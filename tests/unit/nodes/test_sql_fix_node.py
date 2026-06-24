from text_to_sql_demo.llm.client import MockLLMClient
from text_to_sql_demo.llm.models import ModelProfile
from text_to_sql_demo.nodes.sql_fix import FixSQLNode
from text_to_sql_demo.workflow.dependencies import NodeDependencies
from text_to_sql_demo.workflow.state import WorkflowState


def test_fix_sql_node_strips_markdown_fence_from_fixed_sql() -> None:
    fixed_sql = "SELECT amount FROM orders"
    state = WorkflowState(
        user_question="列出订单金额",
        data={
            "attempt_count": 0,
            "repair_instruction": {
                "original_question": "列出订单金额",
                "current_sql": "SELECT total_amount FROM orders",
                "error_category": "unknown_column",
                "original_error": "字段不存在: orders.total_amount",
                "related_schema": {},
                "repair_history": [],
                "reason": "根据错误类型 unknown_column 修复 SQL",
            },
        },
    )
    llm_client = MockLLMClient(responses={"strong": f"```sql\n{fixed_sql}\n```"})
    dependencies = NodeDependencies(
        values={
            "llm_client": llm_client,
            "model_profiles": {
                "strong": ModelProfile(alias="strong", provider="mock", model_name="strong-model"),
            },
        }
    )
    node = FixSQLNode(
        name="reflection_fix",
        config={"model_alias": "strong"},
        dependencies=dependencies,
    )

    result = node.run(state)
    state.apply_patch(result.state_patch)

    assert state.data["current_sql"] == fixed_sql
    assert state.data["generated_sql"] == fixed_sql
    assert state.data["repair_history"][0]["new_sql"] == fixed_sql


def test_fix_sql_node_uses_configured_prompt_template(tmp_path) -> None:
    template_path = tmp_path / "fix_sql.yaml"
    template_path.write_text(
        "\n".join(
            [
                'system: "修复 {{ error_category }} SQL"',
                "user: |",
                "  原始问题: {{ original_question }}",
                "  当前SQL: {{ current_sql }}",
                "  错误: {{ original_error }}",
                "  Schema:",
                "  {{ related_schema }}",
            ]
        ),
        encoding="utf-8",
    )
    state = WorkflowState(
        user_question="列出订单金额",
        data={
            "attempt_count": 0,
            "repair_instruction": {
                "original_question": "列出订单金额",
                "current_sql": "SELECT total_amount FROM orders",
                "error_category": "unknown_column",
                "original_error": "字段不存在: orders.total_amount",
                "related_schema": {"tables": [{"name": "orders"}]},
                "repair_history": [],
                "reason": "根据错误类型 unknown_column 修复 SQL",
            },
        },
    )
    llm_client = MockLLMClient(responses={"strong": "SELECT amount FROM orders"})
    dependencies = NodeDependencies(
        values={
            "llm_client": llm_client,
            "model_profiles": {
                "strong": ModelProfile(alias="strong", provider="mock", model_name="strong-model"),
            },
        }
    )
    node = FixSQLNode(
        name="reflection_fix",
        config={"model_alias": "strong", "prompt_template": str(template_path)},
        dependencies=dependencies,
    )

    node.run(state)

    assert llm_client.requests[0].system_prompt == "修复 unknown_column SQL"
    assert "字段不存在: orders.total_amount" in llm_client.requests[0].user_prompt
    assert "Original question" not in llm_client.requests[0].user_prompt


def test_fix_sql_node_injects_repair_strategy_into_prompt_and_history() -> None:
    state = WorkflowState(
        user_question="统计订单金额",
        data={
            "attempt_count": 0,
            "repair_instruction": {
                "original_question": "统计订单金额",
                "current_sql": "SELECT SUM(orders.total_amount) FROM orders",
                "error_category": "unknown_column",
                "original_error": "字段不存在: orders.total_amount",
                "related_schema": {"tables": [{"name": "orders"}]},
                "repair_history": [],
                "reason": "根据 repair_unknown_column 修复 SQL",
                "strategy": {
                    "name": "repair_unknown_column",
                    "focus": "修复不存在字段引用",
                    "instructions": [
                        "只替换不存在字段 total_amount",
                        "优先从相关 Schema 中选择同表字段",
                    ],
                    "avoid": ["不要虚构字段"],
                },
            },
        },
    )
    llm_client = MockLLMClient(responses={"strong": "SELECT SUM(amount) FROM orders"})
    dependencies = NodeDependencies(
        values={
            "llm_client": llm_client,
            "model_profiles": {
                "strong": ModelProfile(alias="strong", provider="mock", model_name="strong-model"),
            },
        }
    )
    node = FixSQLNode(
        name="reflection_fix",
        config={"model_alias": "strong"},
        dependencies=dependencies,
    )

    result = node.run(state)
    state.apply_patch(result.state_patch)

    assert "定向修复策略" in llm_client.requests[0].user_prompt
    assert "只替换不存在字段 total_amount" in llm_client.requests[0].user_prompt
    assert "不要虚构字段" in llm_client.requests[0].user_prompt
    assert state.data["repair_history"][0]["strategy_name"] == "repair_unknown_column"


def test_fix_sql_node_injects_reflection_reason_and_context_summary() -> None:
    state = WorkflowState(
        user_question="统计订单金额",
        data={
            "attempt_count": 1,
            "reflection_decision": {
                "strategy": "FIX_SQL",
                "reason": "字段不存在，按 linked schema 修复字段名",
                "confidence": 0.8,
                "error_category": "unknown_column",
                "attempt_count": 1,
                "max_attempts": 3,
            },
            "sql_contexts": [
                {
                    "attempt": 1,
                    "sql": "SELECT total_amount FROM orders",
                    "validation_error": {
                        "category": "unknown_column",
                        "message": "no such column: total_amount",
                    },
                    "reflection_strategy": "FIX_SQL",
                    "reflection_reason": "字段不存在，按 linked schema 修复字段名",
                }
            ],
            "repair_instruction": {
                "original_question": "统计订单金额",
                "current_sql": "SELECT total_amount FROM orders",
                "error_category": "unknown_column",
                "original_error": "字段不存在: orders.total_amount",
                "related_schema": {"tables": [{"name": "orders"}]},
                "repair_history": [],
                "reason": "字段不存在，按 linked schema 修复字段名",
            },
        },
    )
    llm_client = MockLLMClient(responses={"strong": "SELECT SUM(amount) FROM orders"})
    dependencies = NodeDependencies(
        values={
            "llm_client": llm_client,
            "model_profiles": {
                "strong": ModelProfile(alias="strong", provider="mock", model_name="strong-model"),
            },
        }
    )
    node = FixSQLNode(
        name="reflection_fix",
        config={"model_alias": "strong"},
        dependencies=dependencies,
    )

    node.run(state)

    assert "字段不存在，按 linked schema 修复字段名" in llm_client.requests[0].user_prompt
    memory_block = llm_client.requests[0].user_prompt.split("最近反思记忆:", 1)[1].split(
        "策略反思原因:",
        1,
    )[0]
    assert "sha256:" in memory_block
    assert "SELECT total_amount FROM orders" not in memory_block
