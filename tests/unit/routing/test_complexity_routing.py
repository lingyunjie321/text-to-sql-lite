from text_to_sql_demo.llm.models import ModelProfile
from text_to_sql_demo.routing.complexity import ComplexityClassifier, ModelRouter


def test_simple_single_table_query_routes_to_light() -> None:
    linked_schema = {
        "tables": [
            {
                "name": "customers",
                "columns": {
                    "name": {"name": "name", "type": "VARCHAR"},
                    "email": {"name": "email", "type": "VARCHAR"},
                },
            }
        ]
    }
    classifier = ComplexityClassifier()
    router = ModelRouter(
        profiles={
            "light": ModelProfile(alias="light", provider="mock", model_name="light-model"),
            "strong": ModelProfile(alias="strong", provider="mock", model_name="strong-model"),
        }
    )

    complexity = classifier.classify("列出所有客户邮箱", linked_schema)
    selected = router.route(complexity)

    assert complexity.level == "simple"
    assert selected.alias == "light"


def test_multi_table_window_query_routes_to_strong() -> None:
    linked_schema = {
        "tables": [
            {"name": "regions", "columns": {}},
            {"name": "customers", "columns": {}},
            {"name": "orders", "columns": {}},
        ]
    }
    classifier = ComplexityClassifier()
    router = ModelRouter(
        profiles={
            "light": ModelProfile(alias="light", provider="mock", model_name="light-model"),
            "strong": ModelProfile(alias="strong", provider="mock", model_name="strong-model"),
        }
    )

    complexity = classifier.classify("统计每个地区订单金额排名，使用窗口函数", linked_schema)
    selected = router.route(complexity)

    assert complexity.level == "complex"
    assert selected.alias == "strong"
    assert any("窗口函数" in reason for reason in complexity.reasons)
