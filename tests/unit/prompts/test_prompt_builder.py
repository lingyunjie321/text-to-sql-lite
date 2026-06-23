from text_to_sql_demo.prompts.builder import PromptBuilder


def test_prompt_uses_only_linked_schema_and_excludes_unlinked_tables() -> None:
    original_schema = {
        "tables": {
            "orders": {},
            "customers": {},
            "products": {},
        }
    }
    linked_schema = {
        "tables": [
            {
                "name": "orders",
                "columns": {
                    "id": {"name": "id", "type": "INTEGER"},
                    "amount": {"name": "amount", "type": "NUMERIC"},
                },
            },
            {
                "name": "customers",
                "columns": {
                    "id": {"name": "id", "type": "INTEGER"},
                    "name": {"name": "name", "type": "VARCHAR"},
                },
            },
        ]
    }

    prompt = PromptBuilder().build(
        user_question="查询客户订单金额",
        target_dialect="postgres",
        original_schema=original_schema,
        linked_schema=linked_schema,
        examples=[
            {
                "example": {
                    "natural_language": "查询客户订单金额",
                    "sql": "SELECT amount FROM orders",
                }
            }
        ],
        original_example_count=4,
    )

    assert "orders" in prompt.user_prompt
    assert "customers" in prompt.user_prompt
    assert "products" not in prompt.user_prompt
    assert "Target dialect: postgres" in prompt.user_prompt
    assert "```" not in prompt.user_prompt
    assert prompt.summary["original_schema_table_count"] == 3
    assert prompt.summary["injected_schema_table_count"] == 2
    assert prompt.summary["original_example_count"] == 4
    assert prompt.summary["injected_example_count"] == 1
