from __future__ import annotations

from app.workflow.models import (
    SQLTaskState,
    WorkflowContext,
    WorkflowPermissionError,
)
from app.workflow.nodes._common import (
    NodeUpdate,
    _failure_update,
)
from app.workflow.permissions import resolve_permissions


def _permission_resolve(
    state: SQLTaskState,
    context: WorkflowContext,
) -> NodeUpdate:
    try:
        scope = resolve_permissions(
            datasource_id=state.datasource_id,
            requested_schemas=state.requested_schemas,
            context=context,
        )
    except WorkflowPermissionError as error:
        return _failure_update(error.details)
    return {
        "allowed_schemas": scope.allowed_schemas,
        "allowed_tables": scope.allowed_tables,
        "error_type": None,
        "public_error": None,
    }
