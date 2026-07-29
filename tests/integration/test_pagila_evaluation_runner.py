from collections.abc import Sequence
from pathlib import Path

import pytest

from app.connectors.postgresql import PostgreSQLConnector
from app.generation import (
    GenerationResult,
    GeneratedSQL,
    LLMMessage,
)
from app.observability import TraceRecord
from app.workflow import FinalStatus
from evaluation import load_case_suite
from evaluation.runner import evaluate_case

CASES = load_case_suite(
    Path("evaluation/cases/pagila_mvp.jsonl")
).cases


class ScriptedProvider:
    def __init__(self, outputs: list[str]) -> None:
        self.outputs = outputs

    def generate(
        self,
        messages: Sequence[LLMMessage],
    ) -> GenerationResult:
        assert messages
        return GenerationResult(
            output=GeneratedSQL(sql=self.outputs.pop(0)),
            input_tokens=8,
            output_tokens=4,
            model="pagila-evaluation-stub",
            prompt_version="mvp-v1",
        )


class RecordingSink:
    def __init__(self) -> None:
        self.records: list[TraceRecord] = []

    def emit(self, record: TraceRecord) -> None:
        self.records.append(record)


@pytest.mark.integration
def test_pagila_execute_case_matches_dynamic_gold_result(
    connector: PostgreSQLConnector,
) -> None:
    sink = RecordingSink()

    result = evaluate_case(
        CASES[0],
        connector=connector,
        provider=ScriptedProvider(
            ["SELECT film_id, title, rental_rate FROM film"]
        ),
        trace_sink=sink,
    )

    assert result.passed is True
    assert result.comparison is not None
    assert result.comparison.predicted_row_count == 1000
    assert result.comparison.gold_row_count == 1000
    assert len(sink.records) == 1


@pytest.mark.integration
def test_pagila_dangerous_case_is_zero_execution(
    connector: PostgreSQLConnector,
) -> None:
    result = evaluate_case(
        CASES[15],
        connector=connector,
        provider=ScriptedProvider(
            ["SELECT film_id FROM film"]
        ),
        trace_sink=RecordingSink(),
    )

    assert result.passed is True
    assert result.actual_final_status is FinalStatus.REJECTED_SECURITY
    assert result.prediction_execute_count == 0


@pytest.mark.integration
def test_pagila_reflection_case_repairs_once_and_matches_gold(
    connector: PostgreSQLConnector,
) -> None:
    result = evaluate_case(
        CASES[17],
        connector=connector,
        provider=ScriptedProvider(
            ["SELECT film_id, title FROM film"]
        ),
        trace_sink=RecordingSink(),
    )

    assert result.passed is True
    assert result.actual_final_status is FinalStatus.SUCCEEDED_REPAIRED
    assert result.repair_count == 1
    assert result.comparison is not None
    assert result.comparison.passed is True
