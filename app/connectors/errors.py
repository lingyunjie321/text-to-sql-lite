"""连接器错误模型与驱动异常规范化。

把 psycopg（PostgreSQL）与 pymysql（MySQL / StarRocks）抛出的驱动
异常统一转换为 :class:`DatabaseConnectorError`：按 SQLSTATE 或 MySQL
错误码分类为稳定的 :class:`ErrorType`，并附带可对外展示的安全消息
（不泄露 DSN、密码等敏感信息）。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

import psycopg
from psycopg_pool import PoolTimeout

if TYPE_CHECKING:
    import pymysql


class ErrorType(str, Enum):
    """稳定的错误分类，贯穿连接器、校验与工作流各层。

    取值与具体数据库无关，供 API 层映射为对外的错误类型。
    """

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
    """单次数库错误的结构化细节。

    ``sqlstate`` 为原始 SQLSTATE（MySQL 为 ``MY-<errno>`` 形式）；
    ``code`` 为对外的稳定错误码；``retryable`` 标记是否值得重试；
    ``public_message`` 为可安全对外展示的消息。
    """

    sqlstate: str | None
    error_type: ErrorType
    code: str
    retryable: bool
    public_message: str


class DatabaseConnectorError(RuntimeError):
    """Generic database connector error used across all backends."""

    def __init__(self, details: DatabaseError) -> None:
        super().__init__(details.public_message)
        self.details = details


# Backward-compatible alias for existing code that references
# PostgreSQLConnectorError directly.
PostgreSQLConnectorError = DatabaseConnectorError


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


# ── PostgreSQL SQLSTATE classification ──────────────────────────


def classify_sqlstate(sqlstate: str | None) -> ErrorType:
    """Classify a PostgreSQL SQLSTATE into a generic ErrorType."""
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


# ── MySQL error-code classification ─────────────────────────────
# Reference: https://dev.mysql.com/doc/refman/8.0/en/error-reference.html


# MySQL server error codes mapped to ErrorType categories.
# Values are (error_code_range_start, error_code_range_end).
_MYSQL_ERROR_RANGES: dict[ErrorType, list[tuple[int, int]]] = {
    ErrorType.SYNTAX_ERROR: [
        (1064, 1065),  # ER_PARSE_ERROR, ER_EMPTY_QUERY
        (1149, 1149),  # ER_SYNTAX_ERROR
    ],
    ErrorType.SCHEMA_ERROR: [
        (1049, 1051),  # Unknown DB, table exists, unknown table
        (1054, 1054),  # ER_BAD_FIELD_ERROR
        (1146, 1146),  # ER_NO_SUCH_TABLE
    ],
    ErrorType.PERMISSION_DENIED: [
        (1044, 1045),  # ER_DBACCESS_DENIED_ERROR, ER_ACCESS_DENIED_ERROR
        (1142, 1143),  # ER_TABLEACCESS_DENIED_ERROR, ER_COLUMNACCESS_DENIED_ERROR
        (1227, 1227),  # ER_SPECIFIC_ACCESS_DENIED_ERROR
    ],
    ErrorType.CONNECTION_ERROR: [
        (2001, 2018),  # CR_SOCKET_CREATE_ERROR … CR_TCP_CONNECTION
        (2026, 2026),  # CR_SSL_CONNECTION_ERROR
        (2047, 2054),  # Various connection errors
    ],
    ErrorType.TIMEOUT: [
        (3024, 3024),  # ER_QUERY_TIMEOUT
        (2006, 2006),  # CR_SERVER_GONE_ERROR (can be timeout)
        (2013, 2013),  # CR_SERVER_LOST (can be timeout)
        (2062, 2062),  # ER_WARN_EXEC_TIME_EXCEEDED
    ],
    ErrorType.RESOURCE_RISK: [
        (1041, 1041),  # ER_OUT_OF_RESOURCES
    ],
}


def classify_mysql_error_code(error_code: int) -> ErrorType:
    """Classify a MySQL server error code into a generic ErrorType."""
    for error_type, ranges in _MYSQL_ERROR_RANGES.items():
        for low, high in ranges:
            if low <= error_code <= high:
                return error_type
    return ErrorType.UNKNOWN


# ── Error normalisation ─────────────────────────────────────────


def _effective_sqlstate_pg(error: Exception) -> str | None:
    """Extract a PostgreSQL SQLSTATE from *error*, with a fallback for
    auth failures that happen during the libpq handshake (which doesn't
    expose the server-side SQLSTATE)."""
    sqlstate = getattr(error, "sqlstate", None)
    if sqlstate is not None or not isinstance(
        error, psycopg.OperationalError
    ):
        return sqlstate

    pgconn = getattr(error, "pgconn", None)
    message = getattr(pgconn, "error_message", b"")
    if isinstance(message, str):
        message = message.encode("utf-8", errors="ignore")
    if b"password authentication failed" in message.lower():
        return "28P01"
    return None


def _effective_sqlstate_mysql(error: Exception) -> str | None:
    """Extract a MySQL error code from *error* and convert to a
    SQLSTATE-like string."""
    errno = getattr(error, "args", None)
    if isinstance(errno, tuple) and len(errno) >= 1:
        code = errno[0]
        if isinstance(code, int):
            return f"MY-{code:05d}"
    return None


def normalize_database_error(
    error: Exception,
) -> DatabaseConnectorError:
    """Normalize any database driver exception into a
    :class:`DatabaseConnectorError`.

    Handles psycopg (PostgreSQL) and pymysql (MySQL / StarRocks)
    driver exceptions.  Falls back to classifying by ``sqlstate``
    attribute for generic errors (useful in tests).
    """
    if isinstance(error, DatabaseConnectorError):
        return error

    # ── psycopg / PostgreSQL path ────────────────────────────
    if isinstance(error, psycopg.Error):
        return _normalize_psycopg_error(error)

    # ── pymysql / MySQL path ─────────────────────────────────
    if _is_pymysql_error(error):
        return _normalize_pymysql_error(error)

    # ── Generic error with sqlstate-like attribute ───────────
    # (e.g. FakeDatabaseError in tests)
    sqlstate = _effective_sqlstate_pg(error)
    if sqlstate is not None:
        return _build_error(sqlstate)

    mysql_state = _effective_sqlstate_mysql(error)
    if mysql_state is not None:
        return _build_error(mysql_state)

    # ── True unknown / connection error fallback ─────────────
    return DatabaseConnectorError(
        DatabaseError(
            sqlstate=None,
            error_type=ErrorType.CONNECTION_ERROR,
            code="DB_CONNECTION_ERROR",
            retryable=True,
            public_message="The database connection failed.",
        )
    )


def _build_error(sqlstate: str | None) -> DatabaseConnectorError:
    """Build a :class:`DatabaseConnectorError` from a SQLSTATE string."""
    error_type = classify_sqlstate(sqlstate)
    retryable = (
        error_type is ErrorType.CONNECTION_ERROR
        and sqlstate is not None
        and sqlstate.startswith("08")
    )
    code, public_message = _PUBLIC_ERRORS[error_type]
    return DatabaseConnectorError(
        DatabaseError(
            sqlstate=sqlstate,
            error_type=error_type,
            code=code,
            retryable=retryable,
            public_message=public_message,
        )
    )


def _normalize_psycopg_error(error: Exception) -> DatabaseConnectorError:
    sqlstate = _effective_sqlstate_pg(error)
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
    return DatabaseConnectorError(
        DatabaseError(
            sqlstate=sqlstate,
            error_type=error_type,
            code=code,
            retryable=retryable,
            public_message=public_message,
        )
    )


def _is_pymysql_error(error: Exception) -> bool:
    """Check if *error* originates from the pymysql driver."""
    return type(error).__module__.startswith("pymysql.")


def _normalize_pymysql_error(
    error: Exception,
) -> DatabaseConnectorError:
    """Normalize a pymysql driver exception."""
    errno: int | None = None
    args = getattr(error, "args", None)
    if isinstance(args, tuple) and len(args) >= 1:
        code = args[0]
        if isinstance(code, int):
            errno = code

    sqlstate = f"MY-{errno:05d}" if errno is not None else None
    error_type = (
        classify_mysql_error_code(errno)
        if errno is not None
        else ErrorType.CONNECTION_ERROR
    )

    retryable = error_type in (
        ErrorType.CONNECTION_ERROR,
    )
    code, public_message = _PUBLIC_ERRORS[error_type]
    return DatabaseConnectorError(
        DatabaseError(
            sqlstate=sqlstate,
            error_type=error_type,
            code=code,
            retryable=retryable,
            public_message=public_message,
        )
    )
