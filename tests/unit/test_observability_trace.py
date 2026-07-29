from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from app.api import ApplicationServices, create_app
from app.connectors.metadata import empty_schema_snapshot
from app.connectors.models import ExecutionResult, ResultColumn
from app.execution import success_outcome
from app.observability import (
    TracedWorkflowRunner,
    build_trace_record,
)
from app.reflection import (
    record_execution,
    record_validation,
    start_attempt,
)
from app.validation import validate_sql
from app.workflow import (
    FinalStatus,
    GenerationObservation,
    NodeTiming,
    SQLTaskState,
    TokenUsage,
    WorkflowContext,
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
    return SQLTaskState(
        request_id=source.request_id,
        trace_id=source.trace_id,
        question=source.question,
        datasource_id=source.datasource_id,
        normalized_question="private normalized question",
        allowed_schemas=("public",),
        allowed_tables=("public.film",),
        schema_version="schema-v1",
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
    return WorkflowContext(
        provider=Mock(),
        connector=Mock(),
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


def test_trace_serialization_excludes_sensitive_state_values() -> None:
    rendered = build_trace_record(_terminal_state()).model_dump_json()

    for forbidden in (
        "private-question",
        "private normalized question",
        "private-row-value",
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
