import pytest

from app.connectors.errors import ErrorType
from app.connectors.metadata import empty_schema_snapshot
from app.validation import validate_sql


def _validate(sql: str):
    return validate_sql(
        sql,
        allowed_schemas=(),
        allowed_tables=(),
        snapshot=empty_schema_snapshot(),
    )


def test_accepts_one_table_free_select() -> None:
    result = _validate("select current_date")

    assert result.is_valid
    assert result.normalized_sql == "SELECT CURRENT_DATE"


@pytest.mark.parametrize("sql", ["", "   ", "SELECT ("])
def test_parse_failures_are_repairable_syntax_errors(sql: str) -> None:
    result = _validate(sql)

    assert not result.is_valid
    assert result.issue is not None
    assert result.issue.error_type is ErrorType.SYNTAX_ERROR
    assert result.issue.code == "SQL_PARSE_ERROR"


def test_rejects_all_statements_when_input_contains_two() -> None:
    result = _validate("SELECT 1; SELECT 2")

    assert not result.is_valid
    assert result.issue is not None
    assert result.issue.error_type is ErrorType.PERMISSION_DENIED
    assert result.issue.code == "SQL_MULTIPLE_STATEMENTS"


@pytest.mark.parametrize(
    "sql",
    [
        "INSERT INTO film(film_id) VALUES (1)",
        "UPDATE film SET title = 'x'",
        "DELETE FROM film",
        "MERGE INTO film USING language ON true WHEN MATCHED THEN DELETE",
        "CREATE TABLE unsafe(id int)",
        "ALTER TABLE film ADD COLUMN unsafe int",
        "DROP TABLE film",
        "TRUNCATE TABLE film",
        "COPY film TO STDOUT",
        "CALL unsafe()",
        "DO $$ BEGIN END $$",
        "SET search_path TO public",
        "RESET search_path",
        (
            "WITH changed AS (DELETE FROM film RETURNING film_id) "
            "SELECT film_id FROM changed"
        ),
        "SELECT film_id INTO backup FROM film",
        "SELECT film_id FROM film FOR UPDATE",
        "SELECT film_id FROM film FOR SHARE",
    ],
)
def test_rejects_non_read_only_or_forbidden_ast(sql: str) -> None:
    result = _validate(sql)

    assert not result.is_valid
    assert result.issue is not None
    assert result.issue.error_type is ErrorType.PERMISSION_DENIED
    assert result.issue.code in {
        "SQL_NOT_READ_ONLY",
        "SQL_FORBIDDEN_NODE",
    }


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM film",
        "SELECT film.* FROM film",
        "SELECT COUNT(film.*) FROM film",
    ],
)
def test_rejects_projection_wildcards(sql: str) -> None:
    result = _validate(sql)

    assert result.issue is not None
    assert result.issue.code == "SQL_WILDCARD_FORBIDDEN"


def test_allows_count_star() -> None:
    assert _validate("SELECT COUNT(*)").is_valid


def test_unknown_ast_fails_closed() -> None:
    result = _validate("SELECT 1 OFFSET 1")

    assert result.issue is not None
    assert result.issue.code == "SQL_UNKNOWN_AST"
