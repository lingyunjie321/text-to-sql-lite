from text_to_sql_demo.llm.client import MockLLMClient
from text_to_sql_demo.llm.models import ModelProfile
from text_to_sql_demo.nodes.sql_generation import GenerateSQLNode, GenSQLAgenticNode
from text_to_sql_demo.workflow.dependencies import NodeDependencies
from text_to_sql_demo.workflow.state import WorkflowState


def test_mock_llm_returns_deterministic_sql() -> None:
    client = MockLLMClient(responses={"light": "SELECT name FROM customers;"})

    response = client.complete(
        model_alias="light",
        model_name="light-model",
        system_prompt="system",
        user_prompt="prompt",
    )

    assert response.text == "SELECT name FROM customers;"
    assert response.model_alias == "light"


def test_generate_sql_node_outputs_sql_routing_and_prompt_summary() -> None:
    state = WorkflowState(
        user_question="列出所有客户邮箱",
        data={
            "schema": {
                "tables": {
                    "customers": {},
                    "orders": {},
                    "products": {},
                }
            },
            "schema_linking": {
                "tables": [
                    {
                        "name": "customers",
                        "columns": {
                            "name": {"name": "name", "type": "VARCHAR"},
                            "email": {"name": "email", "type": "VARCHAR"},
                        },
                    }
                ]
            },
            "retrieved_examples": [
                {
                    "example": {
                        "natural_language": "列出所有客户邮箱",
                        "sql": "SELECT email FROM customers;",
                        "dialect": "sqlite",
                        "tags": ["客户"],
                        "involved_tables": ["customers"],
                    },
                    "score": 10.0,
                    "reasons": ["词项匹配"],
                }
            ],
            "available_example_count": 6,
        },
    )
    llm_client = MockLLMClient(responses={"light": "SELECT email FROM customers;"})
    dependencies = NodeDependencies(
        values={
            "llm_client": llm_client,
            "model_profiles": {
                "light": ModelProfile(alias="light", provider="mock", model_name="light-model"),
                "strong": ModelProfile(alias="strong", provider="mock", model_name="strong-model"),
            },
        }
    )
    node = GenerateSQLNode(
        name="sql_generation",
        config={"target_dialect": "sqlite"},
        dependencies=dependencies,
    )

    result = node.run(state)
    state.apply_patch(result.state_patch)

    assert state.data["generated_sql"] == "SELECT email FROM customers;"
    assert state.data["selected_model"] == "light"
    assert state.data["complexity_level"] == "simple"
    assert state.data["routing_reason"]
    assert state.data["prompt_summary"]["original_schema_table_count"] == 3
    assert state.data["prompt_summary"]["injected_schema_table_count"] == 1
    assert state.data["prompt_summary"]["original_example_count"] == 6
    assert state.data["prompt_summary"]["injected_example_count"] == 1
    assert "Target dialect: sqlite" in llm_client.requests[0].user_prompt
    assert "```" not in llm_client.requests[0].user_prompt


def test_gen_sql_agentic_node_uses_template_and_business_patterns(tmp_path) -> None:
    template_path = tmp_path / "generate_sql.yaml"
    template_path.write_text(
        "\n".join(
            [
                'system: "生成 {{ target_dialect }} SQL"',
                "user: |",
                "  问题: {{ user_question }}",
                "  方言: {{ target_dialect }}",
                "  Schema:",
                "  {{ schema_block }}",
                "  Examples:",
                "  {{ examples_block }}",
                "  Patterns:",
                "  {{ patterns_block }}",
            ]
        ),
        encoding="utf-8",
    )
    patterns_path = tmp_path / "patterns.yaml"
    patterns_path.write_text(
        """
patterns:
  - name: sqlite_rank_by_region
    dialect: sqlite
    description: 地区内排名优先使用 RANK() OVER(PARTITION BY ...)
    pattern: 使用窗口函数按地区分区排序
    tags: ["地区", "排名"]
    involved_tables: ["orders", "regions"]
""",
        encoding="utf-8",
    )
    state = WorkflowState(
        user_question="统计每个地区订单金额排名",
        data={
            "schema": {
                "tables": {
                    "orders": {},
                    "regions": {},
                    "products": {},
                }
            },
            "schema_linking": {
                "tables": [
                    {
                        "name": "orders",
                        "columns": {
                            "amount": {"name": "amount", "type": "NUMERIC"},
                            "customer_id": {"name": "customer_id", "type": "INTEGER"},
                        },
                    },
                    {
                        "name": "regions",
                        "columns": {
                            "name": {"name": "name", "type": "VARCHAR"},
                        },
                    },
                ]
            },
            "retrieved_examples": [],
            "available_example_count": 0,
        },
    )
    llm_client = MockLLMClient(responses={"strong": "SELECT 1;"})
    dependencies = NodeDependencies(
        values={
            "llm_client": llm_client,
            "model_profiles": {
                "light": ModelProfile(alias="light", provider="mock", model_name="light-model"),
                "strong": ModelProfile(alias="strong", provider="mock", model_name="strong-model"),
            },
        }
    )
    node = GenSQLAgenticNode(
        name="sql_generation",
        config={
            "target_dialect": "sqlite",
            "prompt_template": str(template_path),
            "patterns_path": str(patterns_path),
            "patterns_top_k": 1,
        },
        dependencies=dependencies,
    )

    result = node.run(state)
    state.apply_patch(result.state_patch)

    assert state.data["business_patterns"][0]["pattern"]["name"] == "sqlite_rank_by_region"
    assert state.data["prompt_summary"]["business_pattern_count"] == 1
    assert llm_client.requests[0].system_prompt == "生成 sqlite SQL"
    assert "使用窗口函数按地区分区排序" in llm_client.requests[0].user_prompt
    assert "products" not in llm_client.requests[0].user_prompt
    assert isinstance(node, GenerateSQLNode)
