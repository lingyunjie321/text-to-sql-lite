from dataclasses import FrozenInstanceError, replace

import pytest

from app.connectors.errors import DatabaseError, ErrorType
from app.connectors.models import ExecutionResult
from app.execution import failure_outcome, success_outcome
from app.reflection import (
    AttemptHistory,
    RepairRegistration,
    RepairRegistrationStatus,
    SQLAttempt,
    record_execution,
    record_validation,
    register_repair_sql,
    sql_fingerprint,
    start_attempt,
)
from app.validation import ValidationIssue, failure_result, success_result


def _issue(error_type: ErrorType) -> ValidationIssue:
    return ValidationIssue(
        error_type=error_type,
        code=f"SQL_{error_type.value}",
        public_message="safe",
    )


def _failure(error_type: ErrorType):
    return failure_result(_issue(error_type))


RESULT = ExecutionResult(
    columns=(),
    rows=[],
    returned_row_count=0,
    truncated=False,
    execution_time_ms=0.1,
)
VALID = success_result(
    "SELECT film_id FROM film",
    referenced_tables=("public.film",),
    referenced_columns=("public.film.film_id",),
)
DB_ERROR = DatabaseError(
    sqlstate="42P01",
    error_type=ErrorType.SCHEMA_ERROR,
    code="DB_SCHEMA_ERROR",
    retryable=False,
    public_message="safe",
)


def test_initial_attempt_has_zero_repair_count() -> None:
    history = start_attempt("SELECT film_id FROM film")

    assert history.repair_count == 0
    assert len(history.attempts) == 1
    assert history.current_attempt.attempt_number == 0
    assert history.current_attempt.sql == "SELECT film_id FROM film"
    assert history.seen_sql_fingerprints == frozenset(
        {sql_fingerprint("SELECT film_id FROM film")}
    )


def test_history_and_attempt_are_immutable() -> None:
    history = start_attempt("SELECT film_id FROM film")

    with pytest.raises(FrozenInstanceError):
        history.repair_count = 1  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        history.current_attempt.sql = "SELECT title FROM film"  # type: ignore[misc]


def test_records_validation_then_successful_execution() -> None:
    history = start_attempt("SELECT film_id FROM film")
    history = record_validation(history, VALID)
    history = record_execution(history, success_outcome(RESULT))

    assert history.current_attempt.validation_result is VALID
    assert history.current_attempt.execution_result is RESULT
    assert history.current_attempt.database_error is None
    assert history.current_attempt.is_success is True


def test_records_sanitized_database_error() -> None:
    history = record_validation(
        start_attempt("SELECT film_id FROM film"),
        VALID,
    )

    history = record_execution(
        history,
        failure_outcome(DB_ERROR),
    )

    assert history.current_attempt.execution_result is None
    assert history.current_attempt.database_error is DB_ERROR
    assert (
        history.current_attempt.current_error_type
        is ErrorType.SCHEMA_ERROR
    )


def test_execution_requires_one_successful_validation() -> None:
    with pytest.raises(
        ValueError, match="attempt execution context is invalid"
    ):
        record_execution(
            start_attempt("SELECT film_id FROM film"),
            success_outcome(RESULT),
        )

    failed = record_validation(
        start_attempt("SELECT broken FROM film"),
        _failure(ErrorType.SCHEMA_ERROR),
    )
    with pytest.raises(
        ValueError, match="attempt execution context is invalid"
    ):
        record_execution(failed, success_outcome(RESULT))


def test_attempt_result_can_only_be_recorded_once() -> None:
    history = record_validation(
        start_attempt("SELECT film_id FROM film"),
        VALID,
    )
    with pytest.raises(
        ValueError, match="attempt validation is already recorded"
    ):
        record_validation(history, VALID)

    executed = record_execution(history, success_outcome(RESULT))
    with pytest.raises(
        ValueError, match="attempt execution is already recorded"
    ):
        record_execution(executed, success_outcome(RESULT))


def test_successful_validation_must_match_current_sql_and_policy() -> None:
    history = start_attempt("SELECT film_id FROM film")
    wrong_sql = success_result(
        "SELECT title FROM film",
        referenced_tables=("public.film",),
        referenced_columns=("public.film.title",),
    )

    with pytest.raises(
        ValueError, match="attempt validation context is invalid"
    ):
        record_validation(history, wrong_sql)
    with pytest.raises(
        ValueError, match="attempt validation context is invalid"
    ):
        record_validation(
            history,
            replace(VALID, policy_version="old-policy"),
        )


def test_repair_requires_repairable_current_error() -> None:
    history = start_attempt("SELECT film_id FROM film")

    with pytest.raises(
        ValueError, match="repair context is invalid"
    ):
        register_repair_sql(history, "SELECT title FROM film")

    denied = record_validation(
        history,
        _failure(ErrorType.PERMISSION_DENIED),
    )
    with pytest.raises(
        ValueError, match="repair context is invalid"
    ):
        register_repair_sql(denied, "SELECT title FROM film")


def test_only_distinct_accepted_repairs_increment_count() -> None:
    history = record_validation(
        start_attempt("SELECT missing_a FROM film"),
        _failure(ErrorType.SCHEMA_ERROR),
    )
    accepted = register_repair_sql(
        history,
        "SELECT missing_b FROM film",
    )

    assert accepted.status is RepairRegistrationStatus.ACCEPTED
    assert accepted.attempt is accepted.history.current_attempt
    assert accepted.history.repair_count == 1

    failed_b = record_validation(
        accepted.history,
        _failure(ErrorType.SCHEMA_ERROR),
    )
    duplicate = register_repair_sql(
        failed_b,
        "  select missing_a from film; ",
    )

    assert duplicate.status is RepairRegistrationStatus.DUPLICATE
    assert duplicate.attempt is None
    assert duplicate.history is failed_b
    assert duplicate.history.repair_count == 1
    assert duplicate.error_type is ErrorType.DUPLICATE_SQL


def test_accepts_at_most_three_repairs() -> None:
    history = record_validation(
        start_attempt("SELECT missing_0 FROM film"),
        _failure(ErrorType.SCHEMA_ERROR),
    )
    for number in range(1, 4):
        registration = register_repair_sql(
            history,
            f"SELECT missing_{number} FROM film",
        )
        assert registration.status is RepairRegistrationStatus.ACCEPTED
        history = record_validation(
            registration.history,
            _failure(ErrorType.SCHEMA_ERROR),
        )

    exhausted = register_repair_sql(
        history,
        "SELECT missing_4 FROM film",
    )

    assert history.repair_count == 3
    assert len(history.attempts) == 4
    assert exhausted.status is RepairRegistrationStatus.EXHAUSTED
    assert exhausted.attempt is None
    assert exhausted.history is history
    assert exhausted.error_type is None


def test_history_rejects_inconsistent_manual_construction() -> None:
    attempt = SQLAttempt(
        attempt_number=0,
        sql="SELECT 1",
        fingerprint=sql_fingerprint("SELECT 1"),
    )

    with pytest.raises(ValueError, match="attempt history is invalid"):
        AttemptHistory(
            attempts=(attempt,),
            seen_sql_fingerprints=frozenset(),
            repair_count=0,
        )


def test_history_rejects_mutable_container_aliases() -> None:
    attempt = SQLAttempt(
        attempt_number=0,
        sql="SELECT 1",
        fingerprint=sql_fingerprint("SELECT 1"),
    )

    with pytest.raises(ValueError, match="attempt history is invalid"):
        AttemptHistory(  # type: ignore[arg-type]
            attempts=[attempt],
            seen_sql_fingerprints=frozenset({attempt.fingerprint}),
            repair_count=0,
        )
    with pytest.raises(ValueError, match="attempt history is invalid"):
        AttemptHistory(  # type: ignore[arg-type]
            attempts=(attempt,),
            seen_sql_fingerprints={attempt.fingerprint},
            repair_count=0,
        )


def test_repair_registration_rejects_unknown_status() -> None:
    history = start_attempt("SELECT 1")

    with pytest.raises(ValueError, match="repair registration is invalid"):
        RepairRegistration(  # type: ignore[arg-type]
            status="garbage",
            history=history,
            attempt=None,
        )
