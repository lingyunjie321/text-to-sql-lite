from datetime import datetime, timezone
from urllib.parse import urlsplit, urlunsplit

import pytest

from app.config import DatabaseSettings
from app.connectors.errors import ErrorType, PostgreSQLConnectorError
from app.connectors.postgresql import PostgreSQLConnector


def _settings_with(
    settings: DatabaseSettings, **overrides: object
) -> DatabaseSettings:
    values: dict[str, object] = {
        "datasource_id": settings.datasource_id,
        "dsn": settings.dsn_value,
        "min_pool_size": settings.min_pool_size,
        "max_pool_size": settings.max_pool_size,
        "pool_timeout_seconds": settings.pool_timeout_seconds,
        "statement_timeout_seconds": settings.statement_timeout_seconds,
        "max_result_rows": settings.max_result_rows,
        "connection_retry_count": settings.connection_retry_count,
    }
    values.update(overrides)
    return DatabaseSettings(**values)


@pytest.mark.integration
def test_pagila_select(connector: PostgreSQLConnector) -> None:
    result = connector.execute(
        "SELECT film_id, title, rental_rate "
        "FROM film ORDER BY film_id LIMIT 3"
    )

    assert [column.name for column in result.columns] == [
        "film_id",
        "title",
        "rental_rate",
    ]
    assert result.returned_row_count == 3
    assert result.truncated is False
    assert result.rows[0][0] == 1
    assert result.rows[0][2] == "0.99"


@pytest.mark.integration
@pytest.mark.parametrize(
    ("sql", "expected"),
    [
        (
            "WITH selected AS (SELECT film_id FROM film WHERE film_id <= 2) "
            "SELECT COUNT(*) FROM selected",
            [[2]],
        ),
        ("SELECT COUNT(*) FROM film", [[1000]]),
        ("SELECT film_id FROM film WHERE false", []),
    ],
)
def test_pagila_common_query_shapes(
    connector: PostgreSQLConnector,
    sql: str,
    expected: list[list[object]],
) -> None:
    result = connector.execute(sql)

    assert result.rows == expected
    assert result.truncated is False


@pytest.mark.integration
def test_result_limit_reads_one_extra_row(
    connector: PostgreSQLConnector,
) -> None:
    result = connector.execute(
        "SELECT n FROM generate_series(1, 1001) AS n"
    )

    assert result.returned_row_count == 1000
    assert len(result.rows) == 1000
    assert result.rows[-1] == [1000]
    assert result.truncated is True


@pytest.mark.integration
def test_postgresql_values_are_json_normalized(
    connector: PostgreSQLConnector,
) -> None:
    result = connector.execute(
        """
        SELECT
            NULL::text AS null_value,
            10.20::numeric AS amount,
            DATE '2026-07-28' AS on_date,
            TIME '08:30:00' AS at_time,
            TIMESTAMPTZ '2026-07-28 08:30:00+00' AS at_timestamp,
            '{"active": true}'::jsonb AS payload,
            '12345678-1234-5678-1234-567812345678'::uuid AS identifier,
            ARRAY[1, 2, 3]::integer[] AS items
        """
    )

    assert result.rows == [[
        None,
        "10.20",
        "2026-07-28",
        "08:30:00",
        datetime(2026, 7, 28, 8, 30, tzinfo=timezone.utc).isoformat(),
        {"active": True},
        "12345678-1234-5678-1234-567812345678",
        [1, 2, 3],
    ]]


@pytest.mark.integration
def test_timeout_cancels_query_and_connection_recovers(
    database_settings: DatabaseSettings,
) -> None:
    timeout_settings = _settings_with(
        database_settings, statement_timeout_seconds=1
    )

    with PostgreSQLConnector(timeout_settings) as connector:
        with pytest.raises(PostgreSQLConnectorError) as caught:
            connector.execute("SELECT pg_sleep(2)")

        assert caught.value.details.error_type is ErrorType.TIMEOUT
        assert caught.value.details.sqlstate == "57014"
        assert connector.execute("SELECT 1").rows == [[1]]


@pytest.mark.integration
def test_write_is_rejected_and_data_is_unchanged(
    connector: PostgreSQLConnector,
) -> None:
    before = connector.execute("SELECT COUNT(*) FROM actor").rows

    with pytest.raises(PostgreSQLConnectorError) as caught:
        connector.execute(
            "INSERT INTO actor(first_name, last_name) "
            "VALUES ('SHOULD', 'FAIL')"
        )

    assert caught.value.details.error_type is ErrorType.PERMISSION_DENIED
    assert caught.value.details.sqlstate in {"25006", "42501"}
    assert connector.execute("SELECT COUNT(*) FROM actor").rows == before


@pytest.mark.integration
def test_read_only_snapshot_reuses_one_repeatable_read_transaction(
    connector: PostgreSQLConnector,
) -> None:
    with connector.read_only_snapshot() as snapshot:
        first_transaction_id = snapshot.execute(
            "SELECT txid_current()"
        ).rows
        second_transaction_id = snapshot.execute(
            "SELECT txid_current()"
        ).rows
        settings = snapshot.execute(
            "SELECT current_setting('transaction_isolation'), "
            "current_setting('transaction_read_only')"
        ).rows

    assert first_transaction_id == second_transaction_id
    assert settings == [["repeatable read", "on"]]


@pytest.mark.integration
def test_read_only_snapshot_preserves_application_exceptions(
    connector: PostgreSQLConnector,
) -> None:
    class ApplicationFailure(RuntimeError):
        pass

    with pytest.raises(ApplicationFailure, match="application failed"):
        with connector.read_only_snapshot():
            raise ApplicationFailure("application failed")


def _replace_password(dsn: str, password: str) -> str:
    parts = urlsplit(dsn)
    username = parts.username or ""
    host = parts.hostname or "127.0.0.1"
    port = f":{parts.port}" if parts.port else ""
    return urlunsplit(
        (
            parts.scheme,
            f"{username}:{password}@{host}{port}",
            parts.path,
            parts.query,
            parts.fragment,
        )
    )


@pytest.mark.integration
def test_authentication_failure_is_not_retryable(
    database_settings: DatabaseSettings,
) -> None:
    invalid = _settings_with(
        database_settings,
        dsn=_replace_password(database_settings.dsn_value, "wrong"),
    )
    connector = PostgreSQLConnector(invalid)

    with pytest.raises(PostgreSQLConnectorError) as caught:
        connector.check_connection()

    assert caught.value.details.error_type is ErrorType.PERMISSION_DENIED
    assert caught.value.details.sqlstate == "28P01"
    assert caught.value.details.retryable is False
    assert "wrong" not in repr(caught.value)


@pytest.mark.integration
def test_connection_refused_is_public_safe(
    database_settings: DatabaseSettings,
) -> None:
    parts = urlsplit(database_settings.dsn_value)
    refused_dsn = urlunsplit(
        (
            parts.scheme,
            f"{parts.username}:{parts.password}@127.0.0.1:1",
            parts.path,
            parts.query,
            parts.fragment,
        )
    )
    connector = PostgreSQLConnector(
        _settings_with(
            database_settings, dsn=refused_dsn, pool_timeout_seconds=1
        )
    )

    with pytest.raises(PostgreSQLConnectorError) as caught:
        connector.check_connection()

    assert caught.value.details.error_type is ErrorType.CONNECTION_ERROR
    assert database_settings.dsn_value not in repr(caught.value)


@pytest.mark.integration
def test_pool_timeout_is_not_retried(
    database_settings: DatabaseSettings,
) -> None:
    settings = _settings_with(
        database_settings,
        min_pool_size=1,
        max_pool_size=1,
        pool_timeout_seconds=0.1,
        connection_retry_count=3,
    )

    with PostgreSQLConnector(settings) as connector:
        with connector._pool.connection():
            with pytest.raises(PostgreSQLConnectorError) as caught:
                connector.execute("SELECT 1")

    assert caught.value.details.error_type is ErrorType.CONNECTION_ERROR
    assert caught.value.details.retryable is False
