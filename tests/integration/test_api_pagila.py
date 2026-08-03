from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.api import ApplicationServices, create_app
from app.api.context_factory import WorkflowContextFactory
from app.connectors.postgresql import PostgreSQLConnector
from app.connectors.models import ExecutionResult
from app.generation import (
    GenerationResult,
    GeneratedSQL,
    LLMMessage,
    ModelProviderFactory,
)
from app.local.credential_store import InMemoryCredentialStore
from app.local.datasource_service import DatasourceProfileService
from app.local.model_runtime import ModelRuntimeService
from app.local.model_runtime_registry import ModelRuntimeRegistry
from app.local.model_service import ModelProfileService
from app.local.profile_models import DatasourceProfile, ModelProfile
from app.local.profile_resolver import StaticProfileResolver
from app.local.profile_store import LocalProfileStore
from app.workflow import WorkflowContext
from tests.routing_support import single_provider_test_routing


@dataclass
class ScriptedProvider:
    sql_outputs: list[str]

    def __post_init__(self) -> None:
        self.calls: list[tuple[LLMMessage, ...]] = []

    def generate(
        self,
        messages: Sequence[LLMMessage],
        *,
        timeout_seconds: float | None = None,
    ) -> GenerationResult:
        del timeout_seconds
        self.calls.append(tuple(messages))
        return GenerationResult(
            output=GeneratedSQL(sql=self.sql_outputs.pop(0)),
            input_tokens=8,
            output_tokens=4,
            model="api-pagila-stub",
            prompt_version="mvp-v1",
        )


class CountingConnector:
    def __init__(self, connector: PostgreSQLConnector) -> None:
        self.connector = connector
        self.metadata_calls = 0
        self.execute_calls: list[str] = []

    def read_metadata(
        self,
        allowed_schemas: tuple[str, ...],
        allowed_tables: tuple[str, ...],
        *,
        timeout_seconds: float | None = None,
    ):
        self.metadata_calls += 1
        return self.connector.read_metadata(
            allowed_schemas,
            allowed_tables,
            timeout_seconds=timeout_seconds,
        )

    def execute(
        self,
        sql: str,
        *,
        timeout_seconds: float | None = None,
    ) -> ExecutionResult:
        self.execute_calls.append(sql)
        return self.connector.execute(
            sql,
            timeout_seconds=timeout_seconds,
        )

    def _consume_retry_count(self) -> int:
        return self.connector._consume_retry_count()


class _StaticDatasourceRuntimeService:
    def validate_profile(self, profile, password):  # type: ignore[no-untyped-def]
        del profile, password


class _StaticRuntimeRegistry:
    def invalidate(
        self,
        profile_id: str,
        *,
        expected_profile=None,
    ) -> None:
        del profile_id, expected_profile


def _client(
    connector: PostgreSQLConnector,
    sql_outputs: list[str],
) -> tuple[TestClient, ScriptedProvider, CountingConnector]:
    provider = ScriptedProvider(sql_outputs)
    counted = CountingConnector(connector)
    app = create_app(
        services=ApplicationServices(
            context=WorkflowContext(
                connector=counted,
                model_routing=single_provider_test_routing(
                    provider
                ),
                datasource_id="pagila",
                allowed_schemas=("public",),
                allowed_tables=("public.film",),
            )
        ),
        id_factory=iter(
            ("req-api-pagila", "trace-api-pagila")
        ).__next__,
    )
    return TestClient(app), provider, counted


@pytest.mark.integration
def test_http_first_pass_executes_pagila(
    connector: PostgreSQLConnector,
) -> None:
    client, provider, counted = _client(
        connector,
        [
            (
                "SELECT film_id, title FROM film "
                "ORDER BY film_id LIMIT 2"
            )
        ],
    )

    with client:
        response = client.post(
            "/api/v1/text-to-sql",
            json={
                "question": "List the first two film titles",
                "schemas": ["public"],
            },
        )

    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "SUCCEEDED_FIRST_PASS"
    assert body["rows"][0] == [1, "ACADEMY DINOSAUR"]
    assert body["returned_row_count"] == 2
    assert body["attempts"] == 1
    assert len(provider.calls) == 1
    assert len(counted.execute_calls) == 1


@pytest.mark.integration
def test_http_legal_empty_result_is_success(
    connector: PostgreSQLConnector,
) -> None:
    client, _, counted = _client(
        connector,
        [
            (
                "SELECT film_id, title FROM film "
                "WHERE film_id < 0"
            )
        ],
    )

    with client:
        response = client.post(
            "/api/v1/text-to-sql",
            json={"question": "Find impossible film identifiers"},
        )

    body = response.json()
    assert body["status"] == "SUCCEEDED_FIRST_PASS"
    assert body["rows"] == []
    assert body["returned_row_count"] == 0
    assert len(counted.execute_calls) == 1


@pytest.mark.integration
def test_http_schema_repair_revalidates_and_executes(
    connector: PostgreSQLConnector,
) -> None:
    client, provider, counted = _client(
        connector,
        [
            "SELECT missing_title FROM film",
            "SELECT film_id, title FROM film ORDER BY film_id LIMIT 2",
        ],
    )

    with client:
        response = client.post(
            "/api/v1/text-to-sql",
            json={"question": "List the first two film titles"},
        )

    body = response.json()
    assert body["status"] == "SUCCEEDED_REPAIRED"
    assert body["attempts"] == 2
    assert body["repair_count"] == 1
    assert len(provider.calls) == 2
    assert len(counted.execute_calls) == 1


@pytest.mark.integration
def test_http_dangerous_model_sql_never_executes(
    connector: PostgreSQLConnector,
) -> None:
    client, provider, counted = _client(
        connector,
        ["DELETE FROM film"],
    )

    with client:
        response = client.post(
            "/api/v1/text-to-sql",
            json={"question": "Delete all films"},
        )

    body = response.json()
    assert body["status"] == "REJECTED_SECURITY"
    assert body["sql"] is None
    assert body["error"]["error_type"] == "PERMISSION_DENIED"
    assert len(provider.calls) == 1
    assert counted.execute_calls == []


@pytest.mark.integration
def test_profile_ids_select_dynamic_model_for_real_pagila_query(
    connector: PostgreSQLConnector,
    tmp_path: Path,
) -> None:
    provider = ScriptedProvider(
        ["SELECT film_id, title FROM film ORDER BY film_id LIMIT 2"]
    )
    counted = CountingConnector(connector)
    credentials = InMemoryCredentialStore()
    store = LocalProfileStore(tmp_path / "config.db")
    model_runtime_service = ModelRuntimeService(
        model_factory=ModelProviderFactory(
            provider_builder=lambda settings: provider
        )
    )
    model_registry = ModelRuntimeRegistry(
        runtime_service=model_runtime_service,
        credential_store=credentials,
    )
    model_profiles = ModelProfileService(
        store,
        credentials,
        runtime_registry=model_registry,
    )
    datasource_registry = _StaticRuntimeRegistry()
    datasource_profiles = DatasourceProfileService(
        store,
        credentials,
        runtime_service=_StaticDatasourceRuntimeService(),  # type: ignore[arg-type]
        runtime_registry=datasource_registry,  # type: ignore[arg-type]
    )
    model_profile = ModelProfile(
        id="local-model",
        name="Local model",
        provider_type="openai_compatible",
        base_url="http://localhost:11434/v1",
        model_name="qwen2.5-coder",
    )
    datasource_profile = DatasourceProfile(
        id="local-pagila",
        name="Local Pagila",
        database_type="postgresql",
        host="127.0.0.1",
        port=5432,
        database="pagila",
        username="reader",
        allowed_schemas=("public",),
        allowed_tables=("public.film",),
    )
    model_profiles.create(model_profile)
    datasource_profiles.create(
        datasource_profile,
        password=SecretStr("integration-only"),
    )
    static_context = WorkflowContext(
        connector=counted,
        model_routing=single_provider_test_routing(Mock()),
        datasource_id=datasource_profile.id,
        allowed_schemas=datasource_profile.allowed_schemas,
        allowed_tables=datasource_profile.allowed_tables,
    )
    resolver = StaticProfileResolver(
        model_profiles=model_profiles,
        datasource_profiles=datasource_profiles,
        contexts={datasource_profile.id: static_context},
        active_model=None,
        active_datasources={datasource_profile.id: datasource_profile},
        model_runtime_registry=model_registry,
        context_factory=WorkflowContextFactory(),
    )
    services = ApplicationServices(
        context=static_context,
        profile_resolver=resolver,
        model_profiles=model_profiles,
        datasource_profiles=datasource_profiles,
        credential_store=credentials,
        model_runtime_service=model_runtime_service,
        model_runtime_registry=model_registry,
    )
    resolved_context = resolver.resolve(
        datasource_profile_id=datasource_profile.id,
        model_profile_id=model_profile.id,
    )

    with TestClient(create_app(services=services)) as client:
        response = client.post(
            "/api/v1/text-to-sql",
            json={
                "question": "List the first two film titles",
                "datasource_id": datasource_profile.id,
                "model_profile_id": model_profile.id,
            },
        )

    assert response.status_code == 200
    assert response.json()["status"] == "SUCCEEDED_FIRST_PASS"
    assert response.json()["rows"][0] == [1, "ACADEMY DINOSAUR"]
    assert resolved_context.retrieval_runtime is None
    assert len(provider.calls) == 1
    assert len(counted.execute_calls) == 1
