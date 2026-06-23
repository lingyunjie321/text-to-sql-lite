from pathlib import Path

from text_to_sql_demo.prompts.builder import PromptBuilder


def test_prompt_builder_renders_yaml_template_with_patterns(tmp_path: Path) -> None:
    template_path = tmp_path / "generate_sql.yaml"
    template_path.write_text(
        "\n".join(
            [
                'system: "生成 {{ target_dialect }} SQL"',
                "user: |",
                "  问题: {{ user_question }}",
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

    prompt = PromptBuilder().build(
        user_question="查询客户订单金额",
        target_dialect="sqlite",
        original_schema={"tables": {"orders": {}, "customers": {}, "products": {}}},
        linked_schema={
            "tables": [
                {
                    "name": "orders",
                    "columns": {
                        "amount": {"name": "amount", "type": "NUMERIC"},
                    },
                }
            ]
        },
        examples=[
            {
                "example": {
                    "natural_language": "查询客户订单金额",
                    "sql": "SELECT amount FROM orders",
                }
            }
        ],
        original_example_count=3,
        business_patterns=[
            {
                "pattern": {
                    "name": "sqlite_amount",
                    "description": "金额字段使用 orders.amount",
                    "pattern": "SUM(orders.amount)",
                }
            }
        ],
        template_path=template_path,
    )

    assert prompt.system_prompt == "生成 sqlite SQL"
    assert "orders" in prompt.user_prompt
    assert "products" not in prompt.user_prompt
    assert "SELECT amount FROM orders" in prompt.user_prompt
    assert "SUM(orders.amount)" in prompt.user_prompt
    assert prompt.summary["business_pattern_count"] == 1
