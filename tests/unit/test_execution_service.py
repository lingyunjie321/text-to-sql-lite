from dataclasses import replace
from unittest.mock import Mock

import pytest

from app.connectors.errors import (
    DatabaseError,
    ErrorType,
    PostgreSQLConnectorError,
)
from app.connectors.metadata import (
    ColumnMetadata,
    TableMetadata,
    build_schema_snapshot,
)
from app.connectors.models import ExecutionResult
from app.execution import execute_validated_sql
from app.validation import (
    ValidationIssue,
    failure_result,
    validate_sql,
)


RESULT = ExecutionResult(
    columns=(),
    rows=[],
    returned_row_count=0,
    truncated=False,
    execution_time_ms=0.1,
)
ERROR = DatabaseError(
    sqlstate="42P01",
    error_type=ErrorType.SCHEMA_ERROR,
    code="DB_SCHEMA_ERROR",
    retryable=False,
    public_message="The SQL references an invalid database object.",
)
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
VALIDATION = validate_sql(
    "SELECT film_id FROM film",
    allowed_schemas=("public",),
    allowed_tables=("public.film",),
    snapshot=SNAPSHOT,
)


def _execute(validation: object, connector: Mock):
    return execute_validated_sql(  # type: ignore[arg-type]
        validation,
        allowed_schemas=("public",),
        allowed_tables=("public.film",),
        snapshot=SNAPSHOT,
        connector=connector,
    )


def test_executes_normalized_sql_once_and_preserves_result() -> None:
    connector = Mock()
    connector.execute.return_value = RESULT

    outcome = _execute(VALIDATION, connector)

    connector.execute.assert_called_once_with(
        "SELECT film_id FROM film"
    )
    assert outcome.result is RESULT
    assert outcome.error is None


def test_connector_error_becomes_failure_outcome() -> None:
    connector = Mock()
    connector.execute.side_effect = PostgreSQLConnectorError(ERROR)

    outcome = _execute(VALIDATION, connector)

    assert outcome.result is None
    assert outcome.error is ERROR
    connector.execute.assert_called_once_with(
        "SELECT film_id FROM film"
    )


def test_unknown_programming_error_is_not_misclassified() -> None:
    connector = Mock()
    connector.execute.side_effect = RuntimeError("programming defect")

    with pytest.raises(RuntimeError, match="programming defect"):
        _execute(VALIDATION, connector)


@pytest.mark.parametrize(
    "validation",
    [
        failure_result(
            ValidationIssue(
                error_type=ErrorType.PERMISSION_DENIED,
                code="SQL_NOT_READ_ONLY",
                public_message="The SQL statement is not permitted.",
            )
        ),
        replace(VALIDATION, is_valid=False),
        replace(VALIDATION, normalized_sql=None),
        replace(VALIDATION, normalized_sql="  "),
        replace(
            VALIDATION,
            issue=ValidationIssue(
                error_type=ErrorType.UNKNOWN,
                code="UNEXPECTED",
                public_message="safe",
            ),
        ),
        replace(VALIDATION, policy_version="old-policy"),
        replace(
            VALIDATION,
            referenced_tables=["public.film"],  # type: ignore[arg-type]
        ),
        replace(
            VALIDATION,
            referenced_columns=(1,),  # type: ignore[arg-type]
        ),
    ],
)
def test_invalid_execution_context_fails_before_connector(
    validation: object,
) -> None:
    connector = Mock()

    with pytest.raises(
        ValueError, match="^execution context is invalid$"
    ):
        _execute(validation, connector)

    connector.execute.assert_not_called()
