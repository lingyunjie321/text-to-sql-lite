from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock

from fastapi.testclient import TestClient

from app.api import ApplicationServices, create_app
from app.local.credential_store import InMemoryCredentialStore
from app.local.datasource_service import DatasourceProfileService
from app.local.model_service import ModelProfileService
from app.local.profile_store import LocalProfileStore
from app.workflow import WorkflowContext
from tests.routing_support import single_provider_test_routing


def _services(tmp_path: Path) -> ApplicationServices:
    store = LocalProfileStore(tmp_path / "config.db")
    credentials = InMemoryCredentialStore()

    def runner(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("Profile CRUD must not call the workflow")

    return ApplicationServices(
        context=WorkflowContext(
            connector=Mock(),
            model_routing=single_provider_test_routing(Mock()),
            datasource_id="pagila",
            allowed_schemas=("public",),
            allowed_tables=("public.film",),
        ),
        runner=runner,
        model_profiles=ModelProfileService(store, credentials),
        datasource_profiles=DatasourceProfileService(store, credentials),
        credential_store=credentials,
    )


def _model_payload() -> dict[str, object]:
    return {
        "id": "local-model",
        "name": "Local Model",
        "provider_type": "openai_compatible",
        "base_url": "http://localhost:11434/v1",
        "model_name": "qwen2.5-coder",
        "embedding_base_url": None,
        "embedding_model": None,
        "api_key": "stage2-model-secret",
    }


def _datasource_payload() -> dict[str, object]:
    return {
        "id": "local-postgres",
        "name": "Local PostgreSQL",
        "database_type": "postgresql",
        "host": "127.0.0.1",
        "port": 5432,
        "database": "analytics",
        "username": "reader",
        "allowed_schemas": ["public"],
        "allowed_tables": ["public.orders"],
        "password": "stage2-database-secret",
    }


def test_model_profile_crud_never_returns_api_key(tmp_path: Path) -> None:
    app = create_app(services=_services(tmp_path))

    with TestClient(app) as client:
        created = client.post("/api/v1/local/models", json=_model_payload())
        listed = client.get("/api/v1/local/models")
        fetched = client.get("/api/v1/local/models/local-model")

    expected = {
        "id": "local-model",
        "name": "Local Model",
        "provider_type": "openai_compatible",
        "base_url": "http://localhost:11434/v1",
        "model_name": "qwen2.5-coder",
        "embedding_base_url": None,
        "embedding_model": None,
        "generation_credential_status": "configured",
        "embedding_credential_status": "not_applicable",
    }
    assert created.status_code == 201
    assert created.json() == expected
    assert listed.status_code == 200
    assert listed.json() == [expected]
    assert fetched.json() == expected
    for response in (created, listed, fetched):
        assert "stage2-model-secret" not in response.text
        assert "api_key" not in response.json()


def test_model_replace_preserves_omitted_key_and_clears_explicit_null(
    tmp_path: Path,
) -> None:
    app = create_app(services=_services(tmp_path))
    payload = _model_payload()

    with TestClient(app) as client:
        client.post("/api/v1/local/models", json=payload)
        payload["name"] = "Renamed Model"
        payload.pop("api_key")
        preserved = client.put(
            "/api/v1/local/models/local-model",
            json=payload,
        )
        payload["api_key"] = None
        cleared = client.put(
            "/api/v1/local/models/local-model",
            json=payload,
        )

    assert preserved.status_code == 200
    assert preserved.json()["generation_credential_status"] == "configured"
    assert cleared.status_code == 200
    assert cleared.json()["generation_credential_status"] == "missing"


def test_model_delete_and_duplicate_use_stable_errors(tmp_path: Path) -> None:
    app = create_app(services=_services(tmp_path))

    with TestClient(app) as client:
        assert client.post(
            "/api/v1/local/models", json=_model_payload()
        ).status_code == 201
        duplicate = client.post(
            "/api/v1/local/models", json=_model_payload()
        )
        deleted = client.delete("/api/v1/local/models/local-model")
        missing = client.get("/api/v1/local/models/local-model")

    assert duplicate.status_code == 409
    assert duplicate.json() == {
        "detail": {
            "code": "PROFILE_ALREADY_EXISTS",
            "message": "The profile already exists.",
        }
    }
    assert deleted.status_code == 204
    assert deleted.content == b""
    assert missing.status_code == 404
    assert missing.json()["detail"]["code"] == "MODEL_PROFILE_NOT_FOUND"


def test_datasource_profile_crud_never_returns_password(tmp_path: Path) -> None:
    app = create_app(services=_services(tmp_path))

    with TestClient(app) as client:
        created = client.post(
            "/api/v1/local/datasources",
            json=_datasource_payload(),
        )
        listed = client.get("/api/v1/local/datasources")
        fetched = client.get("/api/v1/local/datasources/local-postgres")

    expected = {
        "id": "local-postgres",
        "name": "Local PostgreSQL",
        "database_type": "postgresql",
        "host": "127.0.0.1",
        "port": 5432,
        "database": "analytics",
        "username": "reader",
        "allowed_schemas": ["public"],
        "allowed_tables": ["public.orders"],
        "password_status": "configured",
    }
    assert created.status_code == 201
    assert created.json() == expected
    assert listed.json() == [expected]
    assert fetched.json() == expected
    for response in (created, listed, fetched):
        assert "stage2-database-secret" not in response.text
        assert "password" not in response.json()


def test_datasource_replace_and_delete_follow_secret_semantics(
    tmp_path: Path,
) -> None:
    app = create_app(services=_services(tmp_path))
    payload = _datasource_payload()

    with TestClient(app) as client:
        client.post("/api/v1/local/datasources", json=payload)
        payload["name"] = "Renamed Database"
        payload.pop("password")
        preserved = client.put(
            "/api/v1/local/datasources/local-postgres",
            json=payload,
        )
        payload["host"] = "localhost"
        cleared = client.put(
            "/api/v1/local/datasources/local-postgres",
            json=payload,
        )
        deleted = client.delete(
            "/api/v1/local/datasources/local-postgres"
        )
        missing = client.get(
            "/api/v1/local/datasources/local-postgres"
        )

    assert preserved.json()["password_status"] == "configured"
    assert cleared.json()["password_status"] == "missing"
    assert deleted.status_code == 204
    assert missing.status_code == 404
    assert missing.json()["detail"]["code"] == (
        "DATASOURCE_PROFILE_NOT_FOUND"
    )


def test_profile_validation_error_does_not_echo_secret_input(tmp_path: Path) -> None:
    app = create_app(services=_services(tmp_path))
    payload = _model_payload()
    payload["base_url"] = "https://user:stage2-url-secret@example.test/v1"

    with TestClient(app) as client:
        response = client.post("/api/v1/local/models", json=payload)

    assert response.status_code == 422
    assert response.json() == {
        "detail": [
            {
                "type": "request_validation",
                "loc": ["body"],
                "msg": "Request validation failed.",
            }
        ]
    }
    assert "stage2-url-secret" not in response.text
    assert "stage2-model-secret" not in response.text


def test_profile_routes_fail_closed_when_services_are_not_configured(
    tmp_path: Path,
) -> None:
    services = _services(tmp_path)
    unavailable = ApplicationServices(
        context=services.context,
        runner=services.runner,
    )

    with TestClient(create_app(services=unavailable)) as client:
        response = client.get("/api/v1/local/models")

    assert response.status_code == 503
    assert response.json() == {
        "detail": {
            "code": "PROFILE_SERVICE_UNAVAILABLE",
            "message": "Profile services are unavailable.",
        }
    }


def test_openapi_marks_credentials_write_only_and_registers_crud_paths(
    tmp_path: Path,
) -> None:
    schema = create_app(services=_services(tmp_path)).openapi()

    assert set(schema["paths"]["/api/v1/local/models"]) == {"get", "post"}
    assert set(schema["paths"]["/api/v1/local/models/{profile_id}"]) == {
        "get",
        "put",
        "delete",
    }
    assert set(schema["paths"]["/api/v1/local/datasources"]) == {
        "get",
        "post",
    }
    assert set(
        schema["paths"]["/api/v1/local/datasources/{profile_id}"]
    ) == {"get", "put", "delete"}
    model_create = schema["components"]["schemas"]["ModelProfileCreate"]
    datasource_create = schema["components"]["schemas"][
        "DatasourceProfileCreate"
    ]
    assert model_create["properties"]["api_key"]["writeOnly"] is True
    assert datasource_create["properties"]["password"]["writeOnly"] is True
    assert "api_key" not in schema["components"]["schemas"][
        "ModelProfileResponse"
    ]["properties"]
    assert "password" not in schema["components"]["schemas"][
        "DatasourceProfileResponse"
    ]["properties"]
    query_request = schema["components"]["schemas"]["QueryRequest"]
    assert "model_profile_id" in query_request["properties"]
    assert query_request["properties"]["model_overrides"]["deprecated"] is True
    assert query_request["properties"]["datasource_override"][
        "deprecated"
    ] is True
    expected_responses = {
        ("/api/v1/local/models", "post"): {"201", "409", "422", "500", "503"},
        ("/api/v1/local/models", "get"): {"200", "500", "503"},
        ("/api/v1/local/models/{profile_id}", "get"): {
            "200",
            "404",
            "422",
            "500",
            "503",
        },
        ("/api/v1/local/models/{profile_id}", "put"): {
            "200",
            "404",
            "409",
            "422",
            "500",
            "503",
        },
        ("/api/v1/local/models/{profile_id}", "delete"): {
            "204",
            "404",
            "422",
            "500",
            "503",
        },
        ("/api/v1/local/datasources", "post"): {
            "201",
            "409",
            "422",
            "500",
            "503",
        },
        ("/api/v1/local/datasources", "get"): {"200", "500", "503"},
        ("/api/v1/local/datasources/{profile_id}", "get"): {
            "200",
            "404",
            "422",
            "500",
            "503",
        },
        ("/api/v1/local/datasources/{profile_id}", "put"): {
            "200",
            "404",
            "409",
            "422",
            "500",
            "503",
        },
        ("/api/v1/local/datasources/{profile_id}", "delete"): {
            "204",
            "404",
            "422",
            "500",
            "503",
        },
    }
    for (path, method), expected in expected_responses.items():
        operation = schema["paths"][path][method]
        assert set(operation["responses"]) == expected
        for status_code in expected - {"200", "201", "204", "422"}:
            response_schema = operation["responses"][status_code]["content"][
                "application/json"
            ]["schema"]
            assert response_schema["$ref"].endswith("/ProfileErrorResponse")
