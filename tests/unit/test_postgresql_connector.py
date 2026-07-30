from unittest.mock import Mock, call

import psycopg
import pytest
from psycopg_pool import PoolTimeout

from app.config import DatabaseSettings
from app.connectors.errors import (
    DatabaseError,
    ErrorType,
    PostgreSQLConnectorError,
)
from app.connectors.models import ExecutionResult
from app.connectors.postgresql import PostgreSQLConnector


def _settings(**overrides: object) -> DatabaseSettings:
    values: dict[str, object] = {
        "dsn": "postgresql://reader:secret@127.0.0.1:55432/pagila",
        "min_pool_size": 1,
        "max_pool_size": 1,
        "pool_timeout_seconds": 0.1,
    }
    values.update(overrides)
    return DatabaseSettings(**values)


def _result() -> ExecutionResult:
    return ExecutionResult(
        columns=(),
        rows=[],
        returned_row_count=0,
        truncated=False,
        execution_time_ms=0.1,
    )


def _connector_error(
    error_type: ErrorType,
    *,
    sqlstate: str | None = None,
    retryable: bool = False,
) -> PostgreSQLConnectorError:
    return PostgreSQLConnectorError(
        DatabaseError(
            sqlstate=sqlstate,
            error_type=error_type,
            code=f"DB_{error_type.value}",
            retryable=retryable,
            public_message="safe",
        )
    )


def test_pool_is_created_closed() -> None:
    connector = PostgreSQLConnector(_settings())

    assert connector._pool.closed is True


def test_open_checks_connection_before_opening_pool() -> None:
    connector = PostgreSQLConnector(_settings())
    events: list[str] = []
    connector.check_connection = Mock(
        side_effect=lambda: events.append("check")
    )
    connector._pool = Mock(
        closed=True,
        open=Mock(side_effect=lambda **_: events.append("open")),
    )

    connector.open()

    assert events == ["check", "open"]
    connector._pool.open.assert_called_once_with(wait=True, timeout=0.1)


def test_close_is_idempotent() -> None:
    connector = PostgreSQLConnector(_settings())
    pool = Mock(closed=False)
    connector._pool = pool

    connector.close()
    pool.closed = True
    connector.close()

    pool.close.assert_called_once()


def test_context_manager_opens_and_closes() -> None:
    connector = PostgreSQLConnector(_settings())
    connector.open = Mock()
    connector.close = Mock()

    with connector as entered:
        assert entered is connector

    connector.open.assert_called_once_with()
    connector.close.assert_called_once_with()


def test_execute_retries_identical_sql_for_operational_error() -> None:
    connector = PostgreSQLConnector(_settings(connection_retry_count=1))
    expected_result = _result()
    sql = "SELECT film_id FROM film"
    connector._execute_once = Mock(
        side_effect=[
            psycopg.OperationalError("server closed unexpectedly"),
            expected_result,
        ]
    )

    assert connector.execute(sql) is expected_result
    assert connector._execute_once.call_args_list == [call(sql), call(sql)]


def test_execute_caps_database_call_to_remaining_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connector = PostgreSQLConnector(_settings())
    connector._execute_once = Mock(return_value=_result())
    monkeypatch.setattr(
        "app.connectors.postgresql.time.monotonic",
        lambda: 10.0,
    )

    result = connector.execute(
        "SELECT 1",
        timeout_seconds=0.05,
    )

    assert result == _result()
    connector._execute_once.assert_called_once_with(
        "SELECT 1",
        timeout_seconds=0.05,
    )


@pytest.mark.parametrize("retry_count", [0, 1, 3])
def test_execute_honors_connection_retry_budget(retry_count: int) -> None:
    connector = PostgreSQLConnector(
        _settings(connection_retry_count=retry_count)
    )
    failures = [
        _connector_error(
            ErrorType.CONNECTION_ERROR,
            sqlstate="08006",
            retryable=True,
        )
        for _ in range(retry_count)
    ]
    connector._execute_once = Mock(side_effect=[*failures, _result()])

    assert connector.execute("SELECT 1") == _result()
    assert connector._execute_once.call_count == retry_count + 1
    assert connector._consume_retry_count() == retry_count
    assert connector._consume_retry_count() == 0


def test_execute_stops_after_connection_retry_budget() -> None:
    connector = PostgreSQLConnector(_settings(connection_retry_count=1))
    failure = _connector_error(
        ErrorType.CONNECTION_ERROR,
        sqlstate="08006",
        retryable=True,
    )
    connector._execute_once = Mock(side_effect=failure)

    with pytest.raises(PostgreSQLConnectorError):
        connector.execute("SELECT 1")

    assert connector._execute_once.call_count == 2


@pytest.mark.parametrize(
    "failure",
    [
        _connector_error(ErrorType.SYNTAX_ERROR, sqlstate="42601"),
        _connector_error(ErrorType.SCHEMA_ERROR, sqlstate="42P01"),
        _connector_error(ErrorType.PERMISSION_DENIED, sqlstate="42501"),
        _connector_error(ErrorType.TIMEOUT, sqlstate="57014"),
        _connector_error(ErrorType.RESOURCE_RISK, sqlstate="53000"),
        _connector_error(ErrorType.UNKNOWN),
        PoolTimeout("pool exhausted"),
    ],
)
def test_execute_does_not_retry_non_transient_errors(
    failure: Exception,
) -> None:
    connector = PostgreSQLConnector(_settings(connection_retry_count=3))
    connector._execute_once = Mock(side_effect=failure)

    with pytest.raises(PostgreSQLConnectorError):
        connector.execute("SELECT 1")

    connector._execute_once.assert_called_once_with("SELECT 1")
