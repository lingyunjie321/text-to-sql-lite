from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import threading

import pytest
from pydantic import SecretStr

from app.local.credential_store import (
    DatasourceCredentials,
    InMemoryCredentialStore,
)
from app.local.datasource_runtime import (
    DatasourceRuntime,
    DatasourceRuntimeError,
)
from app.local.profile_models import DatasourceProfile
from app.local.runtime_registry import RuntimeRegistry


def _profile(profile_id: str = "orders", **overrides: object):
    values: dict[str, object] = {
        "id": profile_id,
        "name": profile_id,
        "database_type": "postgresql",
        "host": "127.0.0.1",
        "port": 5432,
        "database": profile_id,
        "username": "reader",
        "allowed_schemas": ("public",),
        "allowed_tables": ("public.orders",),
    }
    values.update(overrides)
    return DatasourceProfile(**values)


class RuntimeConnectorFake:
    dialect_name = "postgres"

    def __init__(
        self,
        name: str,
        *,
        close_order: list[str] | None = None,
        close_error: Exception | None = None,
    ) -> None:
        self.name = name
        self.close_order = close_order
        self.close_error = close_error
        self.close_count = 0

    def close(self) -> None:
        self.close_count += 1
        if self.close_order is not None:
            self.close_order.append(self.name)
        if self.close_error is not None:
            raise self.close_error


class RuntimeServiceFake:
    def __init__(self, outcomes: list[object]) -> None:
        self.outcomes = outcomes
        self.calls: list[tuple[DatasourceProfile, str]] = []
        self.started: threading.Event | None = None
        self.release: threading.Event | None = None

    def build_runtime(self, profile, password):
        self.calls.append((profile, password.get_secret_value()))
        if self.started is not None and self.release is not None:
            self.started.set()
            assert self.release.wait(timeout=2)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return DatasourceRuntime(
            profile=profile,
            connector=outcome,
            context=object(),
        )


def _credentials(*profile_ids: str) -> InMemoryCredentialStore:
    credentials = InMemoryCredentialStore()
    for profile_id in profile_ids:
        credentials.put_datasource(
            profile_id,
            DatasourceCredentials(password=SecretStr(f"secret-{profile_id}")),
        )
    return credentials


def test_registry_rejects_missing_credential_without_building_runtime():
    service = RuntimeServiceFake([])
    registry = RuntimeRegistry(
        runtime_service=service,
        credential_store=_credentials(),
    )

    with pytest.raises(DatasourceRuntimeError) as captured:
        registry.get_or_create(_profile())

    assert captured.value.code == "DATASOURCE_CREDENTIAL_MISSING"
    assert captured.value.status_code == 409
    assert service.calls == []


def test_registry_reuses_runtime_for_identical_profile():
    connector = RuntimeConnectorFake("orders")
    service = RuntimeServiceFake([connector])
    registry = RuntimeRegistry(
        runtime_service=service,
        credential_store=_credentials("orders"),
    )

    first = registry.get_or_create(_profile())
    second = registry.get_or_create(_profile())

    assert first is second
    assert len(service.calls) == 1
    assert connector.close_count == 0


def test_registry_reuses_runtime_when_only_profile_name_changes():
    connector = RuntimeConnectorFake("orders")
    service = RuntimeServiceFake([connector])
    registry = RuntimeRegistry(
        runtime_service=service,
        credential_store=_credentials("orders"),
    )

    first = registry.get_or_create(_profile(name="Old name"))
    second = registry.get_or_create(_profile(name="New name"))

    assert first is second
    assert len(service.calls) == 1
    assert connector.close_count == 0


def test_failed_build_is_not_cached_and_next_call_retries():
    connector = RuntimeConnectorFake("second")
    service = RuntimeServiceFake(
        [
            DatasourceRuntimeError(
                code="DATASOURCE_CONNECTION_FAILED",
                public_message="The datasource connection failed.",
                status_code=503,
            ),
            connector,
        ]
    )
    registry = RuntimeRegistry(
        runtime_service=service,
        credential_store=_credentials("orders"),
    )

    with pytest.raises(DatasourceRuntimeError):
        registry.get_or_create(_profile())
    runtime = registry.get_or_create(_profile())

    assert runtime.connector is connector
    assert len(service.calls) == 2


def test_concurrent_first_access_builds_only_one_runtime():
    connector = RuntimeConnectorFake("orders")
    service = RuntimeServiceFake([connector])
    service.started = threading.Event()
    service.release = threading.Event()
    registry = RuntimeRegistry(
        runtime_service=service,
        credential_store=_credentials("orders"),
    )

    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [
            executor.submit(registry.get_or_create, _profile())
            for _ in range(4)
        ]
        assert service.started.wait(timeout=2)
        service.release.set()
        runtimes = [future.result(timeout=2) for future in futures]

    assert all(runtime is runtimes[0] for runtime in runtimes)
    assert len(service.calls) == 1


def test_profile_change_closes_old_runtime_before_rebuild():
    first = RuntimeConnectorFake("first")
    second = RuntimeConnectorFake("second")
    service = RuntimeServiceFake([first, second])
    registry = RuntimeRegistry(
        runtime_service=service,
        credential_store=_credentials("orders"),
    )
    original = _profile()
    changed = _profile(database="changed")

    registry.get_or_create(original)
    runtime = registry.get_or_create(changed)

    assert first.close_count == 1
    assert runtime.connector is second
    assert len(service.calls) == 2


def test_invalidate_removes_runtime_even_when_close_fails():
    first = RuntimeConnectorFake(
        "first",
        close_error=RuntimeError("password=private-secret"),
    )
    second = RuntimeConnectorFake("second")
    service = RuntimeServiceFake([first, second])
    registry = RuntimeRegistry(
        runtime_service=service,
        credential_store=_credentials("orders"),
    )

    registry.get_or_create(_profile())
    registry.invalidate("orders")
    runtime = registry.get_or_create(_profile())

    assert first.close_count == 1
    assert runtime.connector is second


def test_close_all_uses_reverse_order_and_continues_after_close_failure():
    close_order: list[str] = []
    first = RuntimeConnectorFake("first", close_order=close_order)
    second = RuntimeConnectorFake(
        "second",
        close_order=close_order,
        close_error=RuntimeError("dsn=private-secret"),
    )
    service = RuntimeServiceFake([first, second])
    registry = RuntimeRegistry(
        runtime_service=service,
        credential_store=_credentials("first", "second"),
    )
    registry.get_or_create(_profile("first"))
    registry.get_or_create(_profile("second"))

    registry.close_all()
    registry.close_all()

    assert close_order == ["second", "first"]
    assert first.close_count == 1
    assert second.close_count == 1
