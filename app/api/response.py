from app.api.models import (
    PublicError,
    QueryResponse,
    ResponseClarification,
    ResponseColumn,
)
from app.connectors.models import ExecutionResult
from app.workflow import (
    FinalStatus,
    SQLTaskState,
)


def build_query_response(state: SQLTaskState) -> QueryResponse:
    if state.final_status is None:
        raise ValueError("workflow state is not terminal")
    base: dict[str, object] = {
        "request_id": state.request_id,
        "trace_id": state.trace_id,
        "status": state.final_status,
        "attempts": len(state.sql_attempts),
        "repair_count": state.repair_count,
    }
    if state.final_status in {
        FinalStatus.SUCCEEDED_FIRST_PASS,
        FinalStatus.SUCCEEDED_REPAIRED,
    }:
        result = state.execution_result
        if not isinstance(result, ExecutionResult):
            raise ValueError("workflow success result is invalid")
        base.update(
            {
                "sql": state.current_sql,
                "columns": tuple(
                    ResponseColumn(
                        name=column.name,
                        type_oid=column.type_oid,
                    )
                    for column in result.columns
                ),
                "rows": [list(row) for row in result.rows],
                "returned_row_count": result.returned_row_count,
                "truncated": result.truncated,
            }
        )
    elif (
        state.final_status
        == FinalStatus.CLARIFICATION_REQUIRED
    ):
        if state.clarification is None:
            raise ValueError("workflow clarification is invalid")
        base["clarification"] = ResponseClarification(
            code=state.clarification.code,
            question=state.clarification.question,
        )
    else:
        if state.public_error is None:
            raise ValueError("workflow public error is invalid")
        base["error"] = PublicError(
            error_type=state.public_error.error_type,
            code=state.public_error.code,
            message=state.public_error.public_message,
        )
    return QueryResponse.model_validate(base)
