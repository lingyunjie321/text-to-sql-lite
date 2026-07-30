import math
from typing import Protocol

from app.connectors.errors import PostgreSQLConnectorError
from app.connectors.metadata import SchemaSnapshot
from app.connectors.models import ExecutionResult
from app.execution.models import (
    ExecutionOutcome,
    failure_outcome,
    success_outcome,
)
from app.validation import (
    POLICY_VERSION,
    ValidationResult,
    validate_sql,
)


class SQLExecutor(Protocol):
    def execute(
        self,
        sql: str,
        *,
        timeout_seconds: float | None = None,
    ) -> ExecutionResult: ...


def _validate_execution_context(
    validation_result: ValidationResult,
) -> str:
    if (
        not isinstance(validation_result, ValidationResult)
        or validation_result.is_valid is not True
        or validation_result.policy_version != POLICY_VERSION
        or not isinstance(validation_result.normalized_sql, str)
        or not validation_result.normalized_sql.strip()
        or validation_result.issue is not None
        or not isinstance(validation_result.referenced_tables, tuple)
        or not all(
            isinstance(table, str)
            for table in validation_result.referenced_tables
        )
        or not isinstance(validation_result.referenced_columns, tuple)
        or not all(
            isinstance(column, str)
            for column in validation_result.referenced_columns
        )
    ):
        raise ValueError("execution context is invalid")
    return validation_result.normalized_sql


def execute_validated_sql(
    validation_result: ValidationResult,
    *,
    allowed_schemas: tuple[str, ...],
    allowed_tables: tuple[str, ...],
    snapshot: SchemaSnapshot,
    connector: SQLExecutor,
    timeout_seconds: float | None = None,
) -> ExecutionOutcome:
    if (
        timeout_seconds is not None
        and (
            type(timeout_seconds) not in (int, float)
            or not math.isfinite(float(timeout_seconds))
            or timeout_seconds <= 0
        )
    ):
        raise ValueError("execution context is invalid")
    normalized_sql = _validate_execution_context(validation_result)
    verified_result = validate_sql(
        normalized_sql,
        allowed_schemas=allowed_schemas,
        allowed_tables=allowed_tables,
        snapshot=snapshot,
    )
    if verified_result != validation_result:
        raise ValueError("execution context is invalid")
    try:
        result = (
            connector.execute(normalized_sql)
            if timeout_seconds is None
            else connector.execute(
                normalized_sql,
                timeout_seconds=float(timeout_seconds),
            )
        )
        return success_outcome(result)
    except PostgreSQLConnectorError as error:
        return failure_outcome(error.details)
