from collections.abc import Sequence
from dataclasses import dataclass

import pytest

import app.schema_linking.linker as linker_module
import app.workflow.complexity as complexity_module
import app.workflow.nodes as workflow_nodes
import app.workflow.nodes.complexity_route as cr_node_module
import app.workflow.nodes.schema_linking as sl_node_module
from app.connectors.errors import (
    DatabaseError,
    ErrorType,
    PostgreSQLConnectorError,
)
from app.connectors.metadata import (
    ColumnMetadata,
    SchemaSnapshot,
    TableMetadata,
    build_schema_snapshot,
)
from app.connectors.models import ExecutionResult, ResultColumn
from app.generation import (
    GenerationResult,
    GeneratedSQL,
    LLMMessage,
)
from app.reflection import RepairStrategy
from app.schema_linking import (
    EmbeddingError,
    EmbeddingIndexRegistry,
    EmbeddingProviderError,
    RetrievalRuntime,
    SchemaTopK,
)
from app.workflow import (
    ComplexityReason,
    FinalStatus,
    NodeTiming,
    SQLTaskState,
    WORKFLOW_NODE_NAMES,
    WorkflowContext,
    build_workflow,
    new_task_state,
    run_workflow,
)
from tests.routing_support import single_provider_test_routing


SNAPSHOT = build_schema_snapshot(
    tables=(
        TableMetadata(
            schema_name="public",
            table_name="film",
            relation_kind="table",
            comment="film catalog",
            columns=(
                ColumnMetadata(
                    schema_name="public",
                    table_name="film",
                    column_name="film_id",
                    ordinal_position=1,
                    data_type="int4",
                    formatted_type="integer",
                    nullable=False,
                    comment="identifier",
                ),
                ColumnMetadata(
                    schema_name="public",
                    table_name="film",
                    column_name="title",
                    ordinal_position=2,
                    data_type="varchar",
                    formatted_type="character varying(255)",
                    nullable=False,
                    comment="film title",
                ),
            ),
        ),
    ),
    primary_keys=(),
    foreign_keys=(),
    unique_constraints=(),
    unique_indexes=(),
)
WIDE_SNAPSHOT = build_schema_snapshot(
    tables=(
        *SNAPSHOT.tables,
        *(
            TableMetadata(
                schema_name="public",
                table_name=f"table_{number:02d}",
                relation_kind="table",
                comment=None,
                columns=(
                    ColumnMetadata(
                        schema_name="public",
                        table_name=f"table_{number:02d}",
                        column_name="entity_id",
                        ordinal_position=1,
                        data_type="int4",
                        formatted_type="integer",
                        nullable=False,
                        comment=None,
                    ),
                ),
            )
            for number in range(23)
        ),
    ),
    primary_keys=(),
    foreign_keys=(),
    unique_constraints=(),
    unique_indexes=(),
)
WIDE_ALLOWED_TABLES = tuple(
    f"{table.schema_name}.{table.table_name}"
    for table in WIDE_SNAPSHOT.tables
)
RESULT = ExecutionResult(
    columns=(ResultColumn(name="title", type_oid=1043),),
    rows=[["ACADEMY DINOSAUR"]],
    returned_row_count=1,
    truncated=False,
    execution_time_ms=0.5,
)


@dataclass
class ScriptedProvider:
    outputs: list[GenerationResult]

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
        return self.outputs.pop(0)


@dataclass
class RecordingEmbeddingProvider:
    model_id: str = "deterministic-embedding"
    dimension: int = 2
    provider_config_sha256: str = "a" * 64

    def __post_init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []
        self.timeouts: list[float | None] = []

    def embed(
        self,
        texts: Sequence[str],
        *,
        timeout_seconds: float | None = None,
    ) -> tuple[tuple[float, ...], ...]:
        self.calls.append(tuple(texts))
        self.timeouts.append(timeout_seconds)
        return tuple((1.0, 0.0) for _ in texts)


class QueryFailingEmbeddingProvider:
    model_id = "deterministic-embedding"
    dimension = 2
    provider_config_sha256 = "a" * 64

    def __init__(self, error: EmbeddingProviderError) -> None:
        self.error = error
        self.calls: list[tuple[str, ...]] = []
        self.timeouts: list[float | None] = []

    def embed(
        self,
        texts: Sequence[str],
        *,
        timeout_seconds: float | None = None,
    ) -> tuple[tuple[float, ...], ...]:
        self.calls.append(tuple(texts))
        self.timeouts.append(timeout_seconds)
        if len(texts) == 1 and not texts[0].startswith("{"):
            raise self.error
        return tuple((1.0, 0.0) for _ in texts)


@dataclass
class StubConnector:
    result: ExecutionResult = RESULT
    snapshot: SchemaSnapshot = SNAPSHOT
    error: DatabaseError | None = None
    metadata_error: DatabaseError | None = None
    execution_errors: tuple[DatabaseError | None, ...] = ()
    retry_counts: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        self.metadata_calls: list[
            tuple[tuple[str, ...], tuple[str, ...]]
        ] = []
        self.metadata_timeouts: list[float | None] = []
        self.execute_calls: list[str] = []
        self.execute_timeouts: list[float | None] = []
        self._pending_retry_counts = list(self.retry_counts)
        self._pending_execution_errors = list(
            self.execution_errors
        )
        self._last_retry_count = 0

    def _record_retries(self) -> None:
        self._last_retry_count = (
            self._pending_retry_counts.pop(0)
            if self._pending_retry_counts
            else 0
        )

    def _consume_retry_count(self) -> int:
        retries = self._last_retry_count
        self._last_retry_count = 0
        return retries

    def read_metadata(
        self,
        allowed_schemas: tuple[str, ...],
        allowed_tables: tuple[str, ...],
        *,
        timeout_seconds: float | None = None,
    ):
        self._record_retries()
        self.metadata_calls.append((allowed_schemas, allowed_tables))
        self.metadata_timeouts.append(timeout_seconds)
        if self.metadata_error is not None:
            raise PostgreSQLConnectorError(self.metadata_error)
        return self.snapshot

    def execute(
        self,
        sql: str,
        *,
        timeout_seconds: float | None = None,
    ) -> ExecutionResult:
        self._record_retries()
        self.execute_calls.append(sql)
        self.execute_timeouts.append(timeout_seconds)
        error = (
            self._pending_execution_errors.pop(0)
            if self._pending_execution_errors
            else self.error
        )
        if error is not None:
            raise PostgreSQLConnectorError(error)
        return self.result


def _generation(
    *,
    sql: str | None = None,
    clarification: str | None = None,
) -> GenerationResult:
    return GenerationResult(
        output=GeneratedSQL(
            sql=sql,
            clarification_reason=clarification,
        ),
        input_tokens=10,
        output_tokens=2,
        model="stub-model",
        prompt_version="mvp-v1",
    )


def _context(
    outputs: list[GenerationResult],
    *,
    connector: StubConnector | None = None,
    allowed_tables: tuple[str, ...] = ("public.film",),
    retrieval_runtime: RetrievalRuntime | None = None,
    clock=lambda: 0.0,
) -> tuple[WorkflowContext, ScriptedProvider, StubConnector]:
    provider = ScriptedProvider(outputs)
    selected_connector = connector or StubConnector()
    return (
        WorkflowContext(
            connector=selected_connector,
            model_routing=single_provider_test_routing(
                provider
            ),
            datasource_id="pagila",
            allowed_schemas=("public",),
            allowed_tables=allowed_tables,
            retrieval_runtime=retrieval_runtime,
            clock=clock,
        ),
        provider,
        selected_connector,
    )


def _state() -> SQLTaskState:
    return new_task_state(
        request_id="req-1",
        trace_id="trace-1",
        question="List film titles",
        datasource_id="pagila",
    )


def test_graph_registers_exactly_ten_nodes_and_two_pass_edges() -> None:
    graph = build_workflow().get_graph()
    business_nodes = set(graph.nodes) - {"__start__", "__end__"}
    edges = {
        (edge.source, edge.target)
        for edge in graph.edges
    }

    assert business_nodes == set(WORKFLOW_NODE_NAMES)
    assert WORKFLOW_NODE_NAMES == (
        "request_preprocess",
        "permission_resolve",
        "schema_linking",
        "complexity_route",
        "generate_sql",
        "validate_sql",
        "execute_sql",
        "reflect_sql",
        "clarification",
        "finalize",
    )
    assert edges == {
        ("__start__", "request_preprocess"),
        ("request_preprocess", "permission_resolve"),
        ("request_preprocess", "clarification"),
        ("request_preprocess", "finalize"),
        ("permission_resolve", "schema_linking"),
        ("permission_resolve", "finalize"),
        ("schema_linking", "complexity_route"),
        ("schema_linking", "generate_sql"),
        ("schema_linking", "clarification"),
        ("schema_linking", "finalize"),
        ("complexity_route", "schema_linking"),
        ("complexity_route", "finalize"),
        ("generate_sql", "validate_sql"),
        ("generate_sql", "clarification"),
        ("generate_sql", "finalize"),
        ("validate_sql", "execute_sql"),
        ("validate_sql", "reflect_sql"),
        ("validate_sql", "finalize"),
        ("execute_sql", "reflect_sql"),
        ("execute_sql", "finalize"),
        ("reflect_sql", "schema_linking"),
        ("reflect_sql", "generate_sql"),
        ("reflect_sql", "clarification"),
        ("reflect_sql", "finalize"),
        ("clarification", "finalize"),
        ("finalize", "__end__"),
    }


def test_first_pass_success_runs_the_full_safe_path() -> None:
    context, provider, connector = _context(
        [_generation(sql="SELECT title FROM film LIMIT 10")]
    )

    result = run_workflow(_state(), context=context)

    assert result.final_status is FinalStatus.SUCCEEDED_FIRST_PASS
    assert result.execution_result is RESULT
    assert result.repair_count == 0
    assert result.complexity_decision is not None
    assert result.complexity_decision.schema_top_k == 5
    assert result.complexity_decision.reason_codes == (
        ComplexityReason.DEFAULT_SIMPLE,
    )
    assert result.error_type is None
    assert result.token_usage.input_tokens == 10
    assert result.token_usage.output_tokens == 2
    assert len(result.generation_observations) == 1
    observation = result.generation_observations[0]
    assert observation.model_config_id == "stub-model"
    assert observation.provider_prompt_version == "mvp-v1"
    assert observation.effective_prompt_version == "mvp-v1"
    assert tuple(item.node for item in result.node_timings) == (
        "request_preprocess",
        "permission_resolve",
        "schema_linking",
        "complexity_route",
        "schema_linking",
        "generate_sql",
        "validate_sql",
        "execute_sql",
        "finalize",
    )
    assert tuple(item.route for item in result.node_timings) == (
        "permission_resolve",
        "schema_linking",
        "complexity_route",
        "schema_linking",
        "generate_sql",
        "validate_sql",
        "execute_sql",
        "finalize",
        "__end__",
    )
    assert tuple(
        item.attempt_number
        for item in result.node_timings
    ) == (None, None, None, None, None, 0, 0, 0, 0)
    assert result.step_count == 9
    assert len(provider.calls) == 1
    assert len(connector.metadata_calls) == 1
    assert connector.execute_calls == [
        "SELECT title FROM film LIMIT 10"
    ]


def test_simple_request_probes_then_materializes_same_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connector = StubConnector(snapshot=WIDE_SNAPSHOT)
    context, _, _ = _context(
        [_generation(sql="SELECT title FROM film LIMIT 10")],
        connector=connector,
        allowed_tables=WIDE_ALLOWED_TABLES,
    )
    calls: list[tuple[SchemaTopK, SchemaSnapshot, int]] = []
    original = sl_node_module.link_schema

    def recording_link_schema(
        question: str,
        *,
        allowed_schemas: tuple[str, ...],
        allowed_tables: tuple[str, ...],
        snapshot: SchemaSnapshot,
        top_k: SchemaTopK,
        deadline_at: float,
        clock,
    ):
        result = original(
            question,
            allowed_schemas=allowed_schemas,
            allowed_tables=allowed_tables,
            snapshot=snapshot,
            top_k=top_k,
            deadline_at=deadline_at,
            clock=clock,
        )
        calls.append((top_k, snapshot, len(result.candidate_tables)))
        return result

    monkeypatch.setattr(
        sl_node_module,
        "link_schema",
        recording_link_schema,
    )

    result = run_workflow(_state(), context=context)

    assert [(top_k, count) for top_k, _, count in calls] == [
        (20, 20),
        (5, 5),
    ]
    assert calls[0][1] is calls[1][1] is WIDE_SNAPSHOT
    assert len(connector.metadata_calls) == 1
    assert result.schema_snapshot is WIDE_SNAPSHOT
    assert result.complexity_decision is not None
    assert result.complexity_decision.schema_top_k == 5
    assert len(result.candidate_tables) == 5
    selected = {
        candidate.object_id for candidate in result.candidate_tables
    }
    assert {
        f"{field.schema_name}.{field.table_name}"
        for field in result.candidate_fields
    }.issubset(selected)
    assert all(set(path.tables).issubset(selected) for path in result.join_paths)


def test_hybrid_retrieval_pool_is_reused_across_two_linking_passes() -> None:
    embedding_provider = RecordingEmbeddingProvider()
    retrieval_runtime = RetrievalRuntime(
        provider=embedding_provider,
        registry=EmbeddingIndexRegistry(),
        semantic_version="semantic-v1",
    )
    context, provider, connector = _context(
        [_generation(sql="SELECT title FROM film LIMIT 10")],
        retrieval_runtime=retrieval_runtime,
    )

    result = run_workflow(_state(), context=context)

    assert result.final_status is FinalStatus.SUCCEEDED_FIRST_PASS
    assert result.schema_retrieval_pool is not None
    assert result.schema_retrieval_pool.mode == "hybrid"
    assert (
        result.retrieval_version_id
        == result.schema_retrieval_pool.retrieval_version_id
    )
    assert len(embedding_provider.calls) == 2
    assert len(embedding_provider.calls[0]) == 3
    assert embedding_provider.calls[1] == ("List film titles",)
    assert len(provider.calls) == 1
    assert len(connector.metadata_calls) == 1
    assert connector.execute_calls == [
        "SELECT title FROM film LIMIT 10"
    ]


@pytest.mark.parametrize(
    (
        "error_type",
        "code",
        "expected_message",
        "expected_status",
    ),
    (
        (
            ErrorType.TIMEOUT,
            "EMBEDDING_TIMEOUT",
            "The embedding request timed out.",
            FinalStatus.FAILED_TIMEOUT,
        ),
        (
            ErrorType.CONNECTION_ERROR,
            "EMBEDDING_CONNECTION_ERROR",
            "The embedding service is unavailable.",
            FinalStatus.FAILED_CONNECTION,
        ),
        (
            ErrorType.UNKNOWN,
            "EMBEDDING_RATE_LIMITED",
            "The embedding service is temporarily busy.",
            FinalStatus.FAILED_INTERNAL,
        ),
        (
            ErrorType.UNKNOWN,
            "EMBEDDING_INVALID_RESPONSE",
            "The embedding response is invalid.",
            FinalStatus.FAILED_INTERNAL,
        ),
    ),
)
def test_embedding_failure_without_bm25_maps_to_safe_public_error(
    error_type: ErrorType,
    code: str,
    expected_message: str,
    expected_status: FinalStatus,
) -> None:
    private_detail = "private-provider-detail-must-not-escape"
    embedding_provider = QueryFailingEmbeddingProvider(
        EmbeddingProviderError(
            EmbeddingError(
                error_type=error_type,
                code=code,
                retryable=False,
                public_message=private_detail,
            )
        )
    )
    retrieval_runtime = RetrievalRuntime(
        provider=embedding_provider,
        registry=EmbeddingIndexRegistry(),
        semantic_version="semantic-v1",
    )
    context, model_provider, connector = _context(
        [],
        retrieval_runtime=retrieval_runtime,
        clock=lambda: 119.5,
    )
    state = new_task_state(
        request_id="req-embedding-failure",
        trace_id="trace-embedding-failure",
        question="semantic-only-query",
        datasource_id="pagila",
    ).model_copy(update={"workflow_started_at": 0.0})

    result = run_workflow(state, context=context)
    from app.observability import build_trace_record

    retrieval_trace = build_trace_record(result).retrieval

    assert result.final_status is expected_status
    assert result.public_error is not None
    assert result.public_error.code == code
    assert result.public_error.public_message == expected_message
    assert private_detail not in repr(result)
    assert embedding_provider.timeouts == [0.5, 0.5]
    assert model_provider.calls == []
    assert connector.execute_calls == []
    assert retrieval_trace is not None
    assert retrieval_trace.outcome == "failed"
    assert retrieval_trace.mode == "hybrid"
    assert retrieval_trace.failure_code == code
    assert retrieval_trace.embedding_degradation is None
    assert retrieval_trace.candidate_table_count == 0
    assert retrieval_trace.candidate_field_count == 0
    assert retrieval_trace.embedding_table_count == 0
    assert retrieval_trace.embedding_field_count == 0
    assert private_detail not in retrieval_trace.model_dump_json()


def test_unknown_embedding_error_code_fails_closed_without_detail() -> None:
    private_detail = "unknown-private-provider-detail"
    embedding_provider = QueryFailingEmbeddingProvider(
        EmbeddingProviderError(
            EmbeddingError(
                error_type=ErrorType.UNKNOWN,
                code="EMBEDDING_PRIVATE_PROVIDER_CODE",
                retryable=False,
                public_message=private_detail,
            )
        )
    )
    retrieval_runtime = RetrievalRuntime(
        provider=embedding_provider,
        registry=EmbeddingIndexRegistry(),
        semantic_version="semantic-v1",
    )
    context, model_provider, connector = _context(
        [],
        retrieval_runtime=retrieval_runtime,
    )
    state = new_task_state(
        request_id="req-embedding-unknown",
        trace_id="trace-embedding-unknown",
        question="semantic-only-query",
        datasource_id="pagila",
    )

    result = run_workflow(state, context=context)

    assert result.final_status is FinalStatus.FAILED_INTERNAL
    assert result.public_error is not None
    assert result.public_error.code == "WORKFLOW_INTERNAL_ERROR"
    assert private_detail not in repr(result)
    assert model_provider.calls == []
    assert connector.execute_calls == []


def test_embedding_failure_keeps_bm25_only_workflow_degradation() -> None:
    private_detail = "degraded-private-provider-detail"
    embedding_provider = QueryFailingEmbeddingProvider(
        EmbeddingProviderError(
            EmbeddingError(
                error_type=ErrorType.TIMEOUT,
                code="EMBEDDING_TIMEOUT",
                retryable=False,
                public_message=private_detail,
            )
        )
    )
    retrieval_runtime = RetrievalRuntime(
        provider=embedding_provider,
        registry=EmbeddingIndexRegistry(),
        semantic_version="semantic-v1",
    )
    context, model_provider, connector = _context(
        [_generation(sql="SELECT title FROM film LIMIT 10")],
        retrieval_runtime=retrieval_runtime,
    )

    result = run_workflow(_state(), context=context)

    assert result.final_status is FinalStatus.SUCCEEDED_FIRST_PASS
    assert result.public_error is None
    assert result.schema_retrieval_pool is not None
    assert result.schema_retrieval_pool.mode == "bm25_only"
    assert (
        result.schema_retrieval_pool.embedding_degradation
        == "timeout"
    )
    assert private_detail not in repr(result)
    assert len(model_provider.calls) == 1
    assert connector.execute_calls == [
        "SELECT title FROM film LIMIT 10"
    ]


def test_generation_canonicalizes_count_column_alias_before_validation() -> None:
    context, _, connector = _context(
        [
            _generation(
                sql=(
                    "SELECT COUNT(film_id) AS rating_count "
                    "FROM film"
                )
            )
        ]
    )

    result = run_workflow(_state(), context=context)

    expected_sql = (
        "SELECT COUNT(film_id) AS film_count FROM film"
    )
    assert result.current_sql == expected_sql
    assert connector.execute_calls == [expected_sql]


def test_model_clarification_never_executes_sql() -> None:
    context, provider, connector = _context(
        [_generation(clarification="Which film range?")]
    )

    result = run_workflow(_state(), context=context)

    assert result.final_status is FinalStatus.CLARIFICATION_REQUIRED
    assert result.clarification is not None
    assert result.execution_result is None
    assert result.sql_attempts == ()
    assert len(provider.calls) == 1
    assert connector.execute_calls == []


def test_legal_empty_result_is_a_success_not_a_repair() -> None:
    empty = ExecutionResult(
        columns=(ResultColumn(name="title", type_oid=1043),),
        rows=[],
        returned_row_count=0,
        truncated=False,
        execution_time_ms=0.2,
    )
    connector = StubConnector(result=empty)
    context, provider, _ = _context(
        [_generation(sql="SELECT title FROM film LIMIT 10")],
        connector=connector,
    )

    result = run_workflow(_state(), context=context)

    assert result.final_status is FinalStatus.SUCCEEDED_FIRST_PASS
    assert result.execution_result is empty
    assert result.execution_result.rows == []
    assert result.repair_count == 0
    assert len(provider.calls) == 1
    assert len(connector.execute_calls) == 1


def test_infrastructure_retries_are_accumulated_in_state() -> None:
    connector = StubConnector(retry_counts=(1, 2))
    context, _, _ = _context(
        [_generation(sql="SELECT title FROM film LIMIT 10")],
        connector=connector,
    )

    result = run_workflow(_state(), context=context)

    assert result.final_status is FinalStatus.SUCCEEDED_FIRST_PASS
    assert result.infrastructure_retry_count == 3


def test_schema_error_relinks_and_accepts_one_distinct_repair(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    top_ks: list[SchemaTopK] = []
    repair_history_flags: list[bool] = []
    original_link_schema = sl_node_module.link_schema
    original_decide_complexity = cr_node_module.decide_complexity

    def recording_link_schema(*args: object, **kwargs: object):
        top_ks.append(kwargs["top_k"])  # type: ignore[arg-type]
        return original_link_schema(*args, **kwargs)  # type: ignore[arg-type]

    def recording_decide_complexity(
        *args: object,
        **kwargs: object,
    ):
        repair_history_flags.append(
            kwargs["has_repair_history"]  # type: ignore[arg-type]
        )
        return original_decide_complexity(
            *args,  # type: ignore[arg-type]
            **kwargs,
        )

    monkeypatch.setattr(
        sl_node_module,
        "link_schema",
        recording_link_schema,
    )
    monkeypatch.setattr(
        cr_node_module,
        "decide_complexity",
        recording_decide_complexity,
    )
    context, provider, connector = _context(
        [
            _generation(sql="SELECT missing_title FROM film"),
            _generation(sql="SELECT title FROM film LIMIT 10"),
        ]
    )

    result = run_workflow(_state(), context=context)

    assert result.final_status is FinalStatus.SUCCEEDED_REPAIRED
    assert result.repair_count == 1
    assert len(result.sql_attempts) == 2
    assert len(provider.calls) == 2
    assert len(connector.metadata_calls) == 2
    assert top_ks == [20, 5, 20, 20]
    assert repair_history_flags == [False, True]
    assert result.complexity_decision is not None
    assert (
        ComplexityReason.REPAIR_HISTORY
        in result.complexity_decision.reason_codes
    )
    assert result.complexity_decision.schema_top_k == 20
    assert connector.execute_calls == [
        "SELECT title FROM film LIMIT 10"
    ]
    repair_payload = provider.calls[1][-1].content
    assert '"error_type":"SCHEMA_ERROR"' in repair_payload
    assert '"strategy":"RELINK_SCHEMA"' in repair_payload
    assert "invalid database object" not in repair_payload
    repair_observation = result.generation_observations[1]
    assert repair_observation.provider_prompt_version == "mvp-v1"
    assert (
        repair_observation.effective_prompt_version
        == "mvp-v1+repair-v1"
    )
    assert (
        repair_observation.repair_strategy
        is RepairStrategy.RELINK_SCHEMA
    )
    assert [
        timing.attempt_number
        for timing in result.node_timings
        if timing.node == "generate_sql"
    ] == [0, 1]


def test_syntax_error_repairs_without_relinking() -> None:
    context, _, connector = _context(
        [
            _generation(sql="SELECT ("),
            _generation(sql="SELECT title FROM film LIMIT 10"),
        ]
    )

    result = run_workflow(_state(), context=context)

    assert result.final_status is FinalStatus.SUCCEEDED_REPAIRED
    assert result.repair_count == 1
    assert len(connector.metadata_calls) == 1
    assert len(connector.execute_calls) == 1
    assert result.complexity_decision is not None
    assert result.complexity_decision.schema_top_k == 5
    assert [
        timing.node for timing in result.node_timings
    ].count("complexity_route") == 1
    assert [
        timing.node for timing in result.node_timings
    ].count("schema_linking") == 2
    assert (
        result.generation_observations[1].repair_strategy
        is RepairStrategy.MINIMAL_SQL_REPAIR
    )


def test_dialect_execution_error_regenerates_for_postgres() -> None:
    dialect_error = DatabaseError(
        sqlstate=None,
        error_type=ErrorType.DIALECT_ERROR,
        code="DB_DIALECT_ERROR",
        retryable=False,
        public_message="The SQL dialect is invalid.",
    )
    connector = StubConnector(
        execution_errors=(dialect_error, None)
    )
    context, _, _ = _context(
        [
            _generation(sql="SELECT film_id FROM film LIMIT 1"),
            _generation(sql="SELECT title FROM film LIMIT 1"),
        ],
        connector=connector,
    )

    result = run_workflow(_state(), context=context)

    assert result.final_status is FinalStatus.SUCCEEDED_REPAIRED
    assert result.repair_count == 1
    assert len(connector.metadata_calls) == 1
    assert len(connector.execute_calls) == 2
    assert result.complexity_decision is not None
    assert result.complexity_decision.schema_top_k == 5
    assert [
        timing.node for timing in result.node_timings
    ].count("complexity_route") == 1
    assert [
        timing.node for timing in result.node_timings
    ].count("schema_linking") == 2
    assert (
        result.generation_observations[1].repair_strategy
        is RepairStrategy.REGENERATE_POSTGRES
    )


def test_business_semantic_error_routes_to_clarification() -> None:
    semantic_error = DatabaseError(
        sqlstate=None,
        error_type=ErrorType.AMBIGUOUS_SEMANTICS,
        code="DB_AMBIGUOUS_SEMANTICS",
        retryable=False,
        public_message="More information is required.",
    )
    connector = StubConnector(
        execution_errors=(semantic_error,)
    )
    context, provider, _ = _context(
        [_generation(sql="SELECT film_id FROM film LIMIT 1")],
        connector=connector,
    )

    result = run_workflow(_state(), context=context)

    assert result.final_status is FinalStatus.CLARIFICATION_REQUIRED
    assert result.clarification is not None
    assert len(provider.calls) == 1
    assert len(connector.execute_calls) == 1
    assert result.repair_count == 0


def test_metadata_connection_error_is_terminal_before_model() -> None:
    metadata_error = DatabaseError(
        sqlstate="08006",
        error_type=ErrorType.CONNECTION_ERROR,
        code="DB_CONNECTION_ERROR",
        retryable=False,
        public_message="The database connection failed.",
    )
    connector = StubConnector(
        metadata_error=metadata_error,
        retry_counts=(2,),
    )
    context, provider, _ = _context([], connector=connector)

    result = run_workflow(_state(), context=context)

    assert result.final_status is FinalStatus.FAILED_CONNECTION
    assert provider.calls == []
    assert connector.execute_calls == []
    assert result.infrastructure_retry_count == 2


def test_end_to_end_permission_denial_calls_no_dependencies() -> None:
    context, provider, connector = _context([])
    state = new_task_state(
        request_id="req-denied",
        trace_id="trace-denied",
        question="List film titles",
        datasource_id="pagila",
        requested_schemas=("private",),
    )

    result = run_workflow(state, context=context)

    assert result.final_status is FinalStatus.REJECTED_SECURITY
    assert provider.calls == []
    assert connector.metadata_calls == []
    assert connector.execute_calls == []


def test_duplicate_repair_stops_before_execution() -> None:
    context, provider, connector = _context(
        [
            _generation(sql="SELECT missing_title FROM film"),
            _generation(sql="select missing_title from film;"),
        ]
    )

    result = run_workflow(_state(), context=context)

    assert result.final_status is FinalStatus.FAILED_DUPLICATE_LOOP
    assert result.error_type is ErrorType.DUPLICATE_SQL
    assert result.repair_count == 0
    assert len(provider.calls) == 2
    assert connector.execute_calls == []


def test_third_failed_repair_exhausts_the_budget() -> None:
    context, provider, connector = _context(
        [
            _generation(sql="SELECT missing_0 FROM film"),
            _generation(sql="SELECT missing_1 FROM film"),
            _generation(sql="SELECT missing_2 FROM film"),
            _generation(sql="SELECT missing_3 FROM film"),
        ]
    )

    result = run_workflow(_state(), context=context)

    assert result.final_status is FinalStatus.FAILED_REPAIR_EXHAUSTED
    assert result.repair_count == 3
    assert len(result.sql_attempts) == 4
    assert len(provider.calls) == 4
    assert connector.execute_calls == []
    assert result.step_count <= 32


def test_three_execute_schema_repairs_terminate_at_step_31() -> None:
    schema_error = DatabaseError(
        sqlstate="42703",
        error_type=ErrorType.SCHEMA_ERROR,
        code="DB_SCHEMA_ERROR",
        retryable=False,
        public_message="The SQL references an invalid database object.",
    )
    connector = StubConnector(
        execution_errors=(
            schema_error,
            schema_error,
            schema_error,
            schema_error,
        )
    )
    context, provider, _ = _context(
        [
            _generation(sql="SELECT film_id FROM film LIMIT 1"),
            _generation(sql="SELECT title FROM film LIMIT 1"),
            _generation(
                sql="SELECT film_id, title FROM film LIMIT 1"
            ),
            _generation(
                sql="SELECT title, film_id FROM film LIMIT 1"
            ),
        ],
        connector=connector,
    )

    result = run_workflow(_state(), context=context)

    nodes = [timing.node for timing in result.node_timings]
    assert result.final_status is FinalStatus.FAILED_REPAIR_EXHAUSTED
    assert result.public_error is not None
    assert result.public_error.code == "WORKFLOW_REPAIR_EXHAUSTED"
    assert result.repair_count == 3
    assert len(provider.calls) == 4
    assert len(connector.execute_calls) == 4
    assert len(connector.metadata_calls) == 4
    assert nodes.count("schema_linking") == 8
    assert nodes.count("complexity_route") == 4
    assert result.step_count == 31


def test_deadline_and_step_limit_fail_closed_before_dependencies() -> None:
    timeout_context, timeout_provider, timeout_connector = _context(
        [],
        clock=lambda: 121.0,
    )
    timed_state = SQLTaskState(
        request_id="req-timeout",
        trace_id="trace-timeout",
        question="List film titles",
        datasource_id="pagila",
        workflow_started_at=0.0,
    )

    timed_out = run_workflow(timed_state, context=timeout_context)

    assert timed_out.final_status is FinalStatus.FAILED_TIMEOUT
    assert timeout_provider.calls == []
    assert timeout_connector.metadata_calls == []

    timings = tuple(
        NodeTiming(node=f"previous_{index}", duration_ms=0)
        for index in range(30)
    )
    limited_state = SQLTaskState(
        request_id="req-limit",
        trace_id="trace-limit",
        question="List film titles",
        datasource_id="pagila",
        node_timings=timings,
        step_count=30,
        workflow_started_at=0.0,
    )
    limit_context, limit_provider, limit_connector = _context([])

    limited = run_workflow(limited_state, context=limit_context)

    assert limited.final_status is FinalStatus.FAILED_INTERNAL
    assert limited.step_count == 32
    assert limit_provider.calls == []
    assert limit_connector.metadata_calls == []


def test_workflow_caps_embedding_calls_to_remaining_request_deadline() -> None:
    embedding_provider = RecordingEmbeddingProvider()
    retrieval_runtime = RetrievalRuntime(
        provider=embedding_provider,
        registry=EmbeddingIndexRegistry(),
        semantic_version="semantic-v1",
    )
    context, _, _ = _context(
        [_generation(sql="SELECT title FROM film LIMIT 10")],
        retrieval_runtime=retrieval_runtime,
        clock=lambda: 119.5,
    )
    state = _state().model_copy(
        update={"workflow_started_at": 0.0}
    )

    result = run_workflow(state, context=context)

    assert result.final_status is FinalStatus.SUCCEEDED_FIRST_PASS
    assert embedding_provider.timeouts == [0.5, 0.5]


def test_workflow_caps_database_calls_to_remaining_request_deadline() -> None:
    context, _, connector = _context(
        [_generation(sql="SELECT title FROM film LIMIT 10")],
        clock=lambda: 119.5,
    )
    state = _state().model_copy(
        update={"workflow_started_at": 0.0}
    )

    result = run_workflow(state, context=context)

    assert result.final_status is FinalStatus.SUCCEEDED_FIRST_PASS
    assert connector.metadata_timeouts == [0.5]
    assert connector.execute_timeouts == [0.5]


def test_result_finishing_after_total_deadline_is_not_returned() -> None:
    values = iter(
        (
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            119.0,
            121.0,
            121.0,
            121.0,
        )
    )
    context, _, connector = _context(
        [_generation(sql="SELECT title FROM film LIMIT 10")],
        clock=lambda: next(values),
    )

    result = run_workflow(_state(), context=context)

    assert connector.execute_calls == [
        "SELECT title FROM film LIMIT 10"
    ]
    assert result.final_status is FinalStatus.FAILED_TIMEOUT
    assert result.execution_result is None
