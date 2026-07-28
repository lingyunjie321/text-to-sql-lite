from dataclasses import dataclass
from enum import Enum
from string import hexdigits

from app.connectors.errors import DatabaseError, ErrorType
from app.connectors.models import ExecutionResult
from app.reflection.fingerprint import sql_fingerprint
from app.validation import ValidationResult

MAX_REPAIR_COUNT = 3


class RepairStrategy(str, Enum):
    MINIMAL_SQL_REPAIR = "MINIMAL_SQL_REPAIR"
    RELINK_SCHEMA = "RELINK_SCHEMA"
    REGENERATE_POSTGRES = "REGENERATE_POSTGRES"


class ReflectionRoute(str, Enum):
    GENERATE_SQL = "GENERATE_SQL"
    SCHEMA_LINKING = "SCHEMA_LINKING"
    CLARIFICATION = "CLARIFICATION"
    FINALIZE = "FINALIZE"


class RepairRegistrationStatus(str, Enum):
    ACCEPTED = "ACCEPTED"
    DUPLICATE = "DUPLICATE"
    EXHAUSTED = "EXHAUSTED"


@dataclass(frozen=True, slots=True)
class SQLAttempt:
    attempt_number: int
    sql: str
    fingerprint: str
    validation_result: ValidationResult | None = None
    execution_result: ExecutionResult | None = None
    database_error: DatabaseError | None = None

    def __post_init__(self) -> None:
        if (
            type(self.attempt_number) is not int
            or self.attempt_number < 0
            or not isinstance(self.sql, str)
            or not self.sql.strip()
            or len(self.fingerprint) != 64
            or any(
                character not in hexdigits
                for character in self.fingerprint
            )
            or self.fingerprint != sql_fingerprint(self.sql)
            or (
                self.validation_result is not None
                and not isinstance(
                    self.validation_result,
                    ValidationResult,
                )
            )
            or (
                self.execution_result is not None
                and not isinstance(
                    self.execution_result,
                    ExecutionResult,
                )
            )
            or (
                self.database_error is not None
                and not isinstance(self.database_error, DatabaseError)
            )
            or (
                self.execution_result is not None
                and self.database_error is not None
            )
            or (
                (
                    self.execution_result is not None
                    or self.database_error is not None
                )
                and (
                    self.validation_result is None
                    or self.validation_result.is_valid is not True
                )
            )
        ):
            raise ValueError("SQL attempt is invalid")

    @property
    def current_error_type(self) -> ErrorType | None:
        if self.database_error is not None:
            return self.database_error.error_type
        if (
            self.validation_result is not None
            and self.validation_result.issue is not None
        ):
            return self.validation_result.issue.error_type
        return None

    @property
    def is_success(self) -> bool:
        return self.execution_result is not None


@dataclass(frozen=True, slots=True)
class AttemptHistory:
    attempts: tuple[SQLAttempt, ...]
    seen_sql_fingerprints: frozenset[str]
    repair_count: int

    def __post_init__(self) -> None:
        if (
            not isinstance(self.attempts, tuple)
            or not isinstance(self.seen_sql_fingerprints, frozenset)
        ):
            raise ValueError("attempt history is invalid")
        fingerprints = tuple(
            attempt.fingerprint for attempt in self.attempts
        )
        if (
            not self.attempts
            or not all(
                isinstance(attempt, SQLAttempt)
                for attempt in self.attempts
            )
            or tuple(
                attempt.attempt_number for attempt in self.attempts
            )
            != tuple(range(len(self.attempts)))
            or len(set(fingerprints)) != len(fingerprints)
            or self.seen_sql_fingerprints != frozenset(fingerprints)
            or type(self.repair_count) is not int
            or self.repair_count != len(self.attempts) - 1
            or not 0 <= self.repair_count <= MAX_REPAIR_COUNT
        ):
            raise ValueError("attempt history is invalid")

    @property
    def current_attempt(self) -> SQLAttempt:
        return self.attempts[-1]


@dataclass(frozen=True, slots=True)
class RepairRegistration:
    status: RepairRegistrationStatus
    history: AttemptHistory
    attempt: SQLAttempt | None

    def __post_init__(self) -> None:
        accepted = self.status is RepairRegistrationStatus.ACCEPTED
        if (
            not isinstance(self.status, RepairRegistrationStatus)
            or not isinstance(self.history, AttemptHistory)
            or (self.attempt is not None) is not accepted
            or (
                accepted
                and self.attempt is not self.history.current_attempt
            )
        ):
            raise ValueError("repair registration is invalid")

    @property
    def error_type(self) -> ErrorType | None:
        if self.status is RepairRegistrationStatus.DUPLICATE:
            return ErrorType.DUPLICATE_SQL
        return None


@dataclass(frozen=True, slots=True)
class ReflectionDecision:
    error_type: ErrorType
    route: ReflectionRoute
    strategy: RepairStrategy | None
    code: str

    def __post_init__(self) -> None:
        repair_contexts = {
            RepairStrategy.MINIMAL_SQL_REPAIR: (
                ErrorType.SYNTAX_ERROR,
                ReflectionRoute.GENERATE_SQL,
                "REFLECT_SYNTAX_REPAIR",
            ),
            RepairStrategy.RELINK_SCHEMA: (
                ErrorType.SCHEMA_ERROR,
                ReflectionRoute.SCHEMA_LINKING,
                "REFLECT_SCHEMA_RELINK",
            ),
            RepairStrategy.REGENERATE_POSTGRES: (
                ErrorType.DIALECT_ERROR,
                ReflectionRoute.GENERATE_SQL,
                "REFLECT_DIALECT_REGENERATE",
            ),
        }
        if (
            not isinstance(self.error_type, ErrorType)
            or not isinstance(self.route, ReflectionRoute)
            or (
                self.strategy is not None
                and not isinstance(self.strategy, RepairStrategy)
            )
            or not isinstance(self.code, str)
            or not self.code.strip()
            or (
                self.strategy is not None
                and repair_contexts.get(self.strategy)
                != (self.error_type, self.route, self.code)
            )
        ):
            raise ValueError("reflection decision is invalid")

    @property
    def should_repair(self) -> bool:
        return self.strategy is not None
