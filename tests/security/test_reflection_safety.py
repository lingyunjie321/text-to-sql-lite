from unittest.mock import Mock

import pytest

from app.connectors.errors import DatabaseError, ErrorType
from app.execution import failure_outcome
from app.reflection import (
    ReflectionRoute,
    decide_reflection,
    record_execution,
    record_validation,
    register_repair_sql,
    start_attempt,
)
from app.validation import ValidationIssue, failure_result, success_result


def _validation_failure(error_type: ErrorType):
    return failure_result(
        ValidationIssue(
            error_type=error_type,
            code=f"SQL_{error_type.value}",
            public_message="safe",
        )
    )


@pytest.mark.parametrize(
    "error_type",
    [
        ErrorType.PERMISSION_DENIED,
        ErrorType.BUSINESS_KNOWLEDGE_MISSING,
        ErrorType.AMBIGUOUS_SEMANTICS,
        ErrorType.RESOURCE_RISK,
        ErrorType.DUPLICATE_SQL,
        ErrorType.UNKNOWN,
    ],
)
def test_validation_hard_errors_cannot_accept_repair(
    error_type: ErrorType,
) -> None:
    history = record_validation(
        start_attempt("SELECT unsafe FROM film"),
        _validation_failure(error_type),
    )

    with pytest.raises(ValueError, match="repair context is invalid"):
        register_repair_sql(
            history,
            "SELECT film_id FROM film",
        )

    assert history.repair_count == 0


@pytest.mark.parametrize(
    "error_type",
    [
        ErrorType.CONNECTION_ERROR,
        ErrorType.TIMEOUT,
        ErrorType.PERMISSION_DENIED,
        ErrorType.RESOURCE_RISK,
    ],
)
def test_database_hard_errors_cannot_accept_repair(
    error_type: ErrorType,
) -> None:
    valid = success_result(
        "SELECT film_id FROM film",
        referenced_tables=("public.film",),
        referenced_columns=("public.film.film_id",),
    )
    history = record_validation(
        start_attempt("SELECT film_id FROM film"),
        valid,
    )
    history = record_execution(
        history,
        failure_outcome(
            DatabaseError(
                sqlstate=None,
                error_type=error_type,
                code=f"DB_{error_type.value}",
                retryable=False,
                public_message="safe",
            )
        ),
    )

    with pytest.raises(ValueError, match="repair context is invalid"):
        register_repair_sql(history, "SELECT title FROM film")

    decision = decide_reflection(error_type, repair_count=0)
    assert decision.route is ReflectionRoute.FINALIZE
    assert decision.should_repair is False


def test_duplicate_candidate_never_calls_validator_or_connector() -> None:
    history = record_validation(
        start_attempt("SELECT missing_a FROM film"),
        _validation_failure(ErrorType.SCHEMA_ERROR),
    )
    accepted = register_repair_sql(
        history,
        "SELECT missing_b FROM film",
    )
    history = record_validation(
        accepted.history,
        _validation_failure(ErrorType.SCHEMA_ERROR),
    )
    validator = Mock()
    connector = Mock()

    duplicate = register_repair_sql(
        history,
        "select missing_a from film;",
    )

    assert duplicate.error_type is ErrorType.DUPLICATE_SQL
    assert duplicate.history.repair_count == 1
    validator.assert_not_called()
    connector.execute.assert_not_called()
