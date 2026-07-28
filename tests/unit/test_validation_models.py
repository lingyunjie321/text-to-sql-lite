from dataclasses import FrozenInstanceError

import pytest

from app.connectors.errors import ErrorType
from app.validation import (
    POLICY_VERSION,
    ValidationIssue,
    ValidationResult,
)
from app.validation.models import failure_result, success_result


def test_validation_contracts_are_immutable() -> None:
    issue = ValidationIssue(
        error_type=ErrorType.PERMISSION_DENIED,
        code="SQL_NOT_READ_ONLY",
        public_message="The SQL statement is not permitted.",
    )
    result = ValidationResult(
        is_valid=False,
        normalized_sql=None,
        referenced_tables=(),
        referenced_columns=(),
        issue=issue,
        policy_version="mvp-v1",
    )

    with pytest.raises(FrozenInstanceError):
        result.is_valid = True  # type: ignore[misc]
    assert isinstance(result.referenced_tables, tuple)
    assert isinstance(result.referenced_columns, tuple)


def test_policy_version_is_explicit() -> None:
    assert POLICY_VERSION == "mvp-v1"


def test_failure_result_contains_no_partial_sql_or_references() -> None:
    issue = ValidationIssue(
        error_type=ErrorType.SYNTAX_ERROR,
        code="SQL_PARSE_ERROR",
        public_message="The SQL statement is invalid.",
    )

    result = failure_result(issue)

    assert result == ValidationResult(
        is_valid=False,
        normalized_sql=None,
        referenced_tables=(),
        referenced_columns=(),
        issue=issue,
        policy_version="mvp-v1",
    )


def test_success_result_sorts_and_deduplicates_references() -> None:
    result = success_result(
        "SELECT film_id FROM film",
        referenced_tables=("public.film", "public.film"),
        referenced_columns=(
            "public.film.film_id",
            "public.film.film_id",
        ),
    )

    assert result.referenced_tables == ("public.film",)
    assert result.referenced_columns == ("public.film.film_id",)
    assert result.issue is None
