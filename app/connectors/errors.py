from dataclasses import dataclass
from enum import Enum

import psycopg
from psycopg_pool import PoolTimeout


class ErrorType(str, Enum):
    SYNTAX_ERROR = "SYNTAX_ERROR"
    SCHEMA_ERROR = "SCHEMA_ERROR"
    DIALECT_ERROR = "DIALECT_ERROR"
    BUSINESS_KNOWLEDGE_MISSING = "BUSINESS_KNOWLEDGE_MISSING"
    AMBIGUOUS_SEMANTICS = "AMBIGUOUS_SEMANTICS"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    CONNECTION_ERROR = "CONNECTION_ERROR"
    TIMEOUT = "TIMEOUT"
    RESOURCE_RISK = "RESOURCE_RISK"
    DUPLICATE_SQL = "DUPLICATE_SQL"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class DatabaseError:
    sqlstate: str | None
    error_type: ErrorType
    code: str
    retryable: bool
    public_message: str


class PostgreSQLConnectorError(RuntimeError):
    def __init__(self, details: DatabaseError) -> None:
        super().__init__(details.public_message)
        self.details = details


_PUBLIC_ERRORS: dict[ErrorType, tuple[str, str]] = {
    ErrorType.SYNTAX_ERROR: (
        "DB_SYNTAX_ERROR",
        "The SQL syntax is invalid.",
    ),
    ErrorType.SCHEMA_ERROR: (
        "DB_SCHEMA_ERROR",
        "The SQL references an invalid database object.",
    ),
    ErrorType.PERMISSION_DENIED: (
        "DB_PERMISSION_DENIED",
        "The database operation is not permitted.",
    ),
    ErrorType.CONNECTION_ERROR: (
        "DB_CONNECTION_ERROR",
        "The database connection failed.",
    ),
    ErrorType.TIMEOUT: (
        "DB_TIMEOUT",
        "The database query timed out.",
    ),
    ErrorType.RESOURCE_RISK: (
        "DB_RESOURCE_RISK",
        "The database rejected the query for resource safety.",
    ),
    ErrorType.UNKNOWN: (
        "DB_UNKNOWN",
        "The database operation failed.",
    ),
}


def classify_sqlstate(sqlstate: str | None) -> ErrorType:
    if sqlstate == "42601":
        return ErrorType.SYNTAX_ERROR
    if sqlstate in {"42P01", "42703", "42702"}:
        return ErrorType.SCHEMA_ERROR
    if sqlstate in {"42501", "25006", "28P01"}:
        return ErrorType.PERMISSION_DENIED
    if sqlstate is not None and sqlstate.startswith("08"):
        return ErrorType.CONNECTION_ERROR
    if sqlstate == "57014":
        return ErrorType.TIMEOUT
    if sqlstate is not None and sqlstate.startswith("53"):
        return ErrorType.RESOURCE_RISK
    return ErrorType.UNKNOWN


def _effective_sqlstate(error: Exception) -> str | None:
    sqlstate = getattr(error, "sqlstate", None)
    if sqlstate is not None or not isinstance(
        error, psycopg.OperationalError
    ):
        return sqlstate

    # libpq doesn't expose the server SQLSTATE for connection-handshake
    # failures. Keep this fallback limited to the canonical authentication
    # response; all established-session errors remain SQLSTATE-driven.
    pgconn = getattr(error, "pgconn", None)
    message = getattr(pgconn, "error_message", b"")
    if isinstance(message, str):
        message = message.encode("utf-8", errors="ignore")
    if b"password authentication failed" in message.lower():
        return "28P01"
    return None


def normalize_database_error(error: Exception) -> PostgreSQLConnectorError:
    if isinstance(error, PostgreSQLConnectorError):
        return error

    sqlstate = _effective_sqlstate(error)
    error_type = classify_sqlstate(sqlstate)
    if isinstance(error, PoolTimeout):
        error_type = ErrorType.CONNECTION_ERROR
    elif isinstance(error, psycopg.OperationalError) and sqlstate is None:
        error_type = ErrorType.CONNECTION_ERROR

    retryable = (
        error_type is ErrorType.CONNECTION_ERROR
        and not isinstance(error, PoolTimeout)
        and (
            (sqlstate is not None and sqlstate.startswith("08"))
            or isinstance(error, psycopg.OperationalError)
        )
    )
    code, public_message = _PUBLIC_ERRORS[error_type]
    return PostgreSQLConnectorError(
        DatabaseError(
            sqlstate=sqlstate,
            error_type=error_type,
            code=code,
            retryable=retryable,
            public_message=public_message,
        )
    )
