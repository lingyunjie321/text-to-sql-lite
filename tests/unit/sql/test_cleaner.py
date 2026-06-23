from text_to_sql_demo.sql.cleaner import clean_llm_sql_output


def test_clean_llm_sql_output_strips_sql_fence() -> None:
    sql = "SELECT id FROM orders"

    assert clean_llm_sql_output(f"```sql\n{sql}\n```") == sql


def test_clean_llm_sql_output_extracts_sql_fence_from_explanation() -> None:
    sql = "SELECT amount FROM orders"
    response = f"下面是查询：\n```sqlite\n{sql}\n```\n可以直接执行。"

    assert clean_llm_sql_output(response) == sql


def test_clean_llm_sql_output_keeps_plain_sql() -> None:
    sql = "SELECT id, amount FROM orders"

    assert clean_llm_sql_output(sql) == sql


def test_clean_llm_sql_output_keeps_non_sql_fence() -> None:
    response = "```python\nprint('not sql')\n```"

    assert clean_llm_sql_output(response) == response
