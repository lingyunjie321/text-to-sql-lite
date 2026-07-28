from collections.abc import Sequence
from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient

from app.api import ApplicationServices, create_app
from app.connectors.postgresql import PostgreSQLConnector
from app.connectors.models import ExecutionResult
from app.generation import (
    GenerationResult,
    GeneratedSQL,
    LLMMessage,
)
from app.workflow import WorkflowContext


@dataclass
class ScriptedProvider:
    sql_outputs: list[str]

    def __post_init__(self) -> None:
        self.calls: list[tuple[LLMMessage, ...]] = []

    def generate(
        self,
        messages: Sequence[LLMMessage],
    ) -> GenerationResult:
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
    ):
        self.metadata_calls += 1
        return self.connector.read_metadata(
            allowed_schemas,
            allowed_tables,
        )

    def execute(self, sql: str) -> ExecutionResult:
        self.execute_calls.append(sql)
        return self.connector.execute(sql)

    def _consume_retry_count(self) -> int:
        return self.connector._consume_retry_count()


def _client(
    connector: PostgreSQLConnector,
    sql_outputs: list[str],
) -> tuple[TestClient, ScriptedProvider, CountingConnector]:
    provider = ScriptedProvider(sql_outputs)
    counted = CountingConnector(connector)
    app = create_app(
        services=ApplicationServices(
            context=WorkflowContext(
                provider=provider,
                connector=counted,
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
