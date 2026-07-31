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
from app.schema_linking import (
    EmbeddingIndexRegistry,
    RetrievalRuntime,
)
from app.workflow import FinalStatus
from evaluation import load_case_suite
from evaluation.runner import evaluate_case
from tests.routing_support import single_provider_test_routing

CASES = load_case_suite(
    Path("evaluation/cases/pagila_mvp.jsonl")
).cases


class ScriptedProvider:
    def __init__(self, outputs: list[str]) -> None:
        self.outputs = outputs

    def generate(
        self,
        messages: Sequence[LLMMessage],
        *,
        timeout_seconds: float | None = None,
    ) -> GenerationResult:
        del timeout_seconds
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


class DeterministicEmbeddingProvider:
    model_id = "pagila-evaluation-embedding-stub"
    dimension = 2
    provider_config_sha256 = "b" * 64

    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []

    def embed(
        self,
        texts: Sequence[str],
        *,
        timeout_seconds: float | None = None,
    ) -> tuple[tuple[float, ...], ...]:
        del timeout_seconds
        self.calls.append(tuple(texts))
        return tuple((1.0, 0.0) for _ in texts)


@pytest.mark.integration
def test_pagila_execute_case_matches_dynamic_gold_result(
    connector: PostgreSQLConnector,
) -> None:
    sink = RecordingSink()

    result = evaluate_case(
        CASES[0],
        connector=connector,
        model_routing=single_provider_test_routing(
            ScriptedProvider(
                ["SELECT film_id, title, rental_rate FROM film"]
            )
        ),
        trace_sink=sink,
    )

    assert result.passed is True
    assert result.comparison is not None
    assert result.comparison.predicted_row_count == 1000
    assert result.comparison.gold_row_count == 1000
    assert len(sink.records) == 1


@pytest.mark.integration
def test_pagila_execute_case_uses_hybrid_retrieval(
    connector: PostgreSQLConnector,
) -> None:
    provider = DeterministicEmbeddingProvider()
    sink = RecordingSink()

    result = evaluate_case(
        CASES[0],
        connector=connector,
        model_routing=single_provider_test_routing(
            ScriptedProvider(
                ["SELECT film_id, title, rental_rate FROM film"]
            )
        ),
        retrieval_runtime=RetrievalRuntime(
            provider=provider,
            registry=EmbeddingIndexRegistry(),
            semantic_version="pagila-evaluation-semantic-v1",
        ),
        trace_sink=sink,
    )

    assert result.passed is True
    # Stage 1 检索增强后，probe(K=20) → 路由 → materialize(K=5/10/20)
    # 可能产生额外的 embedding pass（如 rerank 或 fallback 探测）。
    # 核心断言是 hybrid 模式启用且至少有 probe + materialize 两次调用。
    assert len(provider.calls) >= 2
    assert sink.records[0].retrieval is not None
    assert sink.records[0].retrieval.mode == "hybrid"


@pytest.mark.integration
def test_pagila_dangerous_case_is_zero_execution(
    connector: PostgreSQLConnector,
) -> None:
    result = evaluate_case(
        CASES[15],
        connector=connector,
        model_routing=single_provider_test_routing(
            ScriptedProvider(
                ["SELECT film_id FROM film"]
            )
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
        model_routing=single_provider_test_routing(
            ScriptedProvider(
                ["SELECT film_id, title FROM film"]
            )
        ),
        trace_sink=RecordingSink(),
    )

    assert result.passed is True
    assert result.actual_final_status is FinalStatus.SUCCEEDED_REPAIRED
    assert result.repair_count == 1
    assert result.comparison is not None
    assert result.comparison.passed is True
