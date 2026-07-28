import pytest

from app.api import build_query_response
from app.connectors.errors import ErrorType
from app.connectors.models import ExecutionResult, ResultColumn
from app.execution import success_outcome
from app.reflection import (
    record_execution,
    record_validation,
    register_repair_sql,
    start_attempt,
)
from app.validation import (
    ValidationIssue,
    failure_result,
    validate_sql,
)
from app.connectors.metadata import empty_schema_snapshot
from app.workflow import (
    Clarification,
    FinalStatus,
    SQLTaskState,
    WorkflowPublicError,
)


def _success_state() -> SQLTaskState:
    sql = "SELECT 1 AS value"
    validation = validate_sql(
        sql,
        allowed_schemas=(),
        allowed_tables=(),
        snapshot=empty_schema_snapshot(),
    )
    result = ExecutionResult(
        columns=(ResultColumn(name="value", type_oid=23),),
        rows=[[1]],
        returned_row_count=1,
        truncated=False,
        execution_time_ms=0.1,
    )
    history = record_execution(
        record_validation(start_attempt(sql), validation),
        success_outcome(result),
    )
    return SQLTaskState(
        request_id="req-success",
        trace_id="trace-success",
        question="one",
        datasource_id="pagila",
        current_sql=history.current_attempt.sql,
        sql_attempts=history.attempts,
        seen_sql_fingerprints=history.seen_sql_fingerprints,
        validation_result=history.current_attempt.validation_result,
        execution_result=history.current_attempt.execution_result,
        repair_count=history.repair_count,
        final_status=FinalStatus.SUCCEEDED_FIRST_PASS,
    )


def test_success_state_maps_only_public_result_fields() -> None:
    response = build_query_response(_success_state())

    assert response.status is FinalStatus.SUCCEEDED_FIRST_PASS
    assert response.sql == "SELECT 1 AS value"
    assert response.columns[0].name == "value"
    assert response.rows == [[1]]
    assert response.returned_row_count == 1
    assert response.attempts == 1
    assert response.error is None


def test_clarification_state_maps_without_sql_or_results() -> None:
    state = SQLTaskState(
        request_id="req-clarify",
        trace_id="trace-clarify",
        question="ambiguous",
        datasource_id="pagila",
        error_type=ErrorType.AMBIGUOUS_SEMANTICS,
        clarification=Clarification(
            code="AMBIGUOUS_SEMANTICS",
            question="Please clarify the reporting scope.",
        ),
        final_status=FinalStatus.CLARIFICATION_REQUIRED,
    )

    response = build_query_response(state)

    assert response.status is FinalStatus.CLARIFICATION_REQUIRED
    assert response.sql is None
    assert response.rows == []
    assert response.clarification is not None
    assert response.error is None


def test_security_failure_never_returns_failed_sql() -> None:
    sql = "DELETE FROM film"
    history = record_validation(
        start_attempt(sql),
        validate_sql(
            sql,
            allowed_schemas=("public",),
            allowed_tables=("public.film",),
            snapshot=empty_schema_snapshot(),
        ),
    )
    public_error = WorkflowPublicError(
        error_type=ErrorType.PERMISSION_DENIED,
        code="SQL_NOT_READ_ONLY",
        public_message="The SQL statement is not permitted.",
    )
    state = SQLTaskState(
        request_id="req-denied",
        trace_id="trace-denied",
        question="delete films",
        datasource_id="pagila",
        current_sql=history.current_attempt.sql,
        sql_attempts=history.attempts,
        seen_sql_fingerprints=history.seen_sql_fingerprints,
        validation_result=history.current_attempt.validation_result,
        repair_count=history.repair_count,
        error_type=ErrorType.PERMISSION_DENIED,
        public_error=public_error,
        final_status=FinalStatus.REJECTED_SECURITY,
    )

    response = build_query_response(state)

    assert response.status is FinalStatus.REJECTED_SECURITY
    assert response.sql is None
    assert response.columns == ()
    assert response.rows == []
    assert response.error is not None
    assert response.error.error_type is ErrorType.PERMISSION_DENIED
    assert "DELETE" not in response.error.message


def test_repaired_success_state_maps_repair_accounting() -> None:
    failed = record_validation(
        start_attempt("SELECT missing FROM film"),
        failure_result(
            ValidationIssue(
                error_type=ErrorType.SCHEMA_ERROR,
                code="SQL_SCHEMA_ERROR",
                public_message="The SQL references an unknown field.",
            )
        ),
    )
    registration = register_repair_sql(failed, "SELECT 1 AS value")
    validation = validate_sql(
        "SELECT 1 AS value",
        allowed_schemas=(),
        allowed_tables=(),
        snapshot=empty_schema_snapshot(),
    )
    result = ExecutionResult(
        columns=(ResultColumn(name="value", type_oid=23),),
        rows=[[1]],
        returned_row_count=1,
        truncated=False,
        execution_time_ms=0.1,
    )
    history = record_execution(
        record_validation(registration.history, validation),
        success_outcome(result),
    )
    state = SQLTaskState(
        request_id="req-repaired",
        trace_id="trace-repaired",
        question="one",
        datasource_id="pagila",
        current_sql=history.current_attempt.sql,
        sql_attempts=history.attempts,
        seen_sql_fingerprints=history.seen_sql_fingerprints,
        validation_result=history.current_attempt.validation_result,
        execution_result=history.current_attempt.execution_result,
        repair_count=history.repair_count,
        final_status=FinalStatus.SUCCEEDED_REPAIRED,
    )

    response = build_query_response(state)

    assert response.status is FinalStatus.SUCCEEDED_REPAIRED
    assert response.attempts == 2
    assert response.repair_count == 1


@pytest.mark.parametrize(
    ("status", "error_type"),
    [
        (
            FinalStatus.REJECTED_SECURITY,
            ErrorType.PERMISSION_DENIED,
        ),
        (
            FinalStatus.FAILED_DUPLICATE_LOOP,
            ErrorType.DUPLICATE_SQL,
        ),
        (FinalStatus.FAILED_TIMEOUT, ErrorType.TIMEOUT),
        (
            FinalStatus.FAILED_CONNECTION,
            ErrorType.CONNECTION_ERROR,
        ),
        (
            FinalStatus.FAILED_RESOURCE_RISK,
            ErrorType.RESOURCE_RISK,
        ),
        (FinalStatus.FAILED_INTERNAL, ErrorType.UNKNOWN),
    ],
)
def test_failure_states_map_to_matching_public_errors(
    status: FinalStatus,
    error_type: ErrorType,
) -> None:
    state = SQLTaskState(
        request_id=f"req-{status.value}",
        trace_id=f"trace-{status.value}",
        question="one",
        datasource_id="pagila",
        error_type=error_type,
        public_error=WorkflowPublicError(
            error_type=error_type,
            code="SAFE_ERROR",
            public_message="The request failed.",
        ),
        final_status=status,
    )

    response = build_query_response(state)

    assert response.status is status
    assert response.error is not None
    assert response.error.error_type is error_type
    assert response.sql is None
    assert response.rows == []


def test_repair_exhausted_state_maps_without_failed_sql() -> None:
    issue = ValidationIssue(
        error_type=ErrorType.SCHEMA_ERROR,
        code="SQL_SCHEMA_ERROR",
        public_message="The SQL references an unknown field.",
    )
    history = record_validation(
        start_attempt("SELECT missing_0 FROM film"),
        failure_result(issue),
    )
    for number in range(1, 4):
        registration = register_repair_sql(
            history,
            f"SELECT missing_{number} FROM film",
        )
        history = record_validation(
            registration.history,
            failure_result(issue),
        )
    state = SQLTaskState(
        request_id="req-exhausted",
        trace_id="trace-exhausted",
        question="one",
        datasource_id="pagila",
        current_sql=history.current_attempt.sql,
        sql_attempts=history.attempts,
        seen_sql_fingerprints=history.seen_sql_fingerprints,
        validation_result=history.current_attempt.validation_result,
        repair_count=history.repair_count,
        error_type=ErrorType.SCHEMA_ERROR,
        public_error=WorkflowPublicError(
            error_type=ErrorType.SCHEMA_ERROR,
            code="WORKFLOW_REPAIR_EXHAUSTED",
            public_message="The request could not be repaired.",
        ),
        final_status=FinalStatus.FAILED_REPAIR_EXHAUSTED,
    )

    response = build_query_response(state)

    assert response.status is FinalStatus.FAILED_REPAIR_EXHAUSTED
    assert response.attempts == 4
    assert response.repair_count == 3
    assert response.sql is None
