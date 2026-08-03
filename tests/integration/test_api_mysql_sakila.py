"""MySQL 8.4 + Sakila 的 Profile-ID API 真实闭环测试。"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.api import ApplicationServices, create_app
from app.api.context_factory import WorkflowContextFactory
from app.connectors.factory import ConnectorFactory
from app.generation import (
    GenerationResult,
    GeneratedSQL,
    LLMMessage,
    ModelProviderFactory,
)
from app.generation.models import MYSQL_PROMPT_VERSION
from app.local.credential_store import InMemoryCredentialStore
from app.local.datasource_runtime import DatasourceRuntimeService
from app.local.datasource_service import DatasourceProfileService
from app.local.model_service import ModelProfileService
from app.local.model_runtime import ModelRuntimeService
from app.local.model_runtime_registry import ModelRuntimeRegistry
from app.local.profile_models import DatasourceProfile, ModelProfile
from app.local.profile_resolver import StaticProfileResolver
from app.local.profile_store import LocalProfileStore
from app.local.runtime_registry import RuntimeRegistry
from app.observability import TraceRecord, TracedWorkflowRunner
from app.workflow import run_workflow
from tests.routing_support import single_provider_test_routing


def _local_environment() -> dict[str, str]:
    path = Path(".env.mysql.local")
    if not path.is_file():
        return {}
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def _setting(name: str, local_name: str) -> str | None:
    return os.environ.get(name) or _local_environment().get(local_name)


@pytest.fixture(scope="module")
def mysql_connection_values() -> dict[str, object]:
    password = _setting(
        "TEXT_TO_SQL_MYSQL_PASSWORD",
        "MYSQL_APP_PASSWORD",
    )
    if password is None:
        pytest.skip(
            "MySQL API integration requires TEXT_TO_SQL_MYSQL_PASSWORD or "
            ".env.mysql.local"
        )
    return {
        "host": os.environ.get("TEXT_TO_SQL_MYSQL_HOST", "127.0.0.1"),
        "port": int(
            _setting("TEXT_TO_SQL_MYSQL_PORT", "MYSQL_HOST_PORT")
            or "53306"
        ),
        "username": os.environ.get(
            "TEXT_TO_SQL_MYSQL_USERNAME",
            "text_to_sql_reader",
        ),
        "password": password,
        "database": os.environ.get(
            "TEXT_TO_SQL_MYSQL_DATABASE",
            "sakila",
        ),
    }


@dataclass
class ScriptedProvider:
    sql: str

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
            output=GeneratedSQL(sql=self.sql),
            input_tokens=8,
            output_tokens=4,
            model="mysql-sakila-stub",
            prompt_version=messages[0].prompt_version,
        )


class DeterministicEmbeddingProvider:
    model_id = "mysql-sakila-embedding-stub"
    dimension = 2
    provider_config_sha256 = "c" * 64

    def embed(
        self,
        texts: Sequence[str],
        *,
        timeout_seconds: float | None = None,
    ) -> tuple[tuple[float, ...], ...]:
        del timeout_seconds
        return tuple((1.0, 0.0) for _ in texts)


class RecordingSink:
    def __init__(self) -> None:
        self.records: list[TraceRecord] = []

    def emit(self, record: TraceRecord) -> None:
        self.records.append(record)


def _assert_sensitive_value_absent(value: str, sensitive: str) -> None:
    if sensitive and sensitive in value:
        pytest.fail("sensitive datasource value leaked")


@pytest.mark.integration
def test_profile_ids_execute_mysql_sakila_without_leaking_credentials(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    mysql_connection_values: dict[str, object],
) -> None:
    host = str(mysql_connection_values["host"])
    port = int(mysql_connection_values["port"])
    username = str(mysql_connection_values["username"])
    password = str(mysql_connection_values["password"])
    database = str(mysql_connection_values["database"])
    model_api_key = "stage3-model-api-key-must-not-leak"
    datasource_id = "sakila-local"
    model_profile_id = "local-model"

    store = LocalProfileStore(tmp_path / "config.db")
    credentials = InMemoryCredentialStore()
    provider = ScriptedProvider(
        "SELECT actor_id, first_name, last_name FROM actor "
        "ORDER BY actor_id LIMIT 2"
    )
    model_runtime_service = ModelRuntimeService(
        model_factory=ModelProviderFactory(
            provider_builder=lambda settings: provider
        )
    )
    model_runtime_registry = ModelRuntimeRegistry(
        runtime_service=model_runtime_service,
        credential_store=credentials,
    )
    model_profiles = ModelProfileService(
        store,
        credentials,
        runtime_registry=model_runtime_registry,
    )
    model_profile = ModelProfile(
        id=model_profile_id,
        name="Local deterministic model",
        provider_type="openai_compatible",
        base_url="https://models.example.test/v1",
        model_name="mysql-sakila-stub",
    )
    model_profiles.create(
        model_profile,
        generation_api_key=SecretStr(model_api_key),
    )

    model_routing = single_provider_test_routing(provider)
    embedding_provider = DeterministicEmbeddingProvider()
    runtime_service = DatasourceRuntimeService(
        connector_factory=ConnectorFactory(),
        context_factory=WorkflowContextFactory(),
        model_routing=model_routing,
        embedding_provider=embedding_provider,
    )
    registry = RuntimeRegistry(
        runtime_service=runtime_service,
        credential_store=credentials,
    )
    datasource_profiles = DatasourceProfileService(
        store,
        credentials,
        runtime_service=runtime_service,
        runtime_registry=registry,
    )
    datasource_profile = DatasourceProfile(
        id=datasource_id,
        name="Local Sakila",
        database_type="mysql",
        host=host,
        port=port,
        database=database,
        username=username,
        allowed_schemas=("sakila",),
        allowed_tables=("sakila.actor",),
    )
    datasource_profiles.create(
        datasource_profile,
        password=SecretStr(password),
    )

    resolver = StaticProfileResolver(
        model_profiles=model_profiles,
        datasource_profiles=datasource_profiles,
        contexts={},
        active_model=None,
        active_datasources={},
        runtime_registry=registry,
        model_runtime_registry=model_runtime_registry,
        context_factory=WorkflowContextFactory(),
    )
    sink = RecordingSink()
    services = ApplicationServices(
        contexts={},
        runner=TracedWorkflowRunner(run_workflow, sink),
        model_profiles=model_profiles,
        datasource_profiles=datasource_profiles,
        credential_store=credentials,
        profile_resolver=resolver,
        model_routing=model_routing,
        embedding_provider=embedding_provider,
        datasource_runtime_service=runtime_service,
        runtime_registry=registry,
        model_runtime_service=model_runtime_service,
        model_runtime_registry=model_runtime_registry,
    )
    app = create_app(
        services=services,
        id_factory=iter(("req-mysql-sakila", "trace-mysql-sakila")).__next__,
    )
    request_payload = {
        "question": "List the first two actor names",
        "datasource_id": datasource_id,
        "model_profile_id": model_profile_id,
    }

    caplog.set_level(logging.INFO)
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/text-to-sql",
                json=request_payload,
            )
    finally:
        registry.close_all()
        model_runtime_registry.close_all()
        credentials.clear_all()

    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "SUCCEEDED_FIRST_PASS"
    assert body["rows"] == [
        [1, "PENELOPE", "GUINESS"],
        [2, "NICK", "WAHLBERG"],
    ]
    assert body["returned_row_count"] == 2
    assert body["attempts"] == 1
    assert set(request_payload) == {
        "question",
        "datasource_id",
        "model_profile_id",
    }
    assert len(provider.calls) == 1
    assert all(
        message.prompt_version == MYSQL_PROMPT_VERSION
        for message in provider.calls[0]
    )
    assert '"dialect":"mysql"' in provider.calls[0][1].content
    assert len(sink.records) == 1

    dsn = (
        f"mysql://{quote(username, safe='')}:{quote(password, safe='')}@"
        f"{host}:{port}/{quote(database, safe='')}"
    )
    observable_text = "\n".join(
        (
            json.dumps(request_payload, ensure_ascii=False, sort_keys=True),
            response.text,
            sink.records[0].model_dump_json(),
            "\n".join(record.getMessage() for record in caplog.records),
        )
    )
    _assert_sensitive_value_absent(observable_text, password)
    _assert_sensitive_value_absent(observable_text, model_api_key)
    _assert_sensitive_value_absent(observable_text, dsn)
