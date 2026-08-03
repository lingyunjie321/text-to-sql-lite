from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.api import ApplicationServices, create_app
from app.connectors.errors import ErrorType
from app.local.credential_store import InMemoryCredentialStore
from app.local.datasource_service import DatasourceProfileService
from app.local.model_service import ModelProfileService
from app.local.profile_models import DatasourceProfile, ModelProfile
from app.local.profile_resolver import StaticProfileResolver
from app.local.profile_store import LocalProfileStore
from app.local.datasource_runtime import DatasourceRuntimeError
from app.workflow import (
    FinalStatus,
    SQLTaskState,
    WorkflowContext,
    WorkflowPublicError,
)
from tests.routing_support import single_provider_test_routing


class RecordingRunner:
    def __init__(self) -> None:
        self.calls: list[tuple[SQLTaskState, WorkflowContext]] = []

    def __call__(
        self,
        state: SQLTaskState,
        *,
        context: WorkflowContext,
    ) -> SQLTaskState:
        self.calls.append((state, context))
        return SQLTaskState(
            request_id=state.request_id,
            trace_id=state.trace_id,
            question=state.question,
            datasource_id=state.datasource_id,
            requested_schemas=state.requested_schemas,
            error_type=ErrorType.CONNECTION_ERROR,
            public_error=WorkflowPublicError(
                error_type=ErrorType.CONNECTION_ERROR,
                code="TEST_TERMINAL",
                public_message="The test workflow stopped.",
            ),
            final_status=FinalStatus.FAILED_CONNECTION,
        )


class _Connector:
    def __init__(self, dialect_name: str) -> None:
        self.dialect_name = dialect_name


class _RuntimeService:
    def validate_profile(self, profile, password):  # type: ignore[no-untyped-def]
        del profile, password


class _RuntimeRegistry:
    def __init__(self, context: WorkflowContext) -> None:
        self.context = context
        self.get_calls: list[DatasourceProfile] = []
        self.invalidated: list[str] = []
        self.error: Exception | None = None

    def get_or_create(self, profile):  # type: ignore[no-untyped-def]
        self.get_calls.append(profile)
        if self.error is not None:
            raise self.error
        return SimpleNamespace(context=self.context)

    def invalidate(self, profile_id: str) -> None:
        self.invalidated.append(profile_id)


def _model(base_url: str = "https://models.example.test/v1") -> ModelProfile:
    return ModelProfile(
        id="local-model",
        name="Local Model",
        provider_type="openai_compatible",
        base_url=base_url,
        model_name="text-to-sql-model",
    )


def _datasource(host: str = "127.0.0.1") -> DatasourceProfile:
    return DatasourceProfile(
        id="pagila",
        name="Pagila",
        database_type="postgresql",
        host=host,
        port=55432,
        database="pagila",
        username="reader",
        allowed_schemas=("public",),
        allowed_tables=("public.film",),
    )


def _mysql_datasource() -> DatasourceProfile:
    return DatasourceProfile(
        id="pagila",
        name="Sakila",
        database_type="mysql",
        host="127.0.0.1",
        port=3306,
        database="sakila",
        username="reader",
        allowed_schemas=("sakila",),
        allowed_tables=("sakila.film",),
    )


def _services(
    tmp_path: Path,
    runner: RecordingRunner,
) -> tuple[
    ApplicationServices,
    ModelProfileService,
    DatasourceProfileService,
]:
    store = LocalProfileStore(tmp_path / "config.db")
    credentials = InMemoryCredentialStore()
    models = ModelProfileService(store, credentials)
    model_routing = single_provider_test_routing(Mock())
    dynamic_context = WorkflowContext(
        connector=_Connector("postgres"),
        model_routing=model_routing,
        datasource_id="pagila",
        allowed_schemas=("public",),
        allowed_tables=("public.film",),
    )
    runtime_registry = _RuntimeRegistry(dynamic_context)
    runtime_service = _RuntimeService()
    datasources = DatasourceProfileService(
        store,
        credentials,
        runtime_service=runtime_service,
        runtime_registry=runtime_registry,
    )
    models.create(_model())
    datasources.create(_datasource(), password=SecretStr("secret"))
    context = WorkflowContext(
        connector=_Connector("postgres"),
        model_routing=model_routing,
        datasource_id="pagila",
        allowed_schemas=("public",),
        allowed_tables=("public.film",),
    )
    resolver = StaticProfileResolver(
        model_profiles=models,
        datasource_profiles=datasources,
        contexts={"pagila": context},
        active_model=ModelProfile(
            **{
                **_model().model_dump(),
                "id": "environment-model",
                "name": "Environment Model",
            }
        ),
        active_datasources={"pagila": _datasource()},
        runtime_registry=runtime_registry,
    )
    return (
        ApplicationServices(
            contexts={"pagila": context},
            runner=runner,
            model_profiles=models,
            datasource_profiles=datasources,
            credential_store=credentials,
            profile_resolver=resolver,
            model_routing=model_routing,
            datasource_runtime_service=runtime_service,
            runtime_registry=runtime_registry,
        ),
        models,
        datasources,
    )


def test_profile_query_resolves_context_before_workflow(tmp_path: Path) -> None:
    runner = RecordingRunner()
    services, _, _ = _services(tmp_path, runner)

    with TestClient(create_app(services=services)) as client:
        response = client.post(
            "/api/v1/text-to-sql",
            json={
                "question": "List films",
                "datasource_id": "pagila",
                "model_profile_id": "local-model",
                "schemas": ["public"],
            },
        )

    assert response.status_code == 200
    assert response.json()["error"]["code"] == "TEST_TERMINAL"
    assert len(runner.calls) == 1
    state, context = runner.calls[0]
    assert state.datasource_id == "pagila"
    assert state.dialect == "postgres"
    assert context is services.contexts["pagila"]


def test_missing_profile_returns_404_before_workflow(tmp_path: Path) -> None:
    runner = RecordingRunner()
    services, models, _ = _services(tmp_path, runner)
    models.delete("local-model")

    with TestClient(create_app(services=services)) as client:
        response = client.post(
            "/api/v1/text-to-sql",
            json={
                "question": "List films",
                "datasource_id": "pagila",
                "model_profile_id": "local-model",
            },
        )

    assert response.status_code == 404
    assert response.json()["status"] == "FAILED_CONNECTION"
    assert response.json()["error"] == {
        "error_type": "CONNECTION_ERROR",
        "code": "MODEL_PROFILE_NOT_FOUND",
        "message": "The model profile was not found.",
    }
    assert runner.calls == []


def test_non_static_datasource_uses_dynamic_runtime_without_default_fallback(
    tmp_path: Path,
) -> None:
    runner = RecordingRunner()
    services, _, datasources = _services(tmp_path, runner)
    datasources.replace(_datasource(host="localhost"))

    with TestClient(create_app(services=services)) as client:
        response = client.post(
            "/api/v1/text-to-sql",
            json={
                "question": "List films",
                "datasource_id": "pagila",
                "model_profile_id": "local-model",
            },
        )

    assert response.status_code == 200
    assert len(runner.calls) == 1
    assert runner.calls[0][1] is services.runtime_registry.context


def test_dynamic_runtime_failure_keeps_stable_error_without_fallback(
    tmp_path: Path,
) -> None:
    runner = RecordingRunner()
    services, _, datasources = _services(tmp_path, runner)
    datasources.replace(_datasource(host="localhost"))
    services.runtime_registry.error = DatasourceRuntimeError(
        code="DATASOURCE_CREDENTIAL_MISSING",
        public_message="The datasource password is not available.",
        status_code=409,
    )

    with TestClient(create_app(services=services)) as client:
        response = client.post(
            "/api/v1/text-to-sql",
            json={
                "question": "List films",
                "datasource_id": "pagila",
                "model_profile_id": "local-model",
            },
        )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == (
        "DATASOURCE_CREDENTIAL_MISSING"
    )
    assert runner.calls == []


def test_dynamic_mysql_profile_sets_query_state_dialect(tmp_path: Path) -> None:
    runner = RecordingRunner()
    services, _, datasources = _services(tmp_path, runner)
    mysql_profile = _mysql_datasource()
    datasources.replace(mysql_profile)
    services.runtime_registry.context = WorkflowContext(
        connector=_Connector("mysql"),
        model_routing=services.model_routing,
        datasource_id="pagila",
        allowed_schemas=("sakila",),
        allowed_tables=("sakila.film",),
    )

    with TestClient(create_app(services=services)) as client:
        response = client.post(
            "/api/v1/text-to-sql",
            json={
                "question": "List films",
                "datasource_id": "pagila",
                "model_profile_id": "local-model",
            },
        )

    assert response.status_code == 200
    assert runner.calls[0][0].dialect == "mysql"
    assert runner.calls[0][1] is services.runtime_registry.context


def test_profile_mode_without_resolver_returns_safe_409(tmp_path: Path) -> None:
    runner = RecordingRunner()
    services, _, _ = _services(tmp_path, runner)
    unavailable = ApplicationServices(
        contexts=services.contexts,
        runner=runner,
        model_profiles=services.model_profiles,
        datasource_profiles=services.datasource_profiles,
        credential_store=services.credential_store,
    )

    with TestClient(create_app(services=unavailable)) as client:
        response = client.post(
            "/api/v1/text-to-sql",
            json={
                "question": "List films",
                "datasource_id": "pagila",
                "model_profile_id": "local-model",
            },
        )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "PROFILE_RUNTIME_UNAVAILABLE"
    assert runner.calls == []


def test_mixed_profile_and_override_request_is_rejected_before_workflow(
    tmp_path: Path,
) -> None:
    runner = RecordingRunner()
    services, _, _ = _services(tmp_path, runner)

    with TestClient(create_app(services=services)) as client:
        response = client.post(
            "/api/v1/text-to-sql",
            json={
                "question": "List films",
                "datasource_id": "pagila",
                "model_profile_id": "local-model",
                "model_overrides": {
                    "simple": {"model_name": "legacy-model"}
                },
            },
        )

    assert response.status_code == 422
    assert runner.calls == []
