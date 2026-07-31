"""SQL 执行节点：在只读事务中执行已校验 SQL，30 秒超时，最多 1000 行。"""

from __future__ import annotations

from app.execution import execute_validated_sql
from app.reflection import record_execution
from app.workflow.models import (
    REQUEST_TIMEOUT_SECONDS,
    SQLTaskState,
    WorkflowContext,
    WorkflowPublicError,
)
from app.workflow.nodes._common import (
    NodeUpdate,
    _attempt_history,
    _consume_infrastructure_retries,
    _failure_update,
    _history_update,
)


def _execute_sql(
    state: SQLTaskState,
    context: WorkflowContext,
    *,
    database_timeout_seconds: float,
) -> NodeUpdate:
    assert state.validation_result is not None
    assert state.schema_snapshot is not None
    outcome = execute_validated_sql(
        state.validation_result,
        allowed_schemas=state.allowed_schemas,
        allowed_tables=state.allowed_tables,
        snapshot=state.schema_snapshot,
        connector=context.connector,
        timeout_seconds=database_timeout_seconds,
        dialect=state.dialect,
    )
    retry_count = _consume_infrastructure_retries(context)
    history = record_execution(_attempt_history(state), outcome)
    update = _history_update(history)
    update["infrastructure_retry_count"] = (
        state.infrastructure_retry_count + retry_count
    )
    if outcome.is_success:
        update.update(
            {
                "error_type": None,
                "public_error": None,
            }
        )
        return update
    assert outcome.error is not None
    update.update(
        _failure_update(
            WorkflowPublicError(
                error_type=outcome.error.error_type,
                code=outcome.error.code,
                public_message=outcome.error.public_message,
            )
        )
    )
    return update
