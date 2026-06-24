from text_to_sql_demo.nodes.error_reflection import ReflectErrorNode
from text_to_sql_demo.workflow.state import WorkflowState


def test_reflect_error_node_adds_targeted_strategy_for_unknown_column() -> None:
    state = WorkflowState(
        user_question="统计订单金额",
        data={
            "current_sql": "SELECT SUM(orders.total_amount) FROM orders",
            "last_error": {
                "category": "unknown_column",
                "message": "字段不存在: orders.total_amount",
                "table": "orders",
                "column": "total_amount",
            },
            "schema_linking": {
                "tables": [
                    {
                        "name": "orders",
                        "columns": {
                            "amount": {"name": "amount", "type": "NUMERIC"},
                        },
                    }
                ]
            },
        },
    )
    node = ReflectErrorNode(name="reflect", config={"max_repair_attempts": 3})

    result = node.run(state)
    instruction = result.state_patch["data"]["repair_instruction"]

    assert result.outcome == "fix_sql"
    assert result.state_patch["data"]["reflection_decision"]["strategy"] == "FIX_SQL"
    assert instruction["strategy"]["name"] == "repair_unknown_column"
    assert instruction["strategy"]["focus"] == "修复不存在字段引用"
    assert "只替换不存在字段 total_amount" in instruction["strategy"]["instructions"]
    assert "不要虚构字段" in instruction["strategy"]["avoid"]
    assert "unknown_column" in instruction["reason"]
