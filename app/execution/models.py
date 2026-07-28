from dataclasses import dataclass

from app.connectors.errors import DatabaseError
from app.connectors.models import ExecutionResult


@dataclass(frozen=True, slots=True)
class ExecutionOutcome:
    result: ExecutionResult | None
    error: DatabaseError | None

    def __post_init__(self) -> None:
        if (self.result is None) == (self.error is None):
            raise ValueError(
                "exactly one execution outcome is required"
            )
        if (
            self.result is not None
            and not isinstance(self.result, ExecutionResult)
        ) or (
            self.error is not None
            and not isinstance(self.error, DatabaseError)
        ):
            raise TypeError("execution outcome type is invalid")

    @property
    def is_success(self) -> bool:
        return self.result is not None


def success_outcome(result: ExecutionResult) -> ExecutionOutcome:
    return ExecutionOutcome(result=result, error=None)


def failure_outcome(error: DatabaseError) -> ExecutionOutcome:
    return ExecutionOutcome(result=None, error=error)
