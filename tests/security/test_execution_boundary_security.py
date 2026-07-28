from dataclasses import replace
from unittest.mock import Mock

import pytest

from app.connectors.errors import (
    DatabaseError,
    ErrorType,
    PostgreSQLConnectorError,
)
from app.connectors.models import ExecutionResult
from app.connectors.metadata import (
    ColumnMetadata,
    TableMetadata,
    build_schema_snapshot,
)
from app.execution import execute_validated_sql
from app.validation import success_result, validate_sql


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
    ),
)
SNAPSHOT = build_schema_snapshot(
    tables=(FILM,),
    primary_keys=(),
    foreign_keys=(),
    unique_constraints=(),
    unique_indexes=(),
)
EMPTY_RESULT = ExecutionResult(
    columns=(),
    rows=[],
    returned_row_count=0,
    truncated=False,
    execution_time_ms=0.1,
)


def _execute(validation: object, connector: Mock):
    return execute_validated_sql(  # type: ignore[arg-type]
        validation,
        allowed_schemas=("public",),
        allowed_tables=("public.film",),
        snapshot=SNAPSHOT,
        connector=connector,
    )


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM film",
        "SELECT film_id FROM film; DELETE FROM film",
        "SELECT pg_sleep(1)",
        "SELECT film_id FROM private.staff",
    ],
)
def test_rejected_sql_never_reaches_connector(sql: str) -> None:
    validation = validate_sql(
        sql,
        allowed_schemas=("public",),
        allowed_tables=("public.film",),
        snapshot=SNAPSHOT,
    )
    connector = Mock()

    with pytest.raises(
        ValueError, match="^execution context is invalid$"
    ) as caught:
        _execute(validation, connector)

    connector.execute.assert_not_called()
    assert sql not in repr(caught.value)


def test_inconsistent_success_cannot_smuggle_a_second_sql() -> None:
    validation = success_result(
        "SELECT film_id FROM film",
        referenced_tables=("public.film",),
        referenced_columns=("public.film.film_id",),
    )
    validation = replace(
        validation,
        is_valid=False,
        normalized_sql="DELETE FROM film",
    )
    connector = Mock()

    with pytest.raises(ValueError):
        _execute(validation, connector)

    connector.execute.assert_not_called()


@pytest.mark.parametrize(
    "dangerous_sql",
    [
        "DELETE FROM film",
        "SELECT film_id FROM film; DELETE FROM film",
        "SELECT pg_sleep(1)",
    ],
)
def test_forged_success_result_cannot_bypass_validator(
    dangerous_sql: str,
) -> None:
    forged = success_result(
        dangerous_sql,
        referenced_tables=(),
        referenced_columns=(),
    )
    connector = Mock()
    connector.execute.return_value = EMPTY_RESULT

    with pytest.raises(
        ValueError, match="^execution context is invalid$"
    ):
        _execute(forged, connector)

    connector.execute.assert_not_called()


def test_database_error_exposes_only_sanitized_details() -> None:
    validated_sql = "SELECT film_id FROM film"
    safe_error = DatabaseError(
        sqlstate="42P01",
        error_type=ErrorType.SCHEMA_ERROR,
        code="DB_SCHEMA_ERROR",
        retryable=False,
        public_message="The SQL references an invalid database object.",
    )
    connector = Mock()
    connector.execute.side_effect = PostgreSQLConnectorError(safe_error)
    validation = validate_sql(
        validated_sql,
        allowed_schemas=("public",),
        allowed_tables=("public.film",),
        snapshot=SNAPSHOT,
    )

    outcome = _execute(validation, connector)

    rendered = repr(outcome)
    assert outcome.error is safe_error
    assert validated_sql not in rendered
    assert "hidden_table" not in outcome.error.public_message
