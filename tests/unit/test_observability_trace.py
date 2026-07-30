from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api import ApplicationServices, create_app
from app.connectors.metadata import (
    ColumnMetadata,
    TableMetadata,
    build_schema_snapshot,
    empty_schema_snapshot,
)
from app.connectors.models import ExecutionResult, ResultColumn
from app.execution import success_outcome
from app.observability import (
    TraceComplexity,
    TraceRetrieval,
    TracedWorkflowRunner,
    build_trace_record,
)
from app.reflection import (
    record_execution,
    record_validation,
    start_attempt,
)
from app.schema_linking import (
    CandidateField,
    CandidateTable,
    RRFContribution,
    RerankEvidence,
    RerankReason,
    RetrievalEvidence,
    SchemaRetrievalPool,
)
from app.validation import validate_sql
from app.workflow import (
    ComplexityDecision,
    ComplexityReason,
    FinalStatus,
    GenerationObservation,
    NodeTiming,
    QueryComplexity,
    SQLTaskState,
    TokenUsage,
    WorkflowContext,
)
from tests.routing_support import single_provider_test_routing

TRACE_SNAPSHOT = build_schema_snapshot(
    tables=(
        TableMetadata(
            schema_name="public",
            table_name="private_trace_table",
            relation_kind="table",
            comment="private-trace-comment",
            aliases=("private-trace-alias",),
            columns=(
                ColumnMetadata(
                    schema_name="public",
                    table_name="private_trace_table",
                    column_name="private_trace_field",
                    ordinal_position=1,
                    data_type="text",
                    formatted_type="text",
                    nullable=False,
                    comment="private-trace-field-comment",
                ),
            ),
        ),
    ),
    primary_keys=(),
    foreign_keys=(),
    unique_constraints=(),
    unique_indexes=(),
)


def _retrieval_pool() -> SchemaRetrievalPool:
    table_evidence = RetrievalEvidence(
        object_id="public.private_trace_table",
        bm25_rank=1,
        bm25_score=1.0,
        embedding_rank=1,
        embedding_similarity=0.9,
        fusion_rank=1,
        fusion_score=2 / 61,
        contributions=(
            RRFContribution(
                channel="bm25",
                rank=1,
                value=1 / 61,
            ),
            RRFContribution(
                channel="embedding",
                rank=1,
                value=1 / 61,
            ),
        ),
    )
    field_evidence = RetrievalEvidence(
        object_id=(
            "public.private_trace_table.private_trace_field"
        ),
        bm25_rank=1,
        bm25_score=1.0,
        embedding_rank=1,
        embedding_similarity=0.8,
        fusion_rank=1,
        fusion_score=2 / 61,
        contributions=table_evidence.contributions,
    )
    rerank_evidence = RerankEvidence(
        object_id="public.private_trace_table",
        fusion_rank=1,
        rerank_rank=1,
        fusion_score=2 / 61,
        direct_field_count=1,
        approved_alias_count=1,
        required_bridge=False,
        join_connected=False,
        relevant_path_edges=None,
        has_direct_evidence=True,
        reason_codes=(
            RerankReason.FIELD_COVERAGE,
            RerankReason.APPROVED_ALIAS,
        ),
    )
    return SchemaRetrievalPool(
        query_sha256="a" * 64,
        schema_version=TRACE_SNAPSHOT.schema_version,
        authorization_scope_sha256="b" * 64,
        retrieval_version_id="c" * 64,
        retrieval_version_contract="retrieval-version-v1",
        bm25_version="bm25-v1",
        embedding_provider_contract_version=(
            "openai-compatible-embedding-v1"
        ),
        embedding_provider_config_sha256="d" * 64,
        document_version="schema-doc-v1",
        fusion_version="rrf-v1",
        rrf_k=60,
        rerank_version="schema-rerank-v2",
        mode="hybrid",
        ranked_table_ids=("public.private_trace_table",),
        ranked_field_ids=(
            "public.private_trace_table.private_trace_field",
        ),
        table_evidence=(table_evidence,),
        field_evidence=(field_evidence,),
        reranked_table_ids=("public.private_trace_table",),
        rerank_evidence=(rerank_evidence,),
    )


def _terminal_state(
    state: SQLTaskState | None = None,
) -> SQLTaskState:
    sql = "SELECT 'private-row-value' AS value"
    validation = validate_sql(
        sql,
        allowed_schemas=(),
        allowed_tables=(),
        snapshot=empty_schema_snapshot(),
    )
    execution = ExecutionResult(
        columns=(ResultColumn(name="value", type_oid=25),),
        rows=[["private-row-value"]],
        returned_row_count=1,
        truncated=False,
        execution_time_ms=4.5,
    )
    history = record_execution(
        record_validation(start_attempt(sql), validation),
        success_outcome(execution),
    )
    source = state or SQLTaskState(
        request_id="req-trace",
        trace_id="trace-trace",
        question="private-question",
        datasource_id="pagila",
    )
    retrieval_pool = _retrieval_pool()
    return SQLTaskState(
        request_id=source.request_id,
        trace_id=source.trace_id,
        question=source.question,
        datasource_id=source.datasource_id,
        normalized_question="private normalized question",
        allowed_schemas=("public",),
        allowed_tables=("public.private_trace_table",),
        candidate_tables=(
            CandidateTable(
                object_id="public.private_trace_table",
                schema_name="public",
                table_name="private_trace_table",
                relation_kind="table",
                comment="private-candidate-comment",
                score=1.0,
                matched_tokens=("private-candidate-token",),
            ),
        ),
        candidate_fields=(
            CandidateField(
                object_id=(
                    "public.private_trace_table.private_trace_field"
                ),
                schema_name="public",
                table_name="private_trace_table",
                column_name="private_trace_field",
                formatted_type="text",
                nullable=False,
                comment="private-candidate-field-comment",
                score=1.0,
                matched_tokens=("private-field-token",),
            ),
        ),
        schema_version=TRACE_SNAPSHOT.schema_version,
        schema_snapshot=TRACE_SNAPSHOT,
        retrieval_version_id=(
            retrieval_pool.retrieval_version_id
        ),
        schema_retrieval_pool=retrieval_pool,
        probe_candidate_table_count=1,
        probe_candidate_field_count=1,
        complexity_decision=ComplexityDecision(
            level=QueryComplexity.MEDIUM,
            schema_top_k=10,
            reason_codes=(
                ComplexityReason.AGGREGATION_REQUESTED,
            ),
        ),
        current_sql=history.current_attempt.sql,
        sql_attempts=history.attempts,
        seen_sql_fingerprints=history.seen_sql_fingerprints,
        validation_result=history.current_attempt.validation_result,
        execution_result=history.current_attempt.execution_result,
        repair_count=history.repair_count,
        token_usage=TokenUsage(input_tokens=10, output_tokens=4),
        generation_observations=(
            GenerationObservation(
                call_number=1,
                attempt_number=0,
                model_config_id="sk-secret-looking-model-id",
                provider_prompt_version="mvp-v1",
                effective_prompt_version="mvp-v1",
                input_tokens=10,
                output_tokens=4,
            ),
        ),
        node_timings=(
            NodeTiming(
                node="generate_sql",
                duration_ms=3.2,
                attempt_number=0,
                route="validate_sql",
            ),
            NodeTiming(
                node="finalize",
                duration_ms=0.1,
                attempt_number=0,
                route="__end__",
            ),
        ),
        step_count=2,
        infrastructure_retry_count=1,
        final_status=FinalStatus.SUCCEEDED_FIRST_PASS,
    )


def _context() -> WorkflowContext:
    provider = Mock()
    return WorkflowContext(
        connector=Mock(),
        model_routing=single_provider_test_routing(
            provider
        ),
        datasource_id="pagila",
        allowed_schemas=("public",),
        allowed_tables=("public.film",),
        clock=lambda: 0.0,
    )


def test_trace_records_required_safe_workflow_evidence() -> None:
    state = _terminal_state()

    record = build_trace_record(state)

    assert record.request_id == "req-trace"
    assert record.trace_id == "trace-trace"
    assert record.final_status is FinalStatus.SUCCEEDED_FIRST_PASS
    assert record.nodes[0].route == "validate_sql"
    assert record.attempts[0].fingerprint == (
        state.sql_attempts[0].fingerprint
    )
    assert record.input_tokens == 10
    assert record.output_tokens == 4
    assert record.database_duration_ms == 4.5
    assert record.returned_row_count == 1
    assert record.infrastructure_retry_count == 1


def test_trace_records_versioned_complexity_evidence() -> None:
    record = build_trace_record(_terminal_state())

    assert record.complexity is not None
    assert record.complexity.level is QueryComplexity.MEDIUM
    assert record.complexity.schema_top_k == 10
    assert record.complexity.reason_codes == (
        ComplexityReason.AGGREGATION_REQUESTED,
    )
    assert record.complexity.policy_version == "complexity-v1"


def test_trace_records_safe_retrieval_and_rerank_aggregates() -> None:
    record = build_trace_record(_terminal_state())

    assert record.retrieval == TraceRetrieval(
        retrieval_version_id="c" * 64,
        retrieval_version_contract="retrieval-version-v1",
        bm25_version="bm25-v1",
        embedding_provider_contract_version=(
            "openai-compatible-embedding-v1"
        ),
        embedding_provider_config_hash="d" * 64,
        document_version="schema-doc-v1",
        fusion_version="rrf-v1",
        rrf_k=60,
        rerank_version="schema-rerank-v2",
        mode="hybrid",
        embedding_degradation=None,
        candidate_table_count=1,
        candidate_field_count=1,
        probe_table_count=1,
        probe_field_count=1,
        final_table_count=1,
        final_field_count=1,
        embedding_table_count=1,
        embedding_field_count=1,
        fusion_table_count=1,
        fusion_field_count=1,
        rerank_changed_count=0,
        rerank_reason_codes=(
            RerankReason.FIELD_COVERAGE,
            RerankReason.APPROVED_ALIAS,
        ),
        rerank_degraded=False,
    )


@pytest.mark.parametrize(
    "payload",
    (
        {
            "retrieval_version_id": "c" * 64,
            "mode": "hybrid",
            "embedding_degradation": "timeout",
        },
        {
            "retrieval_version_id": "not-a-hash",
            "mode": "hybrid",
        },
        {
            "retrieval_version_id": "c" * 64,
            "mode": "hybrid",
            "rerank_reason_codes": ["field_coverage"],
        },
        {
            "retrieval_version_id": "c" * 64,
            "mode": "hybrid",
            "candidate_table_count": 0,
            "embedding_table_count": 1,
        },
        {
            "retrieval_version_id": "c" * 64,
            "mode": "hybrid",
            "object_id": "private.secret",
        },
    ),
)
def test_trace_retrieval_is_strict_and_allowlisted(
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        TraceRetrieval.model_validate(payload)


@pytest.mark.parametrize(
    "payload",
    (
        {
            "level": "medium",
            "schema_top_k": 10,
            "reason_codes": (
                ComplexityReason.AGGREGATION_REQUESTED,
            ),
            "policy_version": "complexity-v1",
        },
        {
            "level": QueryComplexity.MEDIUM,
            "schema_top_k": 10.0,
            "reason_codes": (
                ComplexityReason.AGGREGATION_REQUESTED,
            ),
            "policy_version": "complexity-v1",
        },
        {
            "level": QueryComplexity.MEDIUM,
            "schema_top_k": True,
            "reason_codes": (
                ComplexityReason.AGGREGATION_REQUESTED,
            ),
            "policy_version": "complexity-v1",
        },
        {
            "level": QueryComplexity.MEDIUM,
            "schema_top_k": 10,
            "reason_codes": [
                ComplexityReason.AGGREGATION_REQUESTED,
            ],
            "policy_version": "complexity-v1",
        },
        {
            "level": QueryComplexity.MEDIUM,
            "schema_top_k": 10,
            "reason_codes": ("aggregation_requested",),
            "policy_version": "complexity-v1",
        },
        {
            "level": QueryComplexity.MEDIUM,
            "schema_top_k": 10,
            "reason_codes": (
                ComplexityReason.AGGREGATION_REQUESTED,
            ),
            "policy_version": "complexity-v2",
        },
        {
            "level": QueryComplexity.SIMPLE,
            "schema_top_k": 5,
            "reason_codes": (
                ComplexityReason.AGGREGATION_REQUESTED,
            ),
            "policy_version": "complexity-v1",
        },
        {
            "level": QueryComplexity.MEDIUM,
            "schema_top_k": 10,
            "reason_codes": (
                ComplexityReason.AGGREGATION_REQUESTED,
            ),
            "policy_version": "complexity-v1",
            "question": "private",
        },
    ),
)
def test_trace_complexity_is_strict_and_allowlisted(
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        TraceComplexity.model_validate(payload)


def test_trace_complexity_is_frozen() -> None:
    evidence = TraceComplexity(
        level=QueryComplexity.MEDIUM,
        schema_top_k=10,
        reason_codes=(ComplexityReason.AGGREGATION_REQUESTED,),
        policy_version="complexity-v1",
    )

    with pytest.raises(ValidationError):
        evidence.schema_top_k = 20  # type: ignore[misc]


def test_trace_serialization_excludes_sensitive_state_values() -> None:
    rendered = build_trace_record(_terminal_state()).model_dump_json()

    for forbidden in (
        "private-question",
        "private normalized question",
        "private-row-value",
        "private_trace_table",
        "private_trace_field",
        "private-trace-comment",
        "private-candidate-token",
        "private-field-token",
        "SELECT 'private-row-value' AS value",
        "sk-secret-looking-model-id",
        '"prompt"',
        '"sql":',
        '"rows":',
        "dsn",
        "api_key",
    ):
        assert forbidden.casefold() not in rendered.casefold()


def test_nonterminal_state_cannot_be_traced() -> None:
    with pytest.raises(ValueError, match="terminal"):
        build_trace_record(
            SQLTaskState(
                request_id="req",
                trace_id="trace",
                question="q",
                datasource_id="pagila",
            )
        )


def test_traced_runner_emits_once_and_returns_same_state() -> None:
    terminal = _terminal_state()
    sink = Mock()
    base_runner = Mock(return_value=terminal)
    runner = TracedWorkflowRunner(base_runner, sink)
    initial = SQLTaskState(
        request_id="req",
        trace_id="trace",
        question="q",
        datasource_id="pagila",
    )

    result = runner(initial, context=_context())

    assert result is terminal
    assert sink.emit.call_count == 1
    assert sink.emit.call_args.args[0].trace_id == "trace-trace"


def test_trace_sink_failure_does_not_change_api_result() -> None:
    class FailingSink:
        def emit(self, record: object) -> None:
            del record
            raise RuntimeError("postgresql://reader:secret@db/pagila")

    def base_runner(
        state: SQLTaskState,
        *,
        context: WorkflowContext,
    ) -> SQLTaskState:
        del context
        return _terminal_state(state)

    app = create_app(
        services=ApplicationServices(
            context=_context(),
            runner=TracedWorkflowRunner(base_runner, FailingSink()),
        ),
        id_factory=iter(("req-api", "trace-api")).__next__,
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/text-to-sql",
            json={"question": "return one"},
        )

    assert response.status_code == 200
    assert response.json()["status"] == "SUCCEEDED_FIRST_PASS"
    assert response.json()["rows"] == [["private-row-value"]]
