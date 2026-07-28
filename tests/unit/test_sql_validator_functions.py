import pytest

from app.connectors.metadata import empty_schema_snapshot
from app.validation import validate_sql


def _validate(expression: str):
    return validate_sql(
        f"SELECT {expression}",
        allowed_schemas=(),
        allowed_tables=(),
        snapshot=empty_schema_snapshot(),
    )


@pytest.mark.parametrize(
    "expression",
    [
        "COUNT(1)",
        "SUM(1)",
        "AVG(1)",
        "MIN(1)",
        "MAX(1)",
        "COALESCE(NULL, 0)",
        "NULLIF(1, 0)",
        "LOWER('A')",
        "UPPER('a')",
        "LENGTH('a')",
        "TRIM(' a ')",
        "SUBSTRING('abc' FROM 1 FOR 2)",
        "DATE_TRUNC('month', TIMESTAMP '2026-07-28')",
        "EXTRACT(YEAR FROM DATE '2026-07-28')",
        "CURRENT_DATE",
        "ROUND(1.5)",
        "ABS(-1)",
        "CEIL(1.2)",
        "FLOOR(1.8)",
        "CASE WHEN 1 = 1 THEN 1 ELSE 0 END",
        "CAST(1 AS TEXT)",
        "CAST(1 AS VARCHAR(10))",
        "CAST(1 AS NUMERIC(10, 2))",
    ],
)
def test_allows_mvp_function_set(expression: str) -> None:
    assert _validate(expression).is_valid


@pytest.mark.parametrize(
    "expression",
    [
        "pg_sleep(1)",
        "dblink('x', 'y')",
        "pg_read_file('/tmp/x')",
        "lo_import('/tmp/x')",
        "custom_udf(1)",
        "IF(TRUE, 1, 0)",
    ],
)
def test_rejects_anonymous_unapproved_and_if_functions(
    expression: str,
) -> None:
    result = _validate(expression)

    assert not result.is_valid
    assert result.issue is not None
    assert result.issue.code == "SQL_FUNCTION_NOT_ALLOWED"
    function_name = expression.split("(", 1)[0].lower()
    assert function_name not in result.issue.public_message.lower()
