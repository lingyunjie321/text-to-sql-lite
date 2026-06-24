from text_to_sql_demo.reflection import (
    append_success_sql_context,
    build_success_sql_attempt_context,
    summarize_sql_contexts,
)


def test_success_sql_context_records_result_summary_without_api_sql() -> None:
    context = build_success_sql_attempt_context(
        state_data={
            "attempt_count": 1,
            "validated_sql": "SELECT SUM(amount) AS total_amount FROM orders",
            "execution_result": {
                "success": True,
                "columns": ["total_amount"],
                "rows": [{"total_amount": 208.5}],
                "duration_ms": 7,
            },
        }
    )
    sql_contexts = append_success_sql_context([], context)

    assert sql_contexts == [
        {
            "attempt": 2,
            "sql": "SELECT SUM(amount) AS total_amount FROM orders",
            "validation_error": None,
            "execution_error": None,
            "result_summary": {
                "row_count": 1,
                "column_count": 1,
                "duration_ms": 7,
            },
            "reflection_strategy": "SUCCESS",
            "reflection_reason": "SQL 已通过校验并成功执行",
        }
    ]

    summarized = summarize_sql_contexts(sql_contexts)
    assert summarized[0]["sql_length"] == len(
        "SELECT SUM(amount) AS total_amount FROM orders"
    )
    assert summarized[0]["sql_hash"].startswith("sha256:")
    assert "sql" not in summarized[0]


def test_success_sql_context_updates_same_final_sql_instead_of_duplicating() -> None:
    first = build_success_sql_attempt_context(
        state_data={
            "attempt_count": 0,
            "validated_sql": "SELECT id FROM orders",
            "execution_result": {
                "success": True,
                "columns": ["id"],
                "rows": [{"id": 1}],
                "duration_ms": 3,
            },
        }
    )
    second = build_success_sql_attempt_context(
        state_data={
            "attempt_count": 0,
            "validated_sql": "SELECT id FROM orders",
            "execution_result": {
                "success": True,
                "columns": ["id"],
                "rows": [{"id": 1}, {"id": 2}],
                "duration_ms": 5,
            },
        }
    )

    sql_contexts = append_success_sql_context([], first)
    sql_contexts = append_success_sql_context(sql_contexts, second)

    assert len(sql_contexts) == 1
    assert sql_contexts[0]["result_summary"] == {
        "row_count": 2,
        "column_count": 1,
        "duration_ms": 5,
    }
