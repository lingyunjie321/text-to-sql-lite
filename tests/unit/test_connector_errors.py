from dataclasses import FrozenInstanceError

import psycopg
import pytest
from psycopg_pool import PoolTimeout

from app.connectors.errors import (
    ErrorType,
    PostgreSQLConnectorError,
    classify_sqlstate,
    normalize_database_error,
)


@pytest.mark.parametrize(
    ("sqlstate", "expected"),
    [
        ("42601", ErrorType.SYNTAX_ERROR),
        ("42P01", ErrorType.SCHEMA_ERROR),
        ("42703", ErrorType.SCHEMA_ERROR),
        ("42702", ErrorType.SCHEMA_ERROR),
        ("42501", ErrorType.PERMISSION_DENIED),
        ("25006", ErrorType.PERMISSION_DENIED),
        ("28P01", ErrorType.PERMISSION_DENIED),
        ("08006", ErrorType.CONNECTION_ERROR),
        ("57014", ErrorType.TIMEOUT),
        ("53000", ErrorType.RESOURCE_RISK),
        ("XX000", ErrorType.UNKNOWN),
        (None, ErrorType.UNKNOWN),
    ],
)
def test_classify_sqlstate(sqlstate: str | None, expected: ErrorType) -> None:
    assert classify_sqlstate(sqlstate) is expected


def test_error_type_contains_complete_workflow_vocabulary() -> None:
    assert {member.value for member in ErrorType} == {
        "SYNTAX_ERROR",
        "SCHEMA_ERROR",
        "DIALECT_ERROR",
        "BUSINESS_KNOWLEDGE_MISSING",
        "AMBIGUOUS_SEMANTICS",
        "PERMISSION_DENIED",
        "CONNECTION_ERROR",
        "TIMEOUT",
        "RESOURCE_RISK",
        "DUPLICATE_SQL",
        "UNKNOWN",
    }


class FakeDatabaseError(Exception):
    sqlstate = "42P01"


def test_normalized_error_is_public_safe_and_immutable() -> None:
    error = FakeDatabaseError(
        "password=do-not-leak postgresql://reader:secret@localhost/pagila"
    )

    normalized = normalize_database_error(error)

    assert isinstance(normalized, PostgreSQLConnectorError)
    assert normalized.details.error_type is ErrorType.SCHEMA_ERROR
    assert normalized.details.code == "DB_SCHEMA_ERROR"
    assert normalized.details.retryable is False
    assert normalized.details.public_message == (
        "The SQL references an invalid database object."
    )
    assert "do-not-leak" not in repr(normalized)
    assert "secret" not in repr(normalized)
    with pytest.raises(FrozenInstanceError):
        normalized.details.code = "changed"  # type: ignore[misc]


@pytest.mark.parametrize(
    ("error", "retryable"),
    [
        (psycopg.OperationalError("connection closed"), True),
        (PoolTimeout("pool exhausted"), False),
        (FakeDatabaseError("missing relation"), False),
    ],
)
def test_retryability_is_limited_to_transient_connections(
    error: Exception, retryable: bool
) -> None:
    assert normalize_database_error(error).details.retryable is retryable


def test_class_08_is_retryable() -> None:
    class ConnectionFailure(Exception):
        sqlstate = "08006"

    normalized = normalize_database_error(ConnectionFailure("secret"))

    assert normalized.details.error_type is ErrorType.CONNECTION_ERROR
    assert normalized.details.retryable is True
    assert normalized.details.code == "DB_CONNECTION_ERROR"


def test_libpq_authentication_handshake_without_sqlstate_maps_to_28p01() -> None:
    class FinishedConnection:
        error_message = b'password authentication failed for user "reader"'

    class AuthenticationFailure(psycopg.OperationalError):
        @property
        def pgconn(self) -> FinishedConnection:
            return FinishedConnection()

    normalized = normalize_database_error(AuthenticationFailure("safe"))

    assert normalized.details.sqlstate == "28P01"
    assert normalized.details.error_type is ErrorType.PERMISSION_DENIED
    assert normalized.details.retryable is False
