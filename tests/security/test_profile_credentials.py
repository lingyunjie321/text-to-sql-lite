from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api import ApplicationServices, create_app
from app.api.profile_models import (
    DatasourceProfileCreate,
    ModelConnectionTestRequest,
    ModelProfileCreate,
)
from app.local.credential_store import InMemoryCredentialStore
from app.local.datasource_service import DatasourceProfileService
from app.local.model_service import ModelProfileService
from app.local.model_runtime import ModelConnectionTestResult
from app.local.profile_store import LocalProfileStore
from app.workflow import WorkflowContext
from tests.routing_support import single_provider_test_routing


class _DatasourceRuntimeService:
    def validate_profile(self, profile, password):  # type: ignore[no-untyped-def]
        del profile, password


class _RuntimeRegistry:
    def invalidate(
        self,
        profile_id: str,
        *,
        expected_profile=None,
    ) -> None:
        del profile_id, expected_profile


class _ModelRuntimeService:
    def __init__(self) -> None:
        self.error: Exception | None = None

    def test_connection(self, profile, credentials):  # type: ignore[no-untyped-def]
        del profile, credentials
        if self.error is not None:
            raise self.error
        return ModelConnectionTestResult()


def _services(tmp_path: Path) -> ApplicationServices:
    store = LocalProfileStore(tmp_path / "config.db")
    credentials = InMemoryCredentialStore()
    runtime_service = _DatasourceRuntimeService()
    runtime_registry = _RuntimeRegistry()
    return ApplicationServices(
        context=WorkflowContext(
            connector=Mock(),
            model_routing=single_provider_test_routing(Mock()),
            datasource_id="pagila",
            allowed_schemas=("public",),
            allowed_tables=("public.film",),
        ),
        runner=lambda state, *, context: state,
        model_profiles=ModelProfileService(store, credentials),
        datasource_profiles=DatasourceProfileService(
            store,
            credentials,
            runtime_service=runtime_service,
            runtime_registry=runtime_registry,
        ),
        credential_store=credentials,
        datasource_runtime_service=runtime_service,
        runtime_registry=runtime_registry,
        model_runtime_service=_ModelRuntimeService(),
    )


def _model_payload(api_key: str) -> dict[str, object]:
    return {
        "id": "local-model",
        "name": "Local Model",
        "provider_type": "openai_compatible",
        "base_url": "http://localhost:11434/v1",
        "model_name": "qwen2.5-coder",
        "api_key": api_key,
    }


@pytest.mark.parametrize("api_key", ["", "bad\napi-key", " key-with-space "])
def test_profile_api_rejects_invalid_api_key_without_echo(
    tmp_path: Path,
    api_key: str,
) -> None:
    with TestClient(create_app(services=_services(tmp_path))) as client:
        response = client.post(
            "/api/v1/local/models",
            json=_model_payload(api_key),
    )

    assert response.status_code == 422
    if api_key:
        assert api_key not in response.text


def test_profile_api_never_writes_credentials_to_sqlite_artifacts(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "config.db"
    services = _services(tmp_path)
    model_secret = "stage2-model-artifact-secret"
    database_secret = "stage2-database-artifact-secret"

    with TestClient(create_app(services=services)) as client:
        assert client.post(
            "/api/v1/local/models",
            json=_model_payload(model_secret),
        ).status_code == 201
        assert client.post(
            "/api/v1/local/datasources",
            json={
                "id": "local-postgres",
                "name": "Local PostgreSQL",
                "database_type": "postgresql",
                "host": "127.0.0.1",
                "port": 5432,
                "database": "analytics",
                "username": "reader",
                "allowed_schemas": ["public"],
                "allowed_tables": ["public.orders"],
                "password": database_secret,
            },
        ).status_code == 201

    for artifact in tmp_path.glob("config.db*"):
        content = artifact.read_bytes()
        assert model_secret.encode() not in content
        assert database_secret.encode() not in content
    assert database_path.is_file()


def test_model_connection_test_never_persists_or_returns_credentials(
    tmp_path: Path,
) -> None:
    services = _services(tmp_path)
    generation_secret = "stage4-transient-generation-secret"
    embedding_secret = "stage4-transient-embedding-secret"

    with TestClient(create_app(services=services)) as client:
        response = client.post(
            "/api/v1/local/models/test",
            json={
                "provider_type": "openai_compatible",
                "base_url": "http://localhost:11434/v1",
                "model_name": "qwen2.5-coder",
                "api_key": generation_secret,
                "embedding_base_url": "http://localhost:11434/v1",
                "embedding_model": "nomic-embed-text",
                "embedding_dimension": 768,
                "embedding_api_key": embedding_secret,
            },
        )
        profiles = client.get("/api/v1/local/models")

    assert response.status_code == 200
    assert profiles.json() == []
    assert generation_secret not in response.text
    assert embedding_secret not in response.text
    assert services.credential_store is not None
    assert not services.credential_store.has_model("connection-test")
    for artifact in tmp_path.glob("config.db*"):
        content = artifact.read_bytes()
        assert generation_secret.encode() not in content
        assert embedding_secret.encode() not in content


def test_model_connection_test_validation_hides_credentials() -> None:
    secret = " stage4-transient-validation-secret "

    with pytest.raises(ValidationError) as exc_info:
        ModelConnectionTestRequest.model_validate(
            {
                "provider_type": "openai_compatible",
                "base_url": "http://localhost:11434/v1",
                "model_name": "qwen2.5-coder",
                "api_key": secret,
            }
        )

    assert secret not in str(exc_info.value)
    assert secret not in repr(exc_info.value)


def test_model_connection_test_unexpected_error_does_not_log_secret(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    services = _services(tmp_path)
    secret = "stage4-runtime-log-secret"
    services.model_runtime_service.error = RuntimeError(secret)
    caplog.set_level(logging.WARNING, logger="app.api.routes._profile_common")

    with TestClient(create_app(services=services)) as client:
        response = client.post(
            "/api/v1/local/models/test",
            json={
                "provider_type": "openai_compatible",
                "base_url": "http://localhost:11434/v1",
                "model_name": "qwen2.5-coder",
                "api_key": secret,
            },
        )

    assert response.status_code == 500
    assert secret not in response.text
    assert secret not in caplog.text
    assert [record.getMessage() for record in caplog.records] == [
        "api_profile_unexpected_error"
    ]


def test_profile_validation_exception_text_hides_model_secret() -> None:
    raw_secret = " stage2-validation-model-secret "
    payload = _model_payload(raw_secret)

    with pytest.raises(ValidationError) as exc_info:
        ModelProfileCreate.model_validate(payload)

    assert raw_secret not in str(exc_info.value)
    assert raw_secret not in repr(exc_info.value)


def test_profile_validation_exception_text_hides_database_secret() -> None:
    with pytest.raises(ValidationError) as exc_info:
        DatasourceProfileCreate.model_validate(
            {
                "id": "local-postgres",
                "name": "Local PostgreSQL",
                "database_type": "postgresql",
                "host": "127.0.0.1",
                "port": 5432,
                "database": "analytics",
                "username": "reader",
                "allowed_schemas": ["public"],
                "allowed_tables": ["private.orders"],
                "password": "stage2-validation-database-secret",
            }
        )

    assert "stage2-validation-database-secret" not in str(exc_info.value)
    assert "stage2-validation-database-secret" not in repr(exc_info.value)


def test_profile_validation_exception_text_hides_endpoint_userinfo() -> None:
    with pytest.raises(ValidationError) as exc_info:
        ModelProfileCreate.model_validate(
            {
                "id": "local-model",
                "name": "Local Model",
                "provider_type": "openai_compatible",
                "base_url": (
                    "https://user:stage2-validation-url-secret@"
                    "models.example.test/v1"
                ),
                "model_name": "model",
                "api_key": "another-secret",
            }
        )

    assert "stage2-validation-url-secret" not in str(exc_info.value)
    assert "stage2-validation-url-secret" not in repr(exc_info.value)


def test_profile_routes_require_configured_application_api_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TEXT_TO_SQL_API_KEY", "local-app-api-key")
    app = create_app(services=_services(tmp_path))

    with TestClient(app) as client:
        missing = client.get("/api/v1/local/models")
        wrong = client.get(
            "/api/v1/local/models",
            headers={"Authorization": "Bearer wrong-key"},
        )
        allowed = client.get(
            "/api/v1/local/models",
            headers={"Authorization": "Bearer local-app-api-key"},
        )

    assert missing.status_code == 401
    assert wrong.status_code == 403
    assert allowed.status_code == 200


def test_unexpected_profile_error_logs_only_fixed_context(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    base_services = _services(tmp_path)

    class FailingModelProfiles:
        def list(self):  # type: ignore[no-untyped-def]
            raise RuntimeError(
                "postgresql://reader:stage2-log-secret@db/private"
            )

    services = ApplicationServices(
        context=base_services.context,
        runner=base_services.runner,
        model_profiles=FailingModelProfiles(),  # type: ignore[arg-type]
        datasource_profiles=base_services.datasource_profiles,
        credential_store=base_services.credential_store,
    )
    caplog.set_level(
        logging.WARNING,
        logger="app.api.routes._profile_common",
    )

    with TestClient(create_app(services=services)) as client:
        response = client.get("/api/v1/local/models")

    assert response.status_code == 500
    assert response.json()["detail"]["code"] == "PROFILE_INTERNAL_ERROR"
    assert "stage2-log-secret" not in response.text
    assert "stage2-log-secret" not in caplog.text
    assert [record.getMessage() for record in caplog.records] == [
        "api_profile_unexpected_error"
    ]
    assert caplog.records[0].exc_info is None
