from __future__ import annotations

from dataclasses import replace

import pytest
from pydantic import ValidationError

from app.connectors.errors import ErrorType
from app.observability import TraceRetrieval, build_trace_record
from app.schema_linking.embedding import (
    EmbeddingError,
    EmbeddingProviderError,
)
from tests.unit.test_observability_trace import _terminal_state
from tests.unit.test_schema_hybrid_retrieval import (
    HYBRID_SNAPSHOT,
    SemanticEmbeddingProvider,
)


class _Clock:
    def __init__(self, *values: int) -> None:
        self._values = iter(values)

    def __call__(self) -> int:
        return next(self._values)


def _link(
    monkeypatch,
    *,
    provider: SemanticEmbeddingProvider,
    clock_values: tuple[int, ...],
):
    import app.schema_linking.linker as linker_module
    from app.schema_linking import (
        EmbeddingIndexRegistry,
        RetrievalRuntime,
        link_schema,
    )

    monkeypatch.setattr(
        linker_module,
        "perf_counter_ns",
        _Clock(*clock_values),
        raising=False,
    )
    return link_schema(
        "film",
        datasource_id="pagila",
        allowed_schemas=("public",),
        allowed_tables=("public.actor", "public.film"),
        snapshot=HYBRID_SNAPSHOT,
        top_k=5,
        retrieval_runtime=RetrievalRuntime(
            provider=provider,
            registry=EmbeddingIndexRegistry(),
            semantic_version="semantic-v1",
        ),
    )


def test_hybrid_retrieval_records_each_stage_duration(
    monkeypatch,
) -> None:
    result = _link(
        monkeypatch,
        provider=SemanticEmbeddingProvider(),
        clock_values=(
            1_000_000,
            3_000_000,
            10_000_000,
            15_000_000,
            20_000_000,
            27_000_000,
            30_000_000,
            41_000_000,
        ),
    )

    pool = result.retrieval_pool
    assert pool is not None
    assert pool.bm25_duration_ms == 2.0
    assert pool.embedding_duration_ms == 5.0
    assert pool.rrf_duration_ms == 7.0
    assert pool.rerank_duration_ms == 11.0


def test_degraded_paths_record_failed_attempt_and_fallback_duration(
    monkeypatch,
) -> None:
    import app.schema_linking.linker as linker_module

    provider = SemanticEmbeddingProvider(
        query_error=EmbeddingProviderError(
            EmbeddingError(
                error_type=ErrorType.TIMEOUT,
                code="EMBEDDING_TIMEOUT",
                retryable=True,
                public_message="fixed embedding failure",
            )
        )
    )

    def fail_rerank(**_: object) -> object:
        raise RuntimeError("private rerank failure")

    monkeypatch.setattr(
        linker_module,
        "rerank_schema_candidates",
        fail_rerank,
    )
    result = _link(
        monkeypatch,
        provider=provider,
        clock_values=(
            2_000_000,
            3_000_000,
            10_000_000,
            14_000_000,
            20_000_000,
            26_000_000,
            30_000_000,
            38_000_000,
        ),
    )

    pool = result.retrieval_pool
    assert pool is not None
    assert pool.mode == "bm25_only"
    assert pool.embedding_degradation == "timeout"
    assert pool.rerank_degraded is True
    assert pool.bm25_duration_ms == 1.0
    assert pool.embedding_duration_ms == 4.0
    assert pool.rrf_duration_ms == 6.0
    assert pool.rerank_duration_ms == 8.0


def test_materialization_reuses_probe_stage_durations(
    monkeypatch,
) -> None:
    import app.schema_linking.linker as linker_module
    from app.schema_linking import (
        EmbeddingIndexRegistry,
        RetrievalRuntime,
        link_schema,
    )

    provider = SemanticEmbeddingProvider()
    runtime = RetrievalRuntime(
        provider=provider,
        registry=EmbeddingIndexRegistry(),
        semantic_version="semantic-v1",
    )
    monkeypatch.setattr(
        linker_module,
        "perf_counter_ns",
        _Clock(
            1_000_000,
            2_000_000,
            10_000_000,
            12_000_000,
            20_000_000,
            23_000_000,
            30_000_000,
            34_000_000,
            100_000_000,
            150_000_000,
        ),
    )
    common = {
        "datasource_id": "pagila",
        "allowed_schemas": ("public",),
        "allowed_tables": ("public.actor", "public.film"),
        "snapshot": HYBRID_SNAPSHOT,
        "retrieval_runtime": runtime,
    }
    probe = link_schema("film", top_k=20, **common)
    provider_calls = len(provider.calls)
    materialized = link_schema(
        "film",
        top_k=5,
        prepared_pool=probe.retrieval_pool,
        **common,
    )

    assert materialized.retrieval_pool is probe.retrieval_pool
    assert len(provider.calls) == provider_calls
    assert probe.retrieval_pool is not None
    assert probe.retrieval_pool.bm25_duration_ms == 1.0
    assert probe.retrieval_pool.embedding_duration_ms == 2.0
    assert probe.retrieval_pool.rrf_duration_ms == 3.0
    assert probe.retrieval_pool.rerank_duration_ms == 4.0


def test_trace_maps_only_fixed_retrieval_stage_durations() -> None:
    terminal = _terminal_state()
    pool = terminal.schema_retrieval_pool
    assert pool is not None
    timed_pool = replace(
        pool,
        bm25_duration_ms=1.25,
        embedding_duration_ms=2.5,
        rrf_duration_ms=3.75,
        rerank_duration_ms=4.0,
    )
    state = terminal.model_copy(
        update={"schema_retrieval_pool": timed_pool}
    )

    retrieval = build_trace_record(state).retrieval

    assert retrieval is not None
    assert retrieval.bm25_duration_ms == 1.25
    assert retrieval.embedding_duration_ms == 2.5
    assert retrieval.rrf_duration_ms == 3.75
    assert retrieval.rerank_duration_ms == 4.0


@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    tuple(
        (field_name, invalid_value)
        for field_name in (
            "bm25_duration_ms",
            "embedding_duration_ms",
            "rrf_duration_ms",
            "rerank_duration_ms",
        )
        for invalid_value in (
            -0.001,
            float("nan"),
            float("inf"),
            True,
            "1.0",
        )
    ),
)
def test_retrieval_pool_rejects_invalid_stage_duration(
    field_name: str,
    invalid_value: object,
) -> None:
    pool = _terminal_state().schema_retrieval_pool
    assert pool is not None

    with pytest.raises(
        ValueError,
        match="schema retrieval pool is invalid",
    ):
        replace(pool, **{field_name: invalid_value})


@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    tuple(
        (field_name, invalid_value)
        for field_name in (
            "bm25_duration_ms",
            "embedding_duration_ms",
            "rrf_duration_ms",
            "rerank_duration_ms",
        )
        for invalid_value in (
            -0.001,
            float("nan"),
            float("inf"),
            True,
            "1.0",
        )
    ),
)
def test_trace_retrieval_rejects_invalid_stage_duration(
    field_name: str,
    invalid_value: object,
) -> None:
    retrieval = build_trace_record(_terminal_state()).retrieval
    assert retrieval is not None
    payload = retrieval.model_dump()
    payload[field_name] = invalid_value

    with pytest.raises(ValidationError):
        TraceRetrieval.model_validate(payload)
