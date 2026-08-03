from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock

from fastapi.testclient import TestClient

from app.api import ApplicationServices, create_app
from app.connectors.catalog import (
    DiscoveredMetadata,
    RelationIdentity,
)
from app.connectors.metadata import (
    ColumnMetadata,
    ForeignKeyMetadata,
    PrimaryKeyMetadata,
    TableMetadata,
    build_schema_snapshot,
)
from app.local.credential_store import InMemoryCredentialStore
from app.local.datasource_service import DatasourceProfileService
from app.local.datasource_runtime import DatasourceRuntimeError
from app.local.model_service import ModelProfileService
from app.local.profile_store import LocalProfileStore
from app.workflow import WorkflowContext
from tests.routing_support import single_provider_test_routing


def _discovered_metadata() -> DiscoveredMetadata:
    actor = TableMetadata(
        schema_name="public",
        table_name="actor",
        relation_kind="table",
        comment="not exposed",
        columns=(
            ColumnMetadata(
                schema_name="public",
                table_name="actor",
                column_name="actor_id",
                ordinal_position=1,
                data_type="int4",
                formatted_type="integer",
                nullable=False,
                comment="not exposed",
            ),
        ),
    )
    snapshot = build_schema_snapshot(
        tables=(actor,),
        primary_keys=(
            PrimaryKeyMetadata(
                constraint_name="actor_pkey",
                schema_name="public",
                table_name="actor",
                columns=("actor_id",),
            ),
        ),
        foreign_keys=(
            ForeignKeyMetadata(
                constraint_name="actor_staff_fkey",
                source_schema="public",
                source_table="actor",
                source_columns=("actor_id",),
                target_schema="public",
                target_table="staff",
                target_columns=("staff_id",),
            ),
        ),
        unique_constraints=(),
        unique_indexes=(),
    )
    return DiscoveredMetadata(
        snapshot=snapshot,
        relations=(RelationIdentity("public", "actor", "table"),),
        truncated=False,
    )


class _DatasourceRuntimeService:
    def __init__(self) -> None:
        self.discovered = _discovered_metadata()
        self.test_calls = []
        self.validation_calls = []
        self.test_error: Exception | None = None

    def validate_profile(self, profile, password):  # type: ignore[no-untyped-def]
        self.validation_calls.append((profile, password))

    def test_connection(self, config, password):  # type: ignore[no-untyped-def]
        self.test_calls.append((config, password))
        if self.test_error is not None:
            raise self.test_error
        return self.discovered

    def discover_profile(self, profile, password):  # type: ignore[no-untyped-def]
        del profile, password
        return self.discovered


class _RuntimeRegistry:
    def __init__(self) -> None:
        self.invalidated: list[str] = []
        self.error: Exception | None = None

    def invalidate(
        self,
        profile_id: str,
        *,
        expected_profile=None,
    ) -> None:
        del expected_profile
        self.invalidated.append(profile_id)

    def get_or_create(self, profile):  # type: ignore[no-untyped-def]
        if self.error is not None:
            raise self.error
        return object()


def _services(tmp_path: Path) -> ApplicationServices:
    store = LocalProfileStore(tmp_path / "config.db")
    credentials = InMemoryCredentialStore()
    runtime_service = _DatasourceRuntimeService()
    runtime_registry = _RuntimeRegistry()
    model_routing = single_provider_test_routing(Mock())

    def runner(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("Profile CRUD must not call the workflow")

    return ApplicationServices(
        context=WorkflowContext(
            connector=Mock(),
            model_routing=model_routing,
            datasource_id="pagila",
            allowed_schemas=("public",),
            allowed_tables=("public.film",),
        ),
        runner=runner,
        model_profiles=ModelProfileService(store, credentials),
        datasource_profiles=DatasourceProfileService(
            store,
            credentials,
            runtime_service=runtime_service,
            runtime_registry=runtime_registry,
        ),
        credential_store=credentials,
        model_routing=model_routing,
        datasource_runtime_service=runtime_service,
        runtime_registry=runtime_registry,
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


def test_datasource_connection_test_returns_only_structure_summary(
    tmp_path: Path,
) -> None:
    services = _services(tmp_path)
    payload = _datasource_payload()
    for key in ("id", "name", "allowed_schemas", "allowed_tables"):
        payload.pop(key)

    with TestClient(create_app(services=services)) as client:
        response = client.post(
            "/api/v1/local/datasources/test",
            json=payload,
        )
        profiles = client.get("/api/v1/local/datasources")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "schemas": ["public"],
        "relations": [
            {"schema": "public", "name": "actor", "kind": "table"}
        ],
        "truncated": False,
        "limits": {
            "timeout_seconds": 30.0,
            "max_relations": 500,
            "max_columns": 10000,
            "max_foreign_keys": 5000,
        },
    }
    assert profiles.json() == []
    assert "stage2-database-secret" not in response.text


def test_datasource_metadata_returns_structure_without_expanding_profile(
    tmp_path: Path,
) -> None:
    services = _services(tmp_path)
    services.runtime_registry.error = RuntimeError(
        "query registry must not serve metadata"
    )
    with TestClient(create_app(services=services)) as client:
        created = client.post(
            "/api/v1/local/datasources",
            json=_datasource_payload(),
        )
        response = client.get(
            "/api/v1/local/datasources/local-postgres/metadata"
        )
        stored = client.get(
            "/api/v1/local/datasources/local-postgres"
        )

    assert created.status_code == 201
    assert response.status_code == 200
    assert response.json() == {
        "datasource_id": "local-postgres",
        "schemas": [
            {
                "name": "public",
                "relations": [
                    {
                        "name": "actor",
                        "kind": "table",
                        "columns": [
                            {
                                "name": "actor_id",
                                "data_type": "integer",
                                "nullable": False,
                            }
                        ],
                        "primary_key": ["actor_id"],
                    }
                ],
            }
        ],
        "foreign_keys": [
            {
                "name": "actor_staff_fkey",
                "source_schema": "public",
                "source_table": "actor",
                "source_columns": ["actor_id"],
                "target_schema": "public",
                "target_table": "staff",
                "target_columns": ["staff_id"],
            }
        ],
        "truncated": False,
        "limits": {
            "timeout_seconds": 30.0,
            "max_relations": 500,
            "max_columns": 10000,
            "max_foreign_keys": 5000,
        },
    }
    assert stored.json()["allowed_tables"] == ["public.orders"]
    for forbidden in ("not exposed", "password", "view_definition"):
        assert forbidden not in response.text


def test_datasource_runtime_errors_use_stable_status_and_code(
    tmp_path: Path,
) -> None:
    services = _services(tmp_path)
    runtime_service = services.datasource_runtime_service
    assert isinstance(runtime_service, _DatasourceRuntimeService)
    runtime_service.test_error = DatasourceRuntimeError(
        code="DATASOURCE_METADATA_TIMEOUT",
        public_message="Datasource metadata discovery timed out.",
        status_code=504,
    )
    payload = _datasource_payload()
    for key in ("id", "name", "allowed_schemas", "allowed_tables"):
        payload.pop(key)

    with TestClient(create_app(services=services)) as client:
        response = client.post(
            "/api/v1/local/datasources/test",
            json=payload,
        )

    assert response.status_code == 504
    assert response.json() == {
        "detail": {
            "code": "DATASOURCE_METADATA_TIMEOUT",
            "message": "Datasource metadata discovery timed out.",
        }
    }


def test_metadata_distinguishes_missing_profile_and_missing_credential(
    tmp_path: Path,
) -> None:
    services = _services(tmp_path)
    payload = _datasource_payload()
    with TestClient(create_app(services=services)) as client:
        missing_profile = client.get(
            "/api/v1/local/datasources/missing/metadata"
        )
        client.post("/api/v1/local/datasources", json=payload)
        payload["password"] = None
        client.put(
            "/api/v1/local/datasources/local-postgres",
            json=payload,
        )
        missing_credential = client.get(
            "/api/v1/local/datasources/local-postgres/metadata"
        )

    assert missing_profile.status_code == 404
    assert missing_profile.json()["detail"]["code"] == (
        "DATASOURCE_PROFILE_NOT_FOUND"
    )
    assert missing_credential.status_code == 409
    assert missing_credential.json()["detail"]["code"] == (
        "DATASOURCE_CREDENTIAL_MISSING"
    )


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
        payload["password"] = None
        explicitly_cleared = client.put(
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
    assert cleared.json()["password_status"] == "configured"
    assert explicitly_cleared.json()["password_status"] == "missing"
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
    assert set(
        schema["paths"]["/api/v1/local/datasources/test"]
    ) == {"post"}
    assert set(
        schema["paths"][
            "/api/v1/local/datasources/{profile_id}/metadata"
        ]
    ) == {"get"}
    model_create = schema["components"]["schemas"]["ModelProfileCreate"]
    datasource_create = schema["components"]["schemas"][
        "DatasourceProfileCreate"
    ]
    assert model_create["properties"]["api_key"]["writeOnly"] is True
    assert datasource_create["properties"]["password"]["writeOnly"] is True
    datasource_test = schema["components"]["schemas"][
        "DatasourceConnectionTestRequest"
    ]
    assert datasource_test["properties"]["password"]["writeOnly"] is True
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
            "504",
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
            "504",
        },
        ("/api/v1/local/datasources/{profile_id}", "delete"): {
            "204",
            "404",
            "422",
            "500",
            "503",
        },
        ("/api/v1/local/datasources/test", "post"): {
            "200",
            "409",
            "422",
            "500",
            "503",
            "504",
        },
        (
            "/api/v1/local/datasources/{profile_id}/metadata",
            "get",
        ): {
            "200",
            "404",
            "409",
            "422",
            "500",
            "503",
            "504",
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
