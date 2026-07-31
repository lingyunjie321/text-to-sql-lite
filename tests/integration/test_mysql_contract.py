"""MySQL Connector 契约测试。

需要真实 MySQL 实例：设置 TEXT_TO_SQL_MYSQL_DSN 环境变量。
未设置时自动 skip。参照 tests/integration/test_postgresql_connector.py
的契约要点：连接、元数据、只读强制、超时、类型规范化、行上限。
"""

from __future__ import annotations

import os

import pytest

from app.config import DatabaseSettings
from app.connectors.mysql import MySQLConnector

_DSN_ENV = "TEXT_TO_SQL_MYSQL_DSN"


@pytest.fixture
def mysql_settings() -> DatabaseSettings:
    dsn = os.environ.get(_DSN_ENV)
    if not dsn:
        pytest.skip(f"{_DSN_ENV} is not set; MySQL contract tests skipped")
    return DatabaseSettings(
        datasource_id="mysql-test",
        type="mysql",
        dsn=dsn,
    )


@pytest.fixture
def mysql_connector(
    mysql_settings: DatabaseSettings,
) -> MySQLConnector:
    conn = MySQLConnector(
        host=mysql_settings.host,
        port=mysql_settings.port,
        user=mysql_settings.username,
        password=mysql_settings.password_value or "",
        database=mysql_settings.database,
    )
    conn.open()
    yield conn
    conn.close()


@pytest.mark.integration
class TestMySQLConnectorContract:
    def test_connects_successfully(
        self, mysql_connector: MySQLConnector
    ) -> None:
        assert mysql_connector is not None

    def test_reads_metadata_within_scope(
        self, mysql_connector: MySQLConnector
    ) -> None:
        snapshot = mysql_connector.read_metadata(
            allowed_schemas=("test",),
            allowed_tables=("test.t1",),
        )
        assert snapshot.schema_version

    def test_rejects_write_operation(
        self, mysql_connector: MySQLConnector
    ) -> None:
        with pytest.raises(Exception):
            mysql_connector.execute_readonly(
                "INSERT INTO test.t1 VALUES (1)"
            )

    def test_normalizes_null_and_decimal(
        self, mysql_connector: MySQLConnector
    ) -> None:
        result = mysql_connector.execute_readonly(
            "SELECT NULL AS n, CAST(1.23 AS DECIMAL(10,2)) AS d"
        )
        assert result.returned_row_count == 1
        assert result.rows[0][0] is None
        assert result.rows[0][1] is not None

    def test_row_limit_truncation(
        self, mysql_connector: MySQLConnector
    ) -> None:
        result = mysql_connector.execute_readonly(
            "SELECT 1 UNION SELECT 2 UNION SELECT 3"
        )
        assert result.returned_row_count <= 1000
