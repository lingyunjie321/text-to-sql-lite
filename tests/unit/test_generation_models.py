from dataclasses import FrozenInstanceError

import pytest
from pydantic import ValidationError

from app.connectors.metadata import empty_schema_snapshot
from app.generation import (
    GenerationContext,
    GenerationResult,
    GeneratedSQL,
)
from app.schema_linking import SchemaLinkingResult


def test_generated_sql_accepts_exactly_sql_or_clarification() -> None:
    sql_output = GeneratedSQL(sql="  SELECT 1  ")
    clarification = GeneratedSQL(
        clarification_reason="  Which date range should be used?  "
    )

    assert sql_output.sql == "SELECT 1"
    assert sql_output.clarification_reason is None
    assert clarification.sql is None
    assert (
        clarification.clarification_reason
        == "Which date range should be used?"
    )


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"sql": None, "clarification_reason": None},
        {"sql": "", "clarification_reason": None},
        {"sql": "SELECT 1", "clarification_reason": "Choose a store"},
        {"sql": "SELECT 1", "unexpected": "value"},
    ],
)
def test_generated_sql_rejects_invalid_structured_output(
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        GeneratedSQL.model_validate(payload)


def test_generation_contracts_are_frozen() -> None:
    snapshot = empty_schema_snapshot()
    linking = SchemaLinkingResult(
        candidate_tables=(),
        candidate_fields=(),
        join_paths=(),
        schema_version=snapshot.schema_version,
        top_k=10,
    )
    context = GenerationContext(
        question="List films",
        normalized_question="List films",
        normalized_time=None,
        dialect="postgres",
        schema_linking=linking,
        snapshot=snapshot,
    )
    output = GeneratedSQL(sql="SELECT 1")
    result = GenerationResult(
        output=output,
        input_tokens=12,
        output_tokens=4,
        model="test-model",
        prompt_version="mvp-v1",
    )

    with pytest.raises(FrozenInstanceError):
        context.dialect = "mysql"  # type: ignore[misc]
    with pytest.raises(ValidationError):
        output.sql = "SELECT 2"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        result.input_tokens = 0  # type: ignore[misc]
    assert context.max_result_rows == 1000
