from langgraph.graph import END, START, StateGraph

from app.connectors.errors import ErrorType
from app.reflection import RepairStrategy
from app.workflow.models import (
    NodeTiming,
    SQLTaskState,
    WorkflowContext,
)
from app.workflow.nodes import (
    CLARIFICATION_NODE,
    EXECUTE_SQL_NODE,
    FINALIZE_NODE,
    GENERATE_SQL_NODE,
    PERMISSION_RESOLVE_NODE,
    REFLECT_SQL_NODE,
    REQUEST_PREPROCESS_NODE,
    SCHEMA_LINKING_NODE,
    VALIDATE_SQL_NODE,
)

WORKFLOW_NODE_NAMES = (
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

_REPAIRABLE_ERRORS = frozenset(
    {
        ErrorType.SYNTAX_ERROR,
        ErrorType.SCHEMA_ERROR,
        ErrorType.DIALECT_ERROR,
    }
)
_REFLECT_ERRORS = _REPAIRABLE_ERRORS | {
    ErrorType.BUSINESS_KNOWLEDGE_MISSING,
    ErrorType.AMBIGUOUS_SEMANTICS,
}


def _preprocess_route(state: SQLTaskState) -> str:
    if state.public_error is not None:
        return "finalize"
    if state.error_type is ErrorType.AMBIGUOUS_SEMANTICS:
        return "clarification"
    return "permission_resolve"


def _permission_route(state: SQLTaskState) -> str:
    return (
        "finalize"
        if state.public_error is not None
        else "schema_linking"
    )


def _schema_route(state: SQLTaskState) -> str:
    if state.public_error is not None:
        return (
            "clarification"
            if state.error_type
            is ErrorType.BUSINESS_KNOWLEDGE_MISSING
            else "finalize"
        )
    return "generate_sql"


def _generation_route(state: SQLTaskState) -> str:
    if state.public_error is not None:
        return "finalize"
    if state.error_type in {
        ErrorType.AMBIGUOUS_SEMANTICS,
        ErrorType.BUSINESS_KNOWLEDGE_MISSING,
    }:
        return "clarification"
    return "validate_sql"


def _validation_route(state: SQLTaskState) -> str:
    if state.validation_result is not None:
        if state.validation_result.is_valid:
            return "execute_sql"
    if state.error_type in _REFLECT_ERRORS:
        return "reflect_sql"
    return "finalize"


def _execution_route(state: SQLTaskState) -> str:
    if state.execution_result is not None:
        return "finalize"
    if state.error_type in _REFLECT_ERRORS:
        return "reflect_sql"
    return "finalize"


def _reflection_route(state: SQLTaskState) -> str:
    if state.repair_strategy is RepairStrategy.RELINK_SCHEMA:
        return "schema_linking"
    if state.repair_strategy in {
        RepairStrategy.MINIMAL_SQL_REPAIR,
        RepairStrategy.REGENERATE_POSTGRES,
    }:
        return "generate_sql"
    if state.error_type in {
        ErrorType.AMBIGUOUS_SEMANTICS,
        ErrorType.BUSINESS_KNOWLEDGE_MISSING,
    }:
        return "clarification"
    return "finalize"


def build_workflow():
    builder = StateGraph(
        SQLTaskState,
        context_schema=WorkflowContext,
    )
    builder.add_node(
        "request_preprocess",
        REQUEST_PREPROCESS_NODE,
    )
    builder.add_node(
        "permission_resolve",
        PERMISSION_RESOLVE_NODE,
    )
    builder.add_node("schema_linking", SCHEMA_LINKING_NODE)
    builder.add_node("generate_sql", GENERATE_SQL_NODE)
    builder.add_node("validate_sql", VALIDATE_SQL_NODE)
    builder.add_node("execute_sql", EXECUTE_SQL_NODE)
    builder.add_node("reflect_sql", REFLECT_SQL_NODE)
    builder.add_node("clarification", CLARIFICATION_NODE)
    builder.add_node("finalize", FINALIZE_NODE)

    builder.add_edge(START, "request_preprocess")
    builder.add_conditional_edges(
        "request_preprocess",
        _preprocess_route,
        [
            "permission_resolve",
            "clarification",
            "finalize",
        ],
    )
    builder.add_conditional_edges(
        "permission_resolve",
        _permission_route,
        ["schema_linking", "finalize"],
    )
    builder.add_conditional_edges(
        "schema_linking",
        _schema_route,
        ["generate_sql", "clarification", "finalize"],
    )
    builder.add_conditional_edges(
        "generate_sql",
        _generation_route,
        ["validate_sql", "clarification", "finalize"],
    )
    builder.add_conditional_edges(
        "validate_sql",
        _validation_route,
        ["execute_sql", "reflect_sql", "finalize"],
    )
    builder.add_conditional_edges(
        "execute_sql",
        _execution_route,
        ["reflect_sql", "finalize"],
    )
    builder.add_conditional_edges(
        "reflect_sql",
        _reflection_route,
        [
            "schema_linking",
            "generate_sql",
            "clarification",
            "finalize",
        ],
    )
    builder.add_edge("clarification", "finalize")
    builder.add_edge("finalize", END)
    return builder.compile()


def run_workflow(
    state: SQLTaskState,
    *,
    context: WorkflowContext,
) -> SQLTaskState:
    output = build_workflow().invoke(
        state,
        context=context,
        config={"recursion_limit": 34},
    )
    result = SQLTaskState.model_validate(output)
    routes = (
        *(
            timing.node
            for timing in result.node_timings[1:]
        ),
        "__end__",
    )
    routed_timings = tuple(
        NodeTiming(
            node=timing.node,
            duration_ms=timing.duration_ms,
            attempt_number=timing.attempt_number,
            route=route,
        )
        for timing, route in zip(
            result.node_timings,
            routes,
            strict=True,
        )
    )
    return SQLTaskState.model_validate(
        {
            **output,
            "node_timings": routed_timings,
        }
    )
