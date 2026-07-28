from dataclasses import replace

from app.connectors.errors import ErrorType
from app.execution import ExecutionOutcome
from app.reflection.fingerprint import sql_fingerprint
from app.reflection.models import (
    MAX_REPAIR_COUNT,
    AttemptHistory,
    ReflectionDecision,
    ReflectionRoute,
    RepairRegistration,
    RepairRegistrationStatus,
    RepairStrategy,
    SQLAttempt,
)
from app.validation import POLICY_VERSION, ValidationIssue, ValidationResult

_REPAIRABLE_ERRORS = frozenset(
    {
        ErrorType.SYNTAX_ERROR,
        ErrorType.SCHEMA_ERROR,
        ErrorType.DIALECT_ERROR,
    }
)


def _replace_current_attempt(
    history: AttemptHistory,
    attempt: SQLAttempt,
) -> AttemptHistory:
    return AttemptHistory(
        attempts=(*history.attempts[:-1], attempt),
        seen_sql_fingerprints=history.seen_sql_fingerprints,
        repair_count=history.repair_count,
    )


def start_attempt(sql: str) -> AttemptHistory:
    attempt = SQLAttempt(
        attempt_number=0,
        sql=sql,
        fingerprint=sql_fingerprint(sql),
    )
    return AttemptHistory(
        attempts=(attempt,),
        seen_sql_fingerprints=frozenset({attempt.fingerprint}),
        repair_count=0,
    )


def record_validation(
    history: AttemptHistory,
    validation_result: ValidationResult,
) -> AttemptHistory:
    current = history.current_attempt
    if current.validation_result is not None:
        raise ValueError("attempt validation is already recorded")
    if not isinstance(validation_result, ValidationResult):
        raise ValueError("attempt validation context is invalid")
    is_valid_result = (
        type(validation_result.is_valid) is bool
        and validation_result.policy_version == POLICY_VERSION
        and isinstance(validation_result.referenced_tables, tuple)
        and all(
            isinstance(table, str)
            for table in validation_result.referenced_tables
        )
        and isinstance(validation_result.referenced_columns, tuple)
        and all(
            isinstance(column, str)
            for column in validation_result.referenced_columns
        )
    )
    if validation_result.is_valid is True:
        is_valid_result = (
            is_valid_result
            and isinstance(validation_result.normalized_sql, str)
            and bool(validation_result.normalized_sql.strip())
            and validation_result.issue is None
            and sql_fingerprint(validation_result.normalized_sql)
            == current.fingerprint
        )
    else:
        is_valid_result = (
            is_valid_result
            and validation_result.normalized_sql is None
            and isinstance(validation_result.issue, ValidationIssue)
            and validation_result.referenced_tables == ()
            and validation_result.referenced_columns == ()
        )
    if not is_valid_result:
        raise ValueError("attempt validation context is invalid")
    return _replace_current_attempt(
        history,
        replace(current, validation_result=validation_result),
    )


def record_execution(
    history: AttemptHistory,
    outcome: ExecutionOutcome,
) -> AttemptHistory:
    current = history.current_attempt
    if (
        current.execution_result is not None
        or current.database_error is not None
    ):
        raise ValueError("attempt execution is already recorded")
    if (
        not isinstance(outcome, ExecutionOutcome)
        or current.validation_result is None
        or current.validation_result.is_valid is not True
    ):
        raise ValueError("attempt execution context is invalid")
    return _replace_current_attempt(
        history,
        replace(
            current,
            execution_result=outcome.result,
            database_error=outcome.error,
        ),
    )


def register_repair_sql(
    history: AttemptHistory,
    sql: str,
) -> RepairRegistration:
    if history.current_attempt.current_error_type not in _REPAIRABLE_ERRORS:
        raise ValueError("repair context is invalid")

    fingerprint = sql_fingerprint(sql)
    if fingerprint in history.seen_sql_fingerprints:
        return RepairRegistration(
            status=RepairRegistrationStatus.DUPLICATE,
            history=history,
            attempt=None,
        )
    if history.repair_count >= MAX_REPAIR_COUNT:
        return RepairRegistration(
            status=RepairRegistrationStatus.EXHAUSTED,
            history=history,
            attempt=None,
        )

    attempt = SQLAttempt(
        attempt_number=len(history.attempts),
        sql=sql,
        fingerprint=fingerprint,
    )
    updated = AttemptHistory(
        attempts=(*history.attempts, attempt),
        seen_sql_fingerprints=(
            history.seen_sql_fingerprints | {fingerprint}
        ),
        repair_count=history.repair_count + 1,
    )
    return RepairRegistration(
        status=RepairRegistrationStatus.ACCEPTED,
        history=updated,
        attempt=attempt,
    )


def decide_reflection(
    error_type: ErrorType,
    *,
    repair_count: int,
    can_reduce_resource: bool = False,
) -> ReflectionDecision:
    if (
        not isinstance(error_type, ErrorType)
        or type(repair_count) is not int
        or not 0 <= repair_count <= MAX_REPAIR_COUNT
        or type(can_reduce_resource) is not bool
    ):
        raise ValueError("reflection context is invalid")

    if (
        error_type in _REPAIRABLE_ERRORS
        and repair_count >= MAX_REPAIR_COUNT
    ):
        return ReflectionDecision(
            error_type=error_type,
            route=ReflectionRoute.FINALIZE,
            strategy=None,
            code="REFLECT_REPAIR_EXHAUSTED",
        )

    repair_routes = {
        ErrorType.SYNTAX_ERROR: (
            ReflectionRoute.GENERATE_SQL,
            RepairStrategy.MINIMAL_SQL_REPAIR,
            "REFLECT_SYNTAX_REPAIR",
        ),
        ErrorType.SCHEMA_ERROR: (
            ReflectionRoute.SCHEMA_LINKING,
            RepairStrategy.RELINK_SCHEMA,
            "REFLECT_SCHEMA_RELINK",
        ),
        ErrorType.DIALECT_ERROR: (
            ReflectionRoute.GENERATE_SQL,
            RepairStrategy.REGENERATE_POSTGRES,
            "REFLECT_DIALECT_REGENERATE",
        ),
    }
    if error_type in repair_routes:
        route, strategy, code = repair_routes[error_type]
        return ReflectionDecision(
            error_type=error_type,
            route=route,
            strategy=strategy,
            code=code,
        )

    if error_type in {
        ErrorType.BUSINESS_KNOWLEDGE_MISSING,
        ErrorType.AMBIGUOUS_SEMANTICS,
    }:
        return ReflectionDecision(
            error_type=error_type,
            route=ReflectionRoute.CLARIFICATION,
            strategy=None,
            code="REFLECT_CLARIFICATION",
        )

    if error_type is ErrorType.RESOURCE_RISK:
        return ReflectionDecision(
            error_type=error_type,
            route=(
                ReflectionRoute.CLARIFICATION
                if can_reduce_resource
                else ReflectionRoute.FINALIZE
            ),
            strategy=None,
            code=(
                "REFLECT_RESOURCE_CLARIFICATION"
                if can_reduce_resource
                else "REFLECT_RESOURCE_RISK"
            ),
        )

    return ReflectionDecision(
        error_type=error_type,
        route=ReflectionRoute.FINALIZE,
        strategy=None,
        code="REFLECT_NON_REPAIRABLE",
    )
