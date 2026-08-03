from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import threading

import pytest
from pydantic import SecretStr

from app.local.credential_store import (
    InMemoryCredentialStore,
    ModelCredentials,
)
from app.local.model_runtime import ModelRuntimeError
from app.local.profile_models import ModelProfile


def _profile(*, model_name: str = "local-model") -> ModelProfile:
    return ModelProfile(
        id="local-model",
        name="Local Model",
        provider_type="openai_compatible",
        base_url="http://localhost:11434/v1",
        model_name=model_name,
    )


@dataclass(frozen=True)
class _Runtime:
    profile: ModelProfile
    label: str


class _RuntimeService:
    def __init__(self, outcomes: list[object]) -> None:
        self.outcomes = outcomes
        self.calls: list[tuple[ModelProfile, ModelCredentials]] = []
        self.started: threading.Event | None = None
        self.release: threading.Event | None = None

    def build_runtime(
        self,
        profile: ModelProfile,
        credentials: ModelCredentials,
    ) -> object:
        self.calls.append((profile, credentials))
        if self.started is not None and self.release is not None:
            self.started.set()
            assert self.release.wait(timeout=2)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _credentials() -> InMemoryCredentialStore:
    store = InMemoryCredentialStore()
    store.put_model(
        "local-model",
        ModelCredentials(generation_api_key=SecretStr("secret")),
    )
    return store


def test_registry_reuses_runtime_for_same_profile_and_credential_revision() -> None:
    from app.local.model_runtime_registry import ModelRuntimeRegistry

    profile = _profile()
    runtime = _Runtime(profile, "first")
    service = _RuntimeService([runtime])
    registry = ModelRuntimeRegistry(
        runtime_service=service,  # type: ignore[arg-type]
        credential_store=_credentials(),
    )

    assert registry.get_or_create(profile) is runtime
    assert registry.get_or_create(profile) is runtime
    assert len(service.calls) == 1


def test_registry_rebuilds_after_credential_change() -> None:
    from app.local.model_runtime_registry import ModelRuntimeRegistry

    profile = _profile()
    first = _Runtime(profile, "first")
    second = _Runtime(profile, "second")
    credentials = _credentials()
    service = _RuntimeService([first, second])
    registry = ModelRuntimeRegistry(
        runtime_service=service,  # type: ignore[arg-type]
        credential_store=credentials,
    )
    registry.get_or_create(profile)

    credentials.put_model(
        profile.id,
        ModelCredentials(generation_api_key=SecretStr("replacement")),
    )

    assert registry.get_or_create(profile) is second
    assert len(service.calls) == 2


def test_failed_model_runtime_build_is_not_cached() -> None:
    from app.local.model_runtime_registry import ModelRuntimeRegistry

    profile = _profile()
    second = _Runtime(profile, "second")
    service = _RuntimeService(
        [
            ModelRuntimeError(
                code="MODEL_RUNTIME_UNAVAILABLE",
                public_message="The model runtime is unavailable.",
                status_code=503,
            ),
            second,
        ]
    )
    registry = ModelRuntimeRegistry(
        runtime_service=service,  # type: ignore[arg-type]
        credential_store=_credentials(),
    )

    with pytest.raises(ModelRuntimeError):
        registry.get_or_create(profile)

    assert registry.get_or_create(profile) is second
    assert len(service.calls) == 2


def test_concurrent_first_model_access_builds_once() -> None:
    from app.local.model_runtime_registry import ModelRuntimeRegistry

    profile = _profile()
    runtime = _Runtime(profile, "first")
    service = _RuntimeService([runtime])
    service.started = threading.Event()
    service.release = threading.Event()
    registry = ModelRuntimeRegistry(
        runtime_service=service,  # type: ignore[arg-type]
        credential_store=_credentials(),
    )

    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [
            executor.submit(registry.get_or_create, profile)
            for _ in range(4)
        ]
        assert service.started.wait(timeout=2)
        service.release.set()
        runtimes = [future.result(timeout=2) for future in futures]

    assert all(runtime is runtimes[0] for runtime in runtimes)
    assert len(service.calls) == 1


def test_registry_rejects_stale_profile_after_invalidation() -> None:
    from app.local.model_runtime_registry import ModelRuntimeRegistry

    original = _profile()
    changed = _profile(model_name="new-model")
    service = _RuntimeService(
        [_Runtime(original, "first"), _Runtime(changed, "second")]
    )
    registry = ModelRuntimeRegistry(
        runtime_service=service,  # type: ignore[arg-type]
        credential_store=_credentials(),
    )
    registry.get_or_create(original)

    registry.invalidate(original.id, expected_profile=changed)

    with pytest.raises(ModelRuntimeError) as exc_info:
        registry.get_or_create(original)
    assert exc_info.value.code == "MODEL_RUNTIME_STALE"
    assert registry.get_or_create(changed).label == "second"


def test_registry_close_all_clears_runtime_and_expected_identity() -> None:
    from app.local.model_runtime_registry import ModelRuntimeRegistry

    profile = _profile()
    first = _Runtime(profile, "first")
    second = _Runtime(profile, "second")
    service = _RuntimeService([first, second])
    registry = ModelRuntimeRegistry(
        runtime_service=service,  # type: ignore[arg-type]
        credential_store=_credentials(),
    )
    registry.get_or_create(profile)
    registry.invalidate(profile.id, expected_profile=profile)
    registry.close_all()

    assert registry.get_or_create(profile) is second
