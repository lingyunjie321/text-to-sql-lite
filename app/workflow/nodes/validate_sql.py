from __future__ import annotations

from app.validation import validate_sql
from app.reflection import record_validation
from app.workflow.models import (
    SQLTaskState,
    WorkflowContext,
    WorkflowPublicError,
)
from app.workflow.nodes._common import (
    NodeUpdate,
    _attempt_history,
    _failure_update,
    _history_update,
)


def _validate_sql(
    state: SQLTaskState,
    context: WorkflowContext,
) -> NodeUpdate:
    del context
    assert state.current_sql is not None
    assert state.schema_snapshot is not None
    result = validate_sql(
        state.current_sql,
        allowed_schemas=state.allowed_schemas,
        allowed_tables=state.allowed_tables,
        snapshot=state.schema_snapshot,
    )
    history = record_validation(_attempt_history(state), result)
    update = _history_update(history)
    if result.is_valid:
        update.update(
            {
                "error_type": None,
                "public_error": None,
            }
        )
        return update
    assert result.issue is not None
    update.update(
        _failure_update(
            WorkflowPublicError(
                error_type=result.issue.error_type,
                code=result.issue.code,
                public_message=result.issue.public_message,
            )
        )
    )
    return update
