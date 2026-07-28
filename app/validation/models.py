from dataclasses import dataclass

from app.connectors.errors import ErrorType


POLICY_VERSION = "mvp-v1"


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    error_type: ErrorType
    code: str
    public_message: str


@dataclass(frozen=True, slots=True)
class ValidationResult:
    is_valid: bool
    normalized_sql: str | None
    referenced_tables: tuple[str, ...]
    referenced_columns: tuple[str, ...]
    issue: ValidationIssue | None
    policy_version: str


def failure_result(issue: ValidationIssue) -> ValidationResult:
    return ValidationResult(
        is_valid=False,
        normalized_sql=None,
        referenced_tables=(),
        referenced_columns=(),
        issue=issue,
        policy_version=POLICY_VERSION,
    )


def success_result(
    normalized_sql: str,
    *,
    referenced_tables: tuple[str, ...],
    referenced_columns: tuple[str, ...],
) -> ValidationResult:
    return ValidationResult(
        is_valid=True,
        normalized_sql=normalized_sql,
        referenced_tables=tuple(sorted(set(referenced_tables))),
        referenced_columns=tuple(sorted(set(referenced_columns))),
        issue=None,
        policy_version=POLICY_VERSION,
    )
