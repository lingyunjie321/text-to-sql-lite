import pytest

from app.connectors.errors import ErrorType
from app.connectors.metadata import (
    ColumnMetadata,
    TableMetadata,
    build_schema_snapshot,
)
from app.validation import validate_sql


FILM = TableMetadata(
    schema_name="public",
    table_name="film",
    relation_kind="table",
    comment=None,
    columns=(
        ColumnMetadata(
            schema_name="public",
            table_name="film",
            column_name="film_id",
            ordinal_position=1,
            data_type="int4",
            formatted_type="integer",
            nullable=False,
            comment=None,
        ),
        ColumnMetadata(
            schema_name="public",
            table_name="film",
            column_name="title",
            ordinal_position=2,
            data_type="text",
            formatted_type="text",
            nullable=False,
            comment=None,
        ),
    ),
)
SNAPSHOT = build_schema_snapshot(
    tables=(FILM,),
    primary_keys=(),
    foreign_keys=(),
    unique_constraints=(),
    unique_indexes=(),
)


@pytest.mark.parametrize(
    ("sql", "error_type", "code"),
    [
        ("SELECT (", ErrorType.SYNTAX_ERROR, "SQL_PARSE_ERROR"),
        (
            "SELECT 1; SELECT 2",
            ErrorType.PERMISSION_DENIED,
            "SQL_MULTIPLE_STATEMENTS",
        ),
        (
            "INSERT INTO film(film_id) VALUES (1)",
            ErrorType.PERMISSION_DENIED,
            "SQL_NOT_READ_ONLY",
        ),
        (
            "UPDATE film SET title = 'x'",
            ErrorType.PERMISSION_DENIED,
            "SQL_NOT_READ_ONLY",
        ),
        (
            "DELETE FROM film",
            ErrorType.PERMISSION_DENIED,
            "SQL_NOT_READ_ONLY",
        ),
        (
            "MERGE INTO film USING language ON true "
            "WHEN MATCHED THEN DELETE",
            ErrorType.PERMISSION_DENIED,
            "SQL_NOT_READ_ONLY",
        ),
        (
            "CREATE TABLE unsafe(id int)",
            ErrorType.PERMISSION_DENIED,
            "SQL_NOT_READ_ONLY",
        ),
        (
            "ALTER TABLE film ADD COLUMN unsafe int",
            ErrorType.PERMISSION_DENIED,
            "SQL_NOT_READ_ONLY",
        ),
        (
            "DROP TABLE film",
            ErrorType.PERMISSION_DENIED,
            "SQL_NOT_READ_ONLY",
        ),
        (
            "TRUNCATE TABLE film",
            ErrorType.PERMISSION_DENIED,
            "SQL_NOT_READ_ONLY",
        ),
        (
            "COPY film TO STDOUT",
            ErrorType.PERMISSION_DENIED,
            "SQL_NOT_READ_ONLY",
        ),
        (
            "CALL unsafe()",
            ErrorType.PERMISSION_DENIED,
            "SQL_NOT_READ_ONLY",
        ),
        (
            "DO $$ BEGIN END $$",
            ErrorType.PERMISSION_DENIED,
            "SQL_NOT_READ_ONLY",
        ),
        (
            "SET search_path TO public",
            ErrorType.PERMISSION_DENIED,
            "SQL_NOT_READ_ONLY",
        ),
        (
            "RESET search_path",
            ErrorType.PERMISSION_DENIED,
            "SQL_NOT_READ_ONLY",
        ),
        (
            "WITH changed AS (DELETE FROM film RETURNING film_id) "
            "SELECT film_id FROM changed",
            ErrorType.PERMISSION_DENIED,
            "SQL_FORBIDDEN_NODE",
        ),
        (
            "SELECT film_id INTO backup FROM film",
            ErrorType.PERMISSION_DENIED,
            "SQL_FORBIDDEN_NODE",
        ),
        (
            "SELECT film_id FROM film FOR UPDATE",
            ErrorType.PERMISSION_DENIED,
            "SQL_FORBIDDEN_NODE",
        ),
        (
            "SELECT film_id FROM film FOR SHARE",
            ErrorType.PERMISSION_DENIED,
            "SQL_FORBIDDEN_NODE",
        ),
        (
            "SELECT * FROM film",
            ErrorType.PERMISSION_DENIED,
            "SQL_WILDCARD_FORBIDDEN",
        ),
        (
            "SELECT f FROM film AS f",
            ErrorType.PERMISSION_DENIED,
            "SQL_WILDCARD_FORBIDDEN",
        ),
        (
            "SELECT CAST(f AS TEXT) FROM film AS f",
            ErrorType.PERMISSION_DENIED,
            "SQL_WILDCARD_FORBIDDEN",
        ),
        (
            "SELECT staff_id FROM staff",
            ErrorType.PERMISSION_DENIED,
            "SQL_OBJECT_NOT_ALLOWED",
        ),
        (
            "SELECT pg_sleep(1)",
            ErrorType.PERMISSION_DENIED,
            "SQL_FUNCTION_NOT_ALLOWED",
        ),
        (
            "SELECT pg_read_file('/tmp/x')",
            ErrorType.PERMISSION_DENIED,
            "SQL_FUNCTION_NOT_ALLOWED",
        ),
        (
            "SELECT dblink('x', 'y')",
            ErrorType.PERMISSION_DENIED,
            "SQL_FUNCTION_NOT_ALLOWED",
        ),
        (
            "SELECT custom_udf(film_id) FROM film",
            ErrorType.PERMISSION_DENIED,
            "SQL_FUNCTION_NOT_ALLOWED",
        ),
        (
            "SELECT CAST('x' AS custom_type)",
            ErrorType.PERMISSION_DENIED,
            "SQL_FUNCTION_NOT_ALLOWED",
        ),
        (
            "SELECT CAST('x' AS custom_type(10))",
            ErrorType.PERMISSION_DENIED,
            "SQL_FUNCTION_NOT_ALLOWED",
        ),
    ],
)
def test_p0_dangerous_sql_fails_closed_without_leakage(
    sql: str,
    error_type: ErrorType,
    code: str,
) -> None:
    result = validate_sql(
        sql,
        allowed_schemas=("public",),
        allowed_tables=("public.film",),
        snapshot=SNAPSHOT,
    )

    assert result.is_valid is False
    assert result.normalized_sql is None
    assert result.referenced_tables == ()
    assert result.referenced_columns == ()
    assert result.issue is not None
    assert result.issue.error_type is error_type
    assert result.issue.code == code
    assert sql not in repr(result)
    message = result.issue.public_message.lower()
    for sensitive_name in (
        "film",
        "staff",
        "pg_sleep",
        "pg_read_file",
        "dblink",
        "custom_udf",
        "backup",
    ):
        assert sensitive_name not in message
