from text_to_sql_demo.config.models import NodeConfig
from text_to_sql_demo.llm.client import MockLLMClient
from text_to_sql_demo.llm.models import ModelProfile
from text_to_sql_demo.workflow.dependencies import NodeDependencies
from text_to_sql_demo.workflow.factory import NodeFactory
from text_to_sql_demo.workflow.state import WorkflowState


def test_reasoning_rewrite_node_regenerates_sql_with_reflection_memory() -> None:
    import text_to_sql_demo.nodes  # noqa: F401

    llm_client = MockLLMClient(responses={"strong": "SELECT SUM(amount) FROM orders"})
    dependencies = NodeDependencies(
        values={
            "llm_client": llm_client,
            "model_profiles": {
                "strong": ModelProfile(alias="strong", provider="mock", model_name="strong-model")
            },
        }
    )
    node = NodeFactory(dependencies=dependencies).create(
        name="reasoning_rewrite",
        config=NodeConfig(type="reasoning_rewrite", model_alias="strong"),
    )
    state = WorkflowState(
        user_question="统计订单金额",
        data={
            "attempt_count": 1,
            "schema_linking": {
                "tables": [
                    {
                        "name": "orders",
                        "columns": {"amount": {"name": "amount", "type": "NUMERIC"}},
                    }
                ]
            },
            "rag_context": {"documents": [{"item": {"title": "订单口径", "content": "金额字段"}}]},
            "sql_contexts": [
                {
                    "attempt": 1,
                    "sql": "SELECT total_amount FROM orders",
                    "execution_error": {
                        "category": "execution_error",
                        "message": "no such column: total_amount",
                    },
                    "reflection_strategy": "REASONING_REWRITE",
                    "reflection_reason": "执行失败，需要重新推理",
                }
            ],
            "last_error": {
                "category": "execution_error",
                "message": "no such column: total_amount",
            },
            "reflection_decision": {
                "strategy": "REASONING_REWRITE",
                "reason": "执行失败，需要重新推理",
                "confidence": 0.7,
                "error_category": "execution_error",
                "attempt_count": 1,
                "max_attempts": 3,
            },
        },
    )

    result = node.run(state)
    state.apply_patch(result.state_patch)

    assert result.outcome == "rewrite_complete"
    assert state.data["generated_sql"] == "SELECT SUM(amount) FROM orders"
    assert state.data["current_sql"] == "SELECT SUM(amount) FROM orders"
    assert state.data["attempt_count"] == 2
    assert "最近反思记忆" in llm_client.requests[0].user_prompt
    assert "sha256:" in llm_client.requests[0].user_prompt
    assert "SELECT total_amount FROM orders" not in llm_client.requests[0].user_prompt
    assert "执行失败，需要重新推理" in llm_client.requests[0].user_prompt


def test_hitl_node_marks_state_for_human_review() -> None:
    import text_to_sql_demo.nodes  # noqa: F401

    node = NodeFactory().create(name="hitl", config=NodeConfig(type="hitl"))
    state = WorkflowState(
        user_question="统计订单金额",
        data={
            "reflection_decision": {
                "strategy": "HITL",
                "reason": "连续修复失败，需要人工确认 Schema",
                "confidence": 0.4,
                "error_category": "unknown_column",
                "attempt_count": 3,
                "max_attempts": 3,
            },
            "last_error": {
                "category": "unknown_column",
                "message": "字段不存在",
            },
        },
    )

    result = node.run(state)
    patch = result.state_patch["data"]

    assert result.outcome == "hitl_required"
    assert patch["final_status"] == "needs_human_review"
    assert patch["hitl_reason"] == "连续修复失败，需要人工确认 Schema"
    assert patch["final_error"]["category"] == "unknown_column"
