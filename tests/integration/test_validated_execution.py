from unittest.mock import Mock

import pytest

from app.connectors.errors import ErrorType
from app.connectors.metadata import SchemaSnapshot
from app.connectors.postgresql import PostgreSQLConnector
from app.execution import execute_validated_sql
from app.validation import ValidationResult, validate_sql


def _validate(
    connector: PostgreSQLConnector,
    sql: str,
    *,
    allowed_tables: tuple[str, ...],
) -> tuple[ValidationResult, SchemaSnapshot]:
    snapshot = connector.read_metadata(("public",), allowed_tables)
    return (
        validate_sql(
            sql,
            allowed_schemas=("public",),
            allowed_tables=allowed_tables,
            snapshot=snapshot,
        ),
        snapshot,
    )


@pytest.mark.integration
@pytest.mark.parametrize(
    ("sql", "expected"),
    [
        (
            "SELECT film_id, title FROM film "
            "ORDER BY film_id LIMIT 3",
            [[1, "ACADEMY DINOSAUR"], [2, "ACE GOLDFINGER"],
             [3, "ADAPTATION HOLES"]],
        ),
        (
            "WITH selected AS ("
            "SELECT film_id FROM film WHERE film_id <= 2"
            ") SELECT COUNT(*) AS total FROM selected",
            [[2]],
        ),
        (
            "SELECT film_id FROM film WHERE film_id < 0",
            [],
        ),
    ],
)
def test_validated_pagila_query_executes(
    connector: PostgreSQLConnector,
    sql: str,
    expected: list[list[object]],
) -> None:
    allowed_tables = ("public.film",)
    validation, snapshot = _validate(
        connector,
        sql,
        allowed_tables=allowed_tables,
    )

    outcome = execute_validated_sql(
        validation,
        allowed_schemas=("public",),
        allowed_tables=allowed_tables,
        snapshot=snapshot,
        connector=connector,
    )

    assert validation.is_valid is True
    assert outcome.error is None
    assert outcome.result is not None
    assert outcome.result.rows == expected
    assert outcome.result.truncated is False


@pytest.mark.integration
def test_validated_execution_preserves_truncation(
    connector: PostgreSQLConnector,
) -> None:
    allowed_tables = ("public.rental",)
    validation, snapshot = _validate(
        connector,
        "SELECT rental_id FROM rental ORDER BY rental_id",
        allowed_tables=allowed_tables,
    )

    outcome = execute_validated_sql(
        validation,
        allowed_schemas=("public",),
        allowed_tables=allowed_tables,
        snapshot=snapshot,
        connector=connector,
    )

    assert outcome.result is not None
    assert outcome.result.returned_row_count == 1000
    assert len(outcome.result.rows) == 1000
    assert outcome.result.truncated is True


@pytest.mark.integration
def test_validator_rejection_has_zero_execution_calls(
    connector: PostgreSQLConnector,
) -> None:
    allowed_tables = ("public.film",)
    validation, snapshot = _validate(
        connector,
        "DELETE FROM film",
        allowed_tables=allowed_tables,
    )
    guarded_connector = Mock(wraps=connector)

    with pytest.raises(ValueError):
        execute_validated_sql(
            validation,
            allowed_schemas=("public",),
            allowed_tables=allowed_tables,
            snapshot=snapshot,
            connector=guarded_connector,
        )

    guarded_connector.execute.assert_not_called()


@pytest.mark.integration
def test_runtime_database_error_is_sanitized(
    connector: PostgreSQLConnector,
) -> None:
    allowed_tables = ("public.film",)
    validation, snapshot = _validate(
        connector,
        "SELECT 1 / 0 AS quotient",
        allowed_tables=allowed_tables,
    )

    outcome = execute_validated_sql(
        validation,
        allowed_schemas=("public",),
        allowed_tables=allowed_tables,
        snapshot=snapshot,
        connector=connector,
    )

    assert validation.is_valid is True
    assert outcome.result is None
    assert outcome.error is not None
    assert outcome.error.error_type is ErrorType.UNKNOWN
    assert outcome.error.code == "DB_UNKNOWN"
    assert "division" not in outcome.error.public_message.lower()
