from dataclasses import FrozenInstanceError

import pytest

from app.connectors.errors import DatabaseError, ErrorType
from app.connectors.models import ExecutionResult
from app.execution import (
    ExecutionOutcome,
    failure_outcome,
    success_outcome,
)


RESULT = ExecutionResult(
    columns=(),
    rows=[],
    returned_row_count=0,
    truncated=False,
    execution_time_ms=0.1,
)
ERROR = DatabaseError(
    sqlstate="57014",
    error_type=ErrorType.TIMEOUT,
    code="DB_TIMEOUT",
    retryable=False,
    public_message="The database query timed out.",
)


def test_success_outcome_contains_only_result() -> None:
    outcome = success_outcome(RESULT)

    assert outcome == ExecutionOutcome(result=RESULT, error=None)
    assert outcome.is_success is True


def test_failure_outcome_contains_only_error() -> None:
    outcome = failure_outcome(ERROR)

    assert outcome == ExecutionOutcome(result=None, error=ERROR)
    assert outcome.is_success is False


@pytest.mark.parametrize(
    ("result", "error"),
    [
        (None, None),
        (RESULT, ERROR),
    ],
)
def test_outcome_requires_exactly_one_value(
    result: ExecutionResult | None,
    error: DatabaseError | None,
) -> None:
    with pytest.raises(
        ValueError, match="exactly one execution outcome is required"
    ):
        ExecutionOutcome(result=result, error=error)


@pytest.mark.parametrize(
    ("result", "error"),
    [
        ("not a result", None),
        (None, "not an error"),
    ],
)
def test_outcome_rejects_wrong_runtime_types(
    result: object,
    error: object,
) -> None:
    with pytest.raises(TypeError, match="execution outcome type is invalid"):
        ExecutionOutcome(  # type: ignore[arg-type]
            result=result,
            error=error,
        )


def test_outcome_is_immutable() -> None:
    outcome = success_outcome(RESULT)

    with pytest.raises(FrozenInstanceError):
        outcome.result = None  # type: ignore[misc]
