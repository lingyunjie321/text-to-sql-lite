"""LangGraph workflow node implementations (split by node)."""

from app.schema_linking import link_schema  # noqa: F401 - exposed for test monkeypatching
from app.workflow.complexity import decide_complexity  # noqa: F401 - exposed for test monkeypatching

from app.workflow.nodes.clarification import _clarification
from app.workflow.nodes.complexity_route import _complexity_route
from app.workflow.nodes.execute_sql import _execute_sql
from app.workflow.nodes.finalize import _finalize
from app.workflow.nodes.generate_sql import _generate_sql
from app.workflow.nodes.permission_resolve import _permission_resolve
from app.workflow.nodes.reflect_sql import _reflect_sql
from app.workflow.nodes.request_preprocess import _request_preprocess
from app.workflow.nodes.schema_linking import _schema_linking
from app.workflow.nodes.validate_sql import _validate_sql
from app.workflow.nodes.wrapper import workflow_node

REQUEST_PREPROCESS_NODE = workflow_node(
    "request_preprocess",
    _request_preprocess,
)
PERMISSION_RESOLVE_NODE = workflow_node(
    "permission_resolve",
    _permission_resolve,
)
SCHEMA_LINKING_NODE = workflow_node(
    "schema_linking",
    _schema_linking,
)
COMPLEXITY_ROUTE_NODE = workflow_node(
    "complexity_route",
    _complexity_route,
)
GENERATE_SQL_NODE = workflow_node("generate_sql", _generate_sql)
VALIDATE_SQL_NODE = workflow_node("validate_sql", _validate_sql)
EXECUTE_SQL_NODE = workflow_node("execute_sql", _execute_sql)
REFLECT_SQL_NODE = workflow_node("reflect_sql", _reflect_sql)
CLARIFICATION_NODE = workflow_node(
    "clarification",
    _clarification,
)
FINALIZE_NODE = workflow_node("finalize", _finalize)
