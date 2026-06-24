from text_to_sql_demo.api.service import serialize_run
from text_to_sql_demo.workflow.state import WorkflowState


def test_serialize_run_returns_reflection_summary_without_full_sql() -> None:
    state = WorkflowState(
        request_id="req_reflection",
        user_question="统计订单金额",
        data={
            "final_status": "needs_human_review",
            "current_sql": "SELECT total_amount FROM orders",
            "attempt_count": 3,
            "hitl_reason": "连续修复失败，需要人工确认 Schema",
            "reflection_decision": {
                "strategy": "HITL",
                "reason": "连续修复失败，需要人工确认 Schema",
                "confidence": 0.4,
                "error_category": "unknown_column",
                "attempt_count": 3,
                "max_attempts": 3,
            },
            "sql_contexts": [
                {
                    "attempt": 3,
                    "sql": "SELECT total_amount FROM orders",
                    "validation_error": {
                        "category": "unknown_column",
                        "message": "no such column: total_amount",
                    },
                    "reflection_strategy": "HITL",
                    "reflection_reason": "连续修复失败，需要人工确认 Schema",
                }
            ],
            "last_error": {
                "category": "unknown_column",
                "message": "no such column: total_amount",
            },
        },
    )

    payload = serialize_run(state)

    assert payload["reflection_decision"]["strategy"] == "HITL"
    assert payload["hitl_required"] is True
    assert payload["hitl_reason"] == "连续修复失败，需要人工确认 Schema"
    assert payload["sql_contexts"][0]["sql_length"] == len("SELECT total_amount FROM orders")
    assert payload["sql_contexts"][0]["sql_hash"].startswith("sha256:")
    assert "sql" not in payload["sql_contexts"][0]
