from collections.abc import Sequence
from dataclasses import dataclass

import pytest

from app.connectors.postgresql import PostgreSQLConnector
from app.generation import (
    GenerationResult,
    GeneratedSQL,
    LLMMessage,
)
from app.workflow import (
    FinalStatus,
    WorkflowContext,
    new_task_state,
    run_workflow,
)


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
            model="pagila-stub",
            prompt_version="mvp-v1",
        )


def _run(
    connector: PostgreSQLConnector,
    provider: ScriptedProvider,
):
    return run_workflow(
        new_task_state(
            request_id="req-pagila-workflow",
            trace_id="trace-pagila-workflow",
            question="List the first two film identifiers and titles",
            datasource_id="pagila",
            requested_schemas=("public",),
        ),
        context=WorkflowContext(
            provider=provider,
            connector=connector,
            datasource_id="pagila",
            allowed_schemas=("public",),
            allowed_tables=("public.film",),
        ),
    )


@pytest.mark.integration
def test_workflow_first_pass_executes_against_pagila(
    connector: PostgreSQLConnector,
) -> None:
    provider = ScriptedProvider(
        [
            (
                "SELECT film_id, title FROM film "
                "ORDER BY film_id LIMIT 2"
            )
        ]
    )

    result = _run(connector, provider)

    assert result.final_status is FinalStatus.SUCCEEDED_FIRST_PASS
    assert result.execution_result is not None
    assert result.execution_result.returned_row_count == 2
    assert result.execution_result.rows[0][0] == 1
    assert result.execution_result.rows[0][1] == "ACADEMY DINOSAUR"
    assert len(provider.calls) == 1


@pytest.mark.integration
def test_workflow_schema_repair_revalidates_and_executes_pagila(
    connector: PostgreSQLConnector,
) -> None:
    provider = ScriptedProvider(
        [
            "SELECT missing_title FROM film",
            (
                "SELECT film_id, title FROM film "
                "ORDER BY film_id LIMIT 2"
            ),
        ]
    )

    result = _run(connector, provider)

    assert result.final_status is FinalStatus.SUCCEEDED_REPAIRED
    assert result.repair_count == 1
    assert len(result.sql_attempts) == 2
    assert result.sql_attempts[0].validation_result is not None
    assert result.sql_attempts[0].validation_result.is_valid is False
    assert result.sql_attempts[1].execution_result is not None
    assert result.execution_result is not None
    assert result.execution_result.returned_row_count == 2
    assert len(provider.calls) == 2
