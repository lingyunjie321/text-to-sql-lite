"""Cache and invalidate dynamic model runtimes by Profile identity."""

from __future__ import annotations

import threading

from app.local.credential_store import (
    InMemoryCredentialStore,
    ModelCredentials,
)
from app.local.model_runtime import (
    ModelRuntime,
    ModelRuntimeError,
    ModelRuntimeService,
)
from app.local.profile_models import ModelProfile


class ModelRuntimeRegistry:
    """Thread-safe lazy cache for process-local model runtimes."""

    def __init__(
        self,
        *,
        runtime_service: ModelRuntimeService,
        credential_store: InMemoryCredentialStore,
    ) -> None:
        self._runtime_service = runtime_service
        self._credential_store = credential_store
        self._runtimes: dict[str, ModelRuntime] = {}
        self._runtime_identities: dict[str, tuple[object, ...]] = {}
        self._expected_identities: dict[str, tuple[object, ...]] = {}
        self._lock = threading.RLock()

    def get_or_create(self, profile: ModelProfile) -> ModelRuntime:
        with self._lock:
            identity = self._runtime_identity(profile)
            expected = self._expected_identities.get(profile.id)
            if expected is not None and identity != expected:
                raise _stale_runtime_error()

            cached = self._runtimes.get(profile.id)
            if (
                cached is not None
                and self._runtime_identities.get(profile.id) == identity
            ):
                return cached
            self._runtimes.pop(profile.id, None)
            self._runtime_identities.pop(profile.id, None)

            credentials = (
                self._credential_store.get_model(profile.id)
                or ModelCredentials()
            )
            try:
                runtime = self._runtime_service.build_runtime(
                    profile,
                    credentials,
                )
            except ModelRuntimeError:
                raise
            except Exception:
                raise _unavailable_runtime_error() from None
            if runtime.profile != profile:
                raise _unavailable_runtime_error()
            self._runtimes[profile.id] = runtime
            self._runtime_identities[profile.id] = identity
            return runtime

    def invalidate(
        self,
        profile_id: str,
        *,
        expected_profile: ModelProfile | None = None,
    ) -> None:
        with self._lock:
            if expected_profile is None:
                self._expected_identities.pop(profile_id, None)
            else:
                self._expected_identities[profile_id] = (
                    self._runtime_identity(expected_profile)
                )
            self._runtimes.pop(profile_id, None)
            self._runtime_identities.pop(profile_id, None)

    def close_all(self) -> None:
        with self._lock:
            self._runtimes.clear()
            self._runtime_identities.clear()
            self._expected_identities.clear()

    def _runtime_identity(
        self,
        profile: ModelProfile,
    ) -> tuple[object, ...]:
        return (
            profile.provider_type,
            str(profile.base_url),
            profile.model_name,
            (
                str(profile.embedding_base_url)
                if profile.embedding_base_url is not None
                else None
            ),
            profile.embedding_model,
            profile.embedding_dimension,
            self._credential_store.model_revision(profile.id),
        )


def _stale_runtime_error() -> ModelRuntimeError:
    return ModelRuntimeError(
        code="MODEL_RUNTIME_STALE",
        public_message="The model profile changed. Please retry.",
        status_code=409,
    )


def _unavailable_runtime_error() -> ModelRuntimeError:
    return ModelRuntimeError(
        code="MODEL_RUNTIME_UNAVAILABLE",
        public_message="The model runtime is unavailable.",
        status_code=503,
    )
