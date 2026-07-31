from __future__ import annotations

from datetime import datetime, timezone

from app.connectors.errors import ErrorType
from app.workflow.models import SQLTaskState, WorkflowContext, WorkflowPublicError
from app.workflow.nodes._common import (
    NodeUpdate,
    _failure_update,
)
from app.workflow.preprocess import preprocess_question


def _request_preprocess(
    state: SQLTaskState,
    context: WorkflowContext,
) -> NodeUpdate:
    now = context.now or datetime.now(timezone.utc)
    try:
        result = preprocess_question(state.question, now=now)
    except ValueError:
        return _failure_update(
            WorkflowPublicError(
                error_type=ErrorType.UNKNOWN,
                code="WORKFLOW_INVALID_REQUEST",
                public_message="The request is invalid.",
            )
        )
    update: NodeUpdate = {
        "normalized_question": result.normalized_question,
        "normalized_time": result.normalized_time,
    }
    if result.requires_clarification:
        update.update(
            {
                "error_type": ErrorType.AMBIGUOUS_SEMANTICS,
                "public_error": None,
            }
        )
    return update
