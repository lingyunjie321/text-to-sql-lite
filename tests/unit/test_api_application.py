import logging
from collections.abc import Sequence
from pathlib import Path
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api import (
    PAGILA_MVP_ALLOWED_SCHEMAS,
    PAGILA_MVP_ALLOWED_TABLES,
    ApplicationServices,
    create_app,
)
from app.api import application as api_application
from app.api import bootstrap as api_bootstrap
from app.config import (
    DatabaseSettings,
    LLMRouteSettings,
    LLMSettings,
)
from app.connectors.errors import ErrorType
from app.connectors.metadata import empty_schema_snapshot
from app.connectors.models import ExecutionResult, ResultColumn
from app.execution import success_outcome
from app.generation import build_configured_model_routing_runtime
from app.local.profile_store import LocalProfileStore
from app.reflection import (
    record_execution,
    record_validation,
    start_attempt,
)
from app.validation import validate_sql
from app.workflow import (
    FinalStatus,
    REQUEST_TIMEOUT_SECONDS,
    SQLTaskState,
    WorkflowContext,
    WorkflowPublicError,
)
from tests.routing_support import single_provider_test_routing


@pytest.fixture(autouse=True)
def _isolate_production_profile_store(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        api_bootstrap,
        "LocalProfileStore",
        lambda: LocalProfileStore(tmp_path / "config.db"),
    )


def _success_state(state: SQLTaskState) -> SQLTaskState:
    sql = "SELECT 1 AS value"
    validation = validate_sql(
        sql,
        allowed_schemas=(),
        allowed_tables=(),
        snapshot=empty_schema_snapshot(),
    )
    result = ExecutionResult(
        columns=(ResultColumn(name="value", type_oid=23),),
        rows=[[1]],
        returned_row_count=1,
        truncated=False,
        execution_time_ms=0.1,
    )
    history = record_execution(
        record_validation(start_attempt(sql), validation),
        success_outcome(result),
    )
    return SQLTaskState(
        request_id=state.request_id,
        trace_id=state.trace_id,
        question=state.question,
        datasource_id=state.datasource_id,
        requested_schemas=state.requested_schemas,
        current_sql=history.current_attempt.sql,
        sql_attempts=history.attempts,
        seen_sql_fingerprints=history.seen_sql_fingerprints,
        validation_result=history.current_attempt.validation_result,
        execution_result=history.current_attempt.execution_result,
        repair_count=history.repair_count,
        final_status=FinalStatus.SUCCEEDED_FIRST_PASS,
    )


class Runner:
    def __init__(self) -> None:
        self.calls: list[tuple[SQLTaskState, WorkflowContext]] = []

    def __call__(
        self,
        state: SQLTaskState,
        *,
        context: WorkflowContext,
    ) -> SQLTaskState:
        self.calls.append((state, context))
        return _success_state(state)


def _services(runner: Runner) -> ApplicationServices:
    provider = Mock()
    return ApplicationServices(
        context=WorkflowContext(
            connector=Mock(),
            model_routing=single_provider_test_routing(
                provider
            ),
            datasource_id="pagila",
            allowed_schemas=("public",),
            allowed_tables=("public.film",),
            clock=lambda: 0.0,
        ),
        runner=runner,
    )


def test_application_services_allow_profile_only_runtime() -> None:
    services = ApplicationServices(
        contexts={},
        model_runtime_registry=object(),
    )

    assert services.contexts == {}
    assert services.model_routing is None
    with pytest.raises(RuntimeError, match="no datasource contexts"):
        _ = services.context


class _PublicSummaryProvider:
    model_id = "public-model"
    endpoint_summary = "https://models.example.test/v1"

    @property
    def _settings(self) -> object:
        raise AssertionError("API must not read provider private settings")

    def generate(
        self,
        messages,
        *,
        timeout_seconds=None,
    ):  # type: ignore[no-untyped-def]
        raise AssertionError("generation is outside config endpoint tests")


class _ProviderWithoutSummary:
    def generate(
        self,
        messages,
        *,
        timeout_seconds=None,
    ):  # type: ignore[no-untyped-def]
        raise AssertionError("generation is outside config endpoint tests")


class _ProviderWithBrokenSummary:
    @property
    def endpoint_summary(self) -> str:
        raise RuntimeError("secret getter failure")

    @property
    def model_id(self) -> str:
        return "model"

    def generate(
        self,
        messages,
        *,
        timeout_seconds=None,
    ):  # type: ignore[no-untyped-def]
        raise AssertionError("generation is outside config endpoint tests")


def _config_services(provider: object) -> ApplicationServices:
    settings = LLMSettings(
        base_url="https://models.example.test/v1",
        api_key="test-secret",
        model="model",
    )
    route_settings = LLMRouteSettings(
        simple=settings,
        standard=settings,
        complex=settings,
        data_boundary_id="test-boundary",
    )
    routing = build_configured_model_routing_runtime(
        settings=route_settings,
        providers={
            "simple": provider,
            "standard": provider,
            "complex": provider,
        },
    )
    return ApplicationServices(
        context=WorkflowContext(
            connector=Mock(),
            model_routing=routing,
            datasource_id="pagila",
            allowed_schemas=("public",),
            allowed_tables=("public.film",),
        ),
        runner=Runner(),
    )


def _id_factory(values: Sequence[str]):
    pending = iter(values)
    return lambda: next(pending)


def test_post_endpoint_runs_workflow_and_returns_contract() -> None:
    runner = Runner()
    services = _services(runner)
    app = create_app(
        services=services,
        id_factory=_id_factory(("req-1", "trace-1")),
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/text-to-sql",
            json={
                "question": "return one",
                "datasource_id": "pagila",
                "schemas": ["public"],
            },
        )

    assert response.status_code == 200
    # Phase 3 响应扩展字段（schema_candidates / semantic_references /
    # complexity_route / repair_history）属契约一部分；本用例的 workflow
    # 不产生候选与路由数据，因此均为 None。
    assert response.json() == {
        "request_id": "req-1",
        "trace_id": "trace-1",
        "status": "SUCCEEDED_FIRST_PASS",
        "sql": "SELECT 1 AS value",
        "columns": [{"name": "value", "type_oid": 23}],
        "rows": [[1]],
        "returned_row_count": 1,
        "truncated": False,
        "attempts": 1,
        "repair_count": 0,
        "clarification": None,
        "error": None,
        "schema_candidates": None,
        "semantic_references": None,
        "complexity_route": None,
        "repair_history": None,
    }
    assert len(runner.calls) == 1
    state, context = runner.calls[0]
    assert state.request_id == "req-1"
    assert state.trace_id == "trace-1"
    assert state.requested_schemas == ("public",)
    assert context is services.context


def test_invalid_request_returns_422_before_workflow() -> None:
    runner = Runner()
    app = create_app(services=_services(runner))

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/text-to-sql",
            json={"question": "   "},
        )

    assert response.status_code == 422
    assert runner.calls == []


def test_openapi_exposes_only_the_specified_post_endpoint() -> None:
    runner = Runner()
    app = create_app(services=_services(runner))

    schema = app.openapi()

    # POST /api/v1/text-to-sql 是核心契约；GET /health 与 GET /api/v1/config
    # 是只读辅助端点；/local 路由提供 Profile 与阶段 3 数据源能力。
    assert set(schema["paths"]) == {
        "/api/v1/text-to-sql",
        "/api/v1/config",
        "/api/v1/local/models",
        "/api/v1/local/models/{profile_id}",
        "/api/v1/local/datasources",
        "/api/v1/local/datasources/{profile_id}",
        "/api/v1/local/datasources/test",
        "/api/v1/local/datasources/{profile_id}/metadata",
        "/health",
    }
    assert set(schema["paths"]["/health"]) == {"get"}
    assert set(schema["paths"]["/api/v1/config"]) == {"get"}
    assert set(schema["paths"]["/api/v1/text-to-sql"]) == {"post"}
    assert schema["paths"]["/health"]["get"]["operationId"] == (
        "health_health_get"
    )
    assert schema["paths"]["/api/v1/config"]["get"]["operationId"] == (
        "get_config_api_v1_config_get"
    )
    assert set(schema["paths"]["/health"]["get"]["responses"]) == {"200"}
    assert set(schema["paths"]["/api/v1/config"]["get"]["responses"]) == {
        "200"
    }
    assert "security" not in schema["paths"]["/health"]["get"]
    assert "security" not in schema["paths"]["/api/v1/config"]["get"]
    operation = schema["paths"]["/api/v1/text-to-sql"]["post"]
    assert operation["operationId"] == (
        "query_text_to_sql_api_v1_text_to_sql_post"
    )
    assert operation["security"] == [{"HTTPBearer": []}]
    assert set(operation["responses"]) == {
        "200",
        "400",
        "403",
        "404",
        "409",
        "422",
        "500",
        "503",
        "504",
    }
    assert operation["requestBody"]["required"] is True
    assert operation["responses"]["200"]["content"][
        "application/json"
    ]["schema"]["$ref"].endswith("/QueryResponse")
    rows_schema = schema["components"]["schemas"][
        "QueryResponse"
    ]["properties"]["rows"]
    assert rows_schema["items"]["items"]


def test_config_uses_public_provider_metadata_without_private_settings() -> None:
    app = create_app(services=_config_services(_PublicSummaryProvider()))

    with TestClient(app) as client:
        response = client.get("/api/v1/config")

    assert response.status_code == 200
    assert response.json()["models"]["simple"] == {
        "base_url": "https://models.example.test/v1",
        "model_name": "public-model",
    }
    assert response.json()["models"]["standard"] == {
        "base_url": "https://models.example.test/v1",
        "model_name": "public-model",
    }
    assert response.json()["models"]["complex"] == {
        "base_url": "https://models.example.test/v1",
        "model_name": "public-model",
    }
    assert response.json()["models"]["fallback"] == {
        "base_url": "unknown",
        "model_name": "unknown",
    }


def test_config_works_without_static_datasource_context() -> None:
    provider = _PublicSummaryProvider()
    configured = _config_services(provider)
    services = ApplicationServices(
        contexts={},
        runner=lambda state, *, context: state,
        model_routing=configured.model_routing,
    )

    with TestClient(create_app(services=services)) as client:
        response = client.get("/api/v1/config")

    assert response.status_code == 200
    assert response.json()["datasources"] == {}
    assert response.json()["models"]["simple"] == {
        "base_url": provider.endpoint_summary,
        "model_name": provider.model_id,
    }


def test_config_returns_unknown_for_provider_without_public_summary() -> None:
    app = create_app(services=_config_services(_ProviderWithoutSummary()))

    with TestClient(app) as client:
        response = client.get("/api/v1/config")

    assert response.status_code == 200
    assert response.json()["models"]["simple"] == {
        "base_url": "unknown",
        "model_name": "unknown",
    }


def test_broken_public_getter_is_not_silently_reported_as_unknown() -> None:
    from app.api.routes.system import _model_summary

    with pytest.raises(RuntimeError, match="secret getter failure"):
        _model_summary(_config_services(_ProviderWithBrokenSummary()), "simple")


def test_route_modules_expose_the_existing_api_contract() -> None:
    from app.api.routes import create_query_router, system_router

    assert {route.path for route in create_query_router(lambda: "id").routes} == {
        "/api/v1/text-to-sql"
    }
    assert {route.path for route in system_router.routes} == {
        "/health",
        "/api/v1/config",
    }


def test_unexpected_api_error_logs_only_whitelisted_context(
    caplog: pytest.LogCaptureFixture,
) -> None:
    def failing_runner(state, *, context):  # type: ignore[no-untyped-def]
        del state, context
        raise RuntimeError(
            "postgresql://reader:secret@db/pagila SELECT private"
        )

    app = create_app(
        services=ApplicationServices(
            context=_services(Runner()).context,
            runner=failing_runner,
        ),
        id_factory=_id_factory(("req-log", "trace-log")),
    )
    caplog.set_level(logging.WARNING, logger="app.api.routes.query")

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            "/api/v1/text-to-sql",
            json={"question": "private question"},
        )

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "API_INTERNAL_ERROR"
    assert [record.getMessage() for record in caplog.records] == [
        "api_query_unexpected_error"
    ]
    record = caplog.records[0]
    assert record.request_id == "req-log"
    assert record.trace_id == "trace-log"
    assert record.error_category == "unexpected"
    assert record.exc_info is None
    rendered = caplog.text
    for secret in ("secret", "postgresql", "private", "RuntimeError"):
        assert secret not in rendered


def test_application_import_reexports_the_same_auth_dependency() -> None:
    from app.api.dependencies import authenticate

    assert api_application._authenticate is authenticate


def test_two_app_factories_keep_their_id_factories_isolated() -> None:
    first_runner = Runner()
    second_runner = Runner()
    first_app = create_app(
        services=_services(first_runner),
        id_factory=_id_factory(("first-request", "first-trace")),
    )
    second_app = create_app(
        services=_services(second_runner),
        id_factory=_id_factory(("second-request", "second-trace")),
    )

    with TestClient(first_app) as first_client:
        first_response = first_client.post(
            "/api/v1/text-to-sql",
            json={"question": "return one"},
        )
    with TestClient(second_app) as second_client:
        second_response = second_client.post(
            "/api/v1/text-to-sql",
            json={"question": "return one"},
        )

    assert first_response.json()["request_id"] == "first-request"
    assert first_response.json()["trace_id"] == "first-trace"
    assert second_response.json()["request_id"] == "second-request"
    assert second_response.json()["trace_id"] == "second-trace"


def test_injected_services_are_not_closed_after_lifespan() -> None:
    close = Mock()
    services = ApplicationServices(
        context=_services(Runner()).context,
        runner=Runner(),
        close=close,
    )

    with TestClient(create_app(services=services)):
        pass

    close.assert_not_called()


def test_identifier_failure_returns_structured_internal_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    runner = Runner()

    def failing_id_factory() -> str:
        raise RuntimeError("identifier secret")

    app = create_app(
        services=_services(runner),
        id_factory=failing_id_factory,
    )
    caplog.set_level(logging.WARNING, logger="app.api.routes.query")

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            "/api/v1/text-to-sql",
            json={"question": "return one"},
        )

    body = response.json()
    assert response.status_code == 500
    assert body["status"] == "FAILED_INTERNAL"
    assert body["error"]["code"] == "API_INTERNAL_ERROR"
    assert body["request_id"]
    assert body["trace_id"]
    assert "secret" not in response.text
    assert runner.calls == []
    assert [record.getMessage() for record in caplog.records] == [
        "api_query_unexpected_error"
    ]
    assert caplog.records[0].exc_info is None
    assert "secret" not in caplog.text


def test_non_json_workflow_result_returns_structured_internal_error() -> None:
    class NonJsonRunner(Runner):
        def __call__(
            self,
            state: SQLTaskState,
            *,
            context: WorkflowContext,
        ) -> SQLTaskState:
            terminal = super().__call__(state, context=context)
            assert terminal.execution_result is not None
            terminal.execution_result.rows[0][0] = object()  # type: ignore[assignment]
            return terminal

    app = create_app(
        services=_services(NonJsonRunner()),
        id_factory=_id_factory(("req-1", "trace-1")),
    )

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            "/api/v1/text-to-sql",
            json={"question": "return one"},
        )

    body = response.json()
    assert response.status_code == 500
    assert body["status"] == "FAILED_INTERNAL"
    assert body["error"]["code"] == "API_INTERNAL_ERROR"
    assert "Internal Server Error" not in response.text


def test_workflow_timeout_is_preserved_by_http_boundary() -> None:
    def timeout_runner(
        state: SQLTaskState,
        *,
        context: WorkflowContext,
    ) -> SQLTaskState:
        del context
        return SQLTaskState(
            request_id=state.request_id,
            trace_id=state.trace_id,
            question=state.question,
            datasource_id=state.datasource_id,
            error_type=ErrorType.TIMEOUT,
            public_error=WorkflowPublicError(
                error_type=ErrorType.TIMEOUT,
                code="WORKFLOW_TIMEOUT",
                public_message="The request timed out.",
            ),
            final_status=FinalStatus.FAILED_TIMEOUT,
        )

    app = create_app(
        services=ApplicationServices(
            context=_services(Runner()).context,
            runner=timeout_runner,
        ),
        id_factory=_id_factory(("req-1", "trace-1")),
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/text-to-sql",
            json={"question": "return one"},
        )

    assert REQUEST_TIMEOUT_SECONDS == 120
    assert response.status_code == 200
    assert response.json()["status"] == "FAILED_TIMEOUT"
    assert response.json()["error"]["error_type"] == "TIMEOUT"


def test_owned_production_services_are_closed_after_lifespan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    close = Mock()
    services = ApplicationServices(
        context=_services(Runner()).context,
        runner=Runner(),
        close=close,
    )
    monkeypatch.setattr(
        api_application,
        "build_production_services",
        lambda: services,
    )

    with TestClient(create_app()):
        close.assert_not_called()

    close.assert_called_once_with()


def test_production_services_reject_non_pagila_datasource_before_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = DatabaseSettings(
        datasource_id="other",
        dsn="postgresql://reader:secret@127.0.0.1:55432/pagila",
    )
    monkeypatch.setattr(
        api_bootstrap,
        "load_optional_database_settings",
        lambda: settings,
    )
    connector_factory = Mock()
    monkeypatch.setattr(
        api_bootstrap,
        "ConnectorFactory",
        lambda: connector_factory,
    )

    from app.api.bootstrap import ApplicationBootstrapError

    with pytest.raises(ApplicationBootstrapError) as captured:
        api_bootstrap.build_production_services()

    connector_factory.create.assert_not_called()
    assert captured.value.stage == "configuration"


def test_production_manifest_drift_fails_before_llm_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = DatabaseSettings(
        dsn=(
            "postgresql://text_to_sql_reader:secret"
            "@127.0.0.1:55432/pagila"
        ),
    )
    connector = Mock()
    connector.read_metadata.return_value = empty_schema_snapshot()
    llm_loads = 0

    def load_llm() -> None:
        nonlocal llm_loads
        llm_loads += 1
        raise AssertionError("LLM settings loaded too early")

    monkeypatch.setattr(
        api_bootstrap,
        "load_optional_database_settings",
        lambda: settings,
    )
    monkeypatch.setattr(
        api_bootstrap,
        "ConnectorFactory",
        lambda: Mock(create=Mock(return_value=connector)),
    )
    monkeypatch.setattr(
        api_bootstrap,
        "load_optional_llm_route_settings",
        load_llm,
    )
    monkeypatch.setattr(
        api_bootstrap,
        "load_view_semantic_manifest",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            ValueError("view semantic manifest is invalid")
        ),
        raising=False,
    )

    from app.api.bootstrap import ApplicationBootstrapError

    with pytest.raises(ApplicationBootstrapError) as captured:
        api_bootstrap.build_production_services()

    assert llm_loads == 0
    connector.open.assert_called_once_with()
    connector.close.assert_called_once_with()
    assert captured.value.stage == "connector"


def test_production_services_inject_versioned_embedding_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = DatabaseSettings(
        dsn=(
            "postgresql://text_to_sql_reader:secret"
            "@127.0.0.1:55432/pagila"
        ),
    )
    connector = Mock()
    connector.read_metadata.return_value = empty_schema_snapshot()
    semantic_connector = Mock()
    manifest = Mock(enriched_schema_version="a" * 64)
    llm_settings = {
        key: LLMSettings(
            base_url="https://models.example.test/v1",
            api_key="stage1-test-secret",
            model=f"model-{key}",
        )
        for key in ("simple", "standard", "complex")
    }
    llm_route_settings = LLMRouteSettings(
        simple=llm_settings["simple"],
        standard=llm_settings["standard"],
        complex=llm_settings["complex"],
        fallback=None,
        fallback_route_ids=(),
        data_boundary_id="production-test-boundary-v1",
    )
    embedding_settings = object()
    llm_providers = {
        key: Mock(name=f"{key}_provider")
        for key in llm_settings
    }
    llm_provider_factory = Mock(
        side_effect=lambda settings: llm_providers[
            settings.model.removeprefix("model-")
        ]
    )
    embedding_provider = Mock(
        model_id="deterministic-embedding",
        dimension=1024,
        provider_config_sha256="e" * 64,
    )

    monkeypatch.setattr(
        api_bootstrap,
        "load_optional_database_settings",
        lambda: settings,
    )
    monkeypatch.setattr(
        api_bootstrap,
        "ConnectorFactory",
        lambda: Mock(create=Mock(return_value=connector)),
    )
    monkeypatch.setattr(
        api_bootstrap,
        "load_view_semantic_manifest",
        Mock(return_value=manifest),
    )
    monkeypatch.setattr(
        api_bootstrap,
        "FrozenSemanticConnector",
        Mock(return_value=semantic_connector),
    )
    monkeypatch.setattr(
        api_bootstrap,
        "load_optional_llm_route_settings",
        Mock(return_value=llm_route_settings),
    )
    from app.generation.factory import ModelProviderFactory

    monkeypatch.setattr(
        api_bootstrap,
        "ModelProviderFactory",
        lambda: ModelProviderFactory(
            provider_builder=llm_provider_factory,
        ),
    )
    monkeypatch.setattr(
        api_bootstrap,
        "load_optional_embedding_settings",
        Mock(return_value=embedding_settings),
    )
    monkeypatch.setattr(
        api_bootstrap,
        "OpenAICompatibleEmbeddingProvider",
        Mock(return_value=embedding_provider),
    )

    services = api_bootstrap.build_production_services()

    runtime = services.context.retrieval_runtime
    assert runtime is not None
    assert runtime.provider is embedding_provider
    assert runtime.semantic_version == manifest.enriched_schema_version
    assert runtime.registry.resident_version_ids == ()
    model_routing = services.context.model_routing
    assert model_routing is not None
    assert (
        model_routing.route_table.select(
            "simple"
        ).primary.max_input_tokens
        == llm_settings["simple"].max_input_tokens
    )
    assert (
        model_routing.route_table.select(
            "medium"
        ).primary.model_config_sha256
        != model_routing.route_table.select(
            "complex"
        ).primary.model_config_sha256
    )
    assert (
        model_routing.provider_registry.resolve(
            "standard"
        ).provider
        is llm_providers["standard"]
    )
    assert llm_provider_factory.call_count == 3
    connector.open.assert_called_once_with()
    connector.close.assert_not_called()
    assert services.close is not None and callable(services.close)


def test_production_lifespan_starts_profile_only_without_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in (
        "TEXT_TO_SQL_DATABASE_DSN",
        "LLM_BASE_URL",
        "LLM_API_KEY",
        "LLM_MODEL",
        "EMBEDDING_BASE_URL",
        "EMBEDDING_API_KEY",
        "EMBEDDING_MODEL",
        "EMBEDDING_DIMENSION",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(
        "app.config._resolved_env_file",
        lambda env_file: env_file if env_file is not None
        else __import__("pathlib").Path(".env.missing"),
    )

    with TestClient(create_app()) as client:
        response = client.get("/api/v1/local/models")

    assert response.status_code == 200
    assert response.json() == []


def test_importing_asgi_app_does_not_load_credentials() -> None:
    from app.main import app

    assert app.title == "Text-to-SQL Agent"


def test_production_pagila_allowlist_is_explicit_and_excludes_staff() -> None:
    assert PAGILA_MVP_ALLOWED_SCHEMAS == ("public",)
    assert len(PAGILA_MVP_ALLOWED_TABLES) == 13
    assert all(
        table.startswith("public.")
        for table in PAGILA_MVP_ALLOWED_TABLES
    )
    assert "public.staff" not in PAGILA_MVP_ALLOWED_TABLES
