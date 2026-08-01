from unittest.mock import Mock

import pytest

from app.config import DatabaseSettings


def _settings(database_type: str) -> DatabaseSettings:
    if database_type == "postgresql":
        return DatabaseSettings(
            type=database_type,
            dsn="postgresql://reader:secret@127.0.0.1:55432/pagila",
        )
    return DatabaseSettings(
        type=database_type,
        host="127.0.0.1",
        port=3306 if database_type == "mysql" else 9030,
        database="analytics",
        username="reader",
        password="secret",
    )


@pytest.mark.parametrize(
    ("database_type", "constructor_name"),
    (
        ("postgresql", "PostgreSQLConnector"),
        ("mysql", "MySQLConnector"),
        ("starrocks", "StarRocksConnector"),
    ),
)
def test_factory_constructs_connector_without_opening_it(
    monkeypatch: pytest.MonkeyPatch,
    database_type: str,
    constructor_name: str,
) -> None:
    from app.connectors import factory

    connector = Mock()
    constructor = Mock(return_value=connector)
    monkeypatch.setattr(factory, constructor_name, constructor)

    created = factory.ConnectorFactory().create(_settings(database_type))

    assert created is connector
    connector.open.assert_not_called()
    if database_type == "postgresql":
        constructor.assert_called_once_with(_settings(database_type))
    else:
        settings = _settings(database_type)
        constructor.assert_called_once_with(
            host=settings.host,
            port=settings.port,
            user=settings.username,
            password=settings.password_value,
            database=settings.database,
            min_pool_size=settings.min_pool_size,
            max_pool_size=settings.max_pool_size,
            pool_timeout_seconds=settings.pool_timeout_seconds,
            statement_timeout_seconds=settings.statement_timeout_seconds,
            max_result_rows=settings.max_result_rows,
            connection_retry_count=settings.connection_retry_count,
        )
