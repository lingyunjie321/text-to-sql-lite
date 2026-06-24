from text_to_sql_demo.nodes.error_reflection import ReflectErrorNode
from text_to_sql_demo.workflow.state import WorkflowState


def _state_for_error(
    *,
    category: str,
    attempt_count: int = 0,
    max_repair_attempts: int = 3,
) -> WorkflowState:
    return WorkflowState(
        user_question="统计订单金额",
        data={
            "current_sql": "SELECT SUM(orders.total_amount) AS total FROM orders",
            "generated_sql": "SELECT SUM(orders.total_amount) AS total FROM orders",
            "attempt_count": attempt_count,
            "max_repair_attempts": max_repair_attempts,
            "last_error": {
                "category": category,
                "message": f"{category} 示例错误",
                "raw_message": f"{category} raw",
                "table": "orders",
                "column": "total_amount",
            },
            "validation_result": {
                "success": False,
                "error": {
                    "category": category,
                    "message": f"{category} 示例错误",
                },
            },
            "schema_linking": {
                "tables": [
                    {
                        "name": "orders",
                        "columns": {"amount": {"name": "amount", "type": "NUMERIC"}},
                    }
                ]
            },
        },
    )


def test_unknown_column_routes_to_fix_sql_and_records_sql_context() -> None:
    node = ReflectErrorNode(name="error_classification", config={"max_repair_attempts": 3})
    state = _state_for_error(category="unknown_column")

    result = node.run(state)
    patch = result.state_patch["data"]

    assert result.outcome == "fix_sql"
    assert patch["reflection_decision"]["strategy"] == "FIX_SQL"
    assert patch["last_reflection_strategy"] == "FIX_SQL"
    assert patch["repair_instruction"]["error_category"] == "unknown_column"
    assert patch["repair_instruction"]["reason"] == patch["reflection_decision"]["reason"]
    assert patch["sql_contexts"][0]["attempt"] == 1
    assert patch["sql_contexts"][0]["reflection_strategy"] == "FIX_SQL"
    assert patch["sql_contexts"][0]["reflection_reason"] == patch["reflection_decision"]["reason"]
    assert patch["sql_contexts"][0]["validation_error"]["category"] == "unknown_column"


def test_unknown_table_routes_to_schema_relink_and_counts_regeneration_attempt() -> None:
    node = ReflectErrorNode(name="error_classification", config={"max_repair_attempts": 3})
    state = _state_for_error(category="unknown_table")

    result = node.run(state)
    patch = result.state_patch["data"]

    assert result.outcome == "relink_schema"
    assert patch["reflection_decision"]["strategy"] == "RELINK_SCHEMA"
    assert patch["attempt_count"] == 1
    assert patch["sql_contexts"][0]["reflection_strategy"] == "RELINK_SCHEMA"


def test_execution_error_routes_to_reasoning_rewrite() -> None:
    node = ReflectErrorNode(name="error_classification", config={"max_repair_attempts": 3})
    state = _state_for_error(category="execution_error")
    state.data.pop("validation_result")
    state.data["execution_result"] = {
        "success": False,
        "error": {
            "category": "execution_error",
            "message": "database execution failed",
        },
    }

    result = node.run(state)
    patch = result.state_patch["data"]

    assert result.outcome == "reasoning_rewrite"
    assert patch["reflection_decision"]["strategy"] == "REASONING_REWRITE"
    assert patch["sql_contexts"][0]["execution_error"]["category"] == "execution_error"


def test_attempts_exhausted_routes_to_hitl_without_infinite_retry() -> None:
    node = ReflectErrorNode(name="error_classification", config={"max_repair_attempts": 3})
    state = _state_for_error(category="unknown_column", attempt_count=3)

    result = node.run(state)
    patch = result.state_patch["data"]

    assert result.outcome == "attempts_exhausted"
    assert patch["reflection_decision"]["strategy"] == "HITL"
    assert patch["termination_reason"] == "attempts_exhausted"
    assert patch["sql_contexts"][0]["attempt"] == 3
