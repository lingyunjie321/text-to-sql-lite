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


def test_prompt_injects_pruned_rag_context() -> None:
    prompt = PromptBuilder().build(
        user_question="统计订单金额",
        target_dialect="sqlite",
        linked_schema={
            "tables": [
                {
                    "name": "orders",
                    "columns": {"amount": {"name": "amount", "type": "NUMERIC"}},
                }
            ]
        },
        examples=[],
        rag_context={
            "reference_sql": [
                {
                    "item": {
                        "name": "order_amount",
                        "natural_language": "订单金额",
                        "sql": "SELECT amount FROM orders",
                    },
                    "score": 5,
                    "reasons": ["表重叠: orders"],
                }
            ],
            "documents": [
                {
                    "item": {
                        "title": "订单口径",
                        "content": "订单金额使用 orders.amount 字段",
                    },
                    "score": 3,
                    "reasons": ["词项匹配: 金额"],
                }
            ],
            "metrics": [
                {
                    "item": {
                        "name": "total_amount",
                        "description": "订单总金额",
                        "expression": "SUM(orders.amount)",
                    },
                    "score": 3,
                    "reasons": ["词项匹配: 金额"],
                }
            ],
            "semantic_models": [
                {
                    "item": {
                        "name": "orders_semantic",
                        "description": "订单事实表",
                    },
                    "score": 3,
                    "reasons": ["表重叠: orders"],
                }
            ],
        },
    )

    assert "Knowledge context:" in prompt.user_prompt
    assert "Reference SQL 1 name: order_amount" in prompt.user_prompt
    assert "Document 1 title: 订单口径" in prompt.user_prompt
    assert "Metric 1 expression: SUM(orders.amount)" in prompt.user_prompt
    assert "Semantic model 1 name: orders_semantic" in prompt.user_prompt
    assert prompt.summary["reference_sql_count"] == 1
    assert prompt.summary["document_context_count"] == 1
    assert prompt.summary["metric_context_count"] == 1
    assert prompt.summary["semantic_model_count"] == 1


def test_prompt_injects_recent_reflection_memory_without_full_sql() -> None:
    prompt = PromptBuilder().build(
        user_question="统计订单金额",
        target_dialect="sqlite",
        linked_schema={
            "tables": [
                {
                    "name": "orders",
                    "columns": {"amount": {"name": "amount", "type": "NUMERIC"}},
                }
            ]
        },
        examples=[],
        sql_contexts=[
            {
                "attempt": 1,
                "sql": "SELECT total_amount FROM orders",
                "validation_error": {
                    "category": "unknown_column",
                    "message": "no such column: total_amount",
                },
                "reflection_strategy": "FIX_SQL",
                "reflection_reason": "字段不存在，修复字段名",
            }
        ],
    )

    assert "Recent reflection memory:" in prompt.user_prompt
    assert "sha256:" in prompt.user_prompt
    assert "SELECT total_amount FROM orders" not in prompt.user_prompt
    assert "FIX_SQL" in prompt.user_prompt
    assert prompt.summary["sql_context_count"] == 1
