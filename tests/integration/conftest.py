import os
from collections.abc import Iterator

import pytest

from app.config import DatabaseSettings
from app.connectors.postgresql import PostgreSQLConnector


@pytest.fixture(scope="session")
def database_settings() -> DatabaseSettings:
    dsn = os.environ.get("TEXT_TO_SQL_DATABASE_DSN")
    if not dsn:
        pytest.fail(
            "TEXT_TO_SQL_DATABASE_DSN is required for integration tests"
        )
    return DatabaseSettings(dsn=dsn)


@pytest.fixture
def connector(
    database_settings: DatabaseSettings,
) -> Iterator[PostgreSQLConnector]:
    with PostgreSQLConnector(database_settings) as active:
        yield active

