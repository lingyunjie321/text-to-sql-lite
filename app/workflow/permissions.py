from app.connectors.errors import ErrorType
from app.workflow.models import (
    PermissionScope,
    WorkflowContext,
    WorkflowPermissionError,
    WorkflowPublicError,
)

_PERMISSION_ERROR = WorkflowPublicError(
    error_type=ErrorType.PERMISSION_DENIED,
    code="WORKFLOW_PERMISSION_DENIED",
    public_message="The request is not permitted.",
)


def resolve_permissions(
    *,
    datasource_id: str,
    requested_schemas: tuple[str, ...],
    context: WorkflowContext,
) -> PermissionScope:
    requested = tuple(sorted(set(requested_schemas)))
    allowed = set(context.allowed_schemas)
    if (
        datasource_id != context.datasource_id
        or any(not schema.strip() for schema in requested)
        or not set(requested).issubset(allowed)
    ):
        raise WorkflowPermissionError(_PERMISSION_ERROR)
    selected_schemas = requested or context.allowed_schemas
    selected_set = set(selected_schemas)
    selected_tables = tuple(
        table
        for table in context.allowed_tables
        if table.split(".", 1)[0] in selected_set
    )
    if not selected_schemas or not selected_tables:
        raise WorkflowPermissionError(_PERMISSION_ERROR)
    return PermissionScope(
        allowed_schemas=selected_schemas,
        allowed_tables=selected_tables,
    )
