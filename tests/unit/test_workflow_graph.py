from collections.abc import Sequence
from dataclasses import dataclass

from app.connectors.errors import (
    DatabaseError,
    ErrorType,
    PostgreSQLConnectorError,
)
from app.connectors.metadata import (
    ColumnMetadata,
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
from app.workflow import (
    FinalStatus,
    NodeTiming,
    SQLTaskState,
    WORKFLOW_NODE_NAMES,
    WorkflowContext,
    build_workflow,
    new_task_state,
    run_workflow,
)


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
    ) -> GenerationResult:
        self.calls.append(tuple(messages))
        return self.outputs.pop(0)


@dataclass
class StubConnector:
    result: ExecutionResult = RESULT
    error: DatabaseError | None = None
    metadata_error: DatabaseError | None = None
    execution_errors: tuple[DatabaseError | None, ...] = ()
    retry_counts: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        self.metadata_calls: list[
            tuple[tuple[str, ...], tuple[str, ...]]
        ] = []
        self.execute_calls: list[str] = []
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
    ):
        self._record_retries()
        self.metadata_calls.append((allowed_schemas, allowed_tables))
        if self.metadata_error is not None:
            raise PostgreSQLConnectorError(self.metadata_error)
        return SNAPSHOT

    def execute(self, sql: str) -> ExecutionResult:
        self._record_retries()
        self.execute_calls.append(sql)
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
    clock=lambda: 0.0,
) -> tuple[WorkflowContext, ScriptedProvider, StubConnector]:
    provider = ScriptedProvider(outputs)
    selected_connector = connector or StubConnector()
    return (
        WorkflowContext(
            provider=provider,
            connector=selected_connector,
            datasource_id="pagila",
            allowed_schemas=("public",),
            allowed_tables=("public.film",),
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


def test_graph_registers_exactly_the_nine_mvp_nodes() -> None:
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
        ("schema_linking", "generate_sql"),
        ("schema_linking", "clarification"),
        ("schema_linking", "finalize"),
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
        "generate_sql",
        "validate_sql",
        "execute_sql",
        "finalize",
    )
    assert tuple(item.route for item in result.node_timings) == (
        "permission_resolve",
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
    ) == (None, None, None, 0, 0, 0, 0)
    assert result.step_count == 7
    assert len(provider.calls) == 1
    assert len(connector.metadata_calls) == 1
    assert connector.execute_calls == [
        "SELECT title FROM film LIMIT 10"
    ]


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


def test_schema_error_relinks_and_accepts_one_distinct_repair() -> None:
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
