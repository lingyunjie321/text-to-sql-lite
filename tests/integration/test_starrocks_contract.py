"""StarRocks Connector 契约测试。

需要真实 StarRocks 实例：设置 TEXT_TO_SQL_STARROCKS_DSN 环境变量。
未设置时自动 skip。
"""

from __future__ import annotations

import os

import pytest

from app.config import DatabaseSettings
from app.connectors.starrocks import StarRocksConnector

_DSN_ENV = "TEXT_TO_SQL_STARROCKS_DSN"


@pytest.fixture
def starrocks_settings() -> DatabaseSettings:
    dsn = os.environ.get(_DSN_ENV)
    if not dsn:
        pytest.skip(f"{_DSN_ENV} is not set; StarRocks contract tests skipped")
    return DatabaseSettings(
        datasource_id="starrocks-test",
        type="starrocks",
        dsn=dsn,
    )


@pytest.fixture
def starrocks_connector(
    starrocks_settings: DatabaseSettings,
) -> StarRocksConnector:
    conn = StarRocksConnector(
        host=starrocks_settings.host,
        port=starrocks_settings.port,
        user=starrocks_settings.username,
        password=starrocks_settings.password_value or "",
        database=starrocks_settings.database,
    )
    conn.open()
    yield conn
    conn.close()


@pytest.mark.integration
class TestStarRocksConnectorContract:
    def test_connects_successfully(
        self, starrocks_connector: StarRocksConnector
    ) -> None:
        assert starrocks_connector is not None

    def test_reads_metadata_without_fk(
        self, starrocks_connector: StarRocksConnector
    ) -> None:
        snapshot = starrocks_connector.read_metadata(
            allowed_schemas=("test",),
            allowed_tables=("test.t1",),
        )
        # StarRocks 不支持 FK；元数据中外键应为空
        assert snapshot.foreign_keys == ()

    def test_rejects_write_operation(
        self, starrocks_connector: StarRocksConnector
    ) -> None:
        with pytest.raises(Exception):
            starrocks_connector.execute_readonly(
                "INSERT INTO test.t1 VALUES (1)"
            )

    def test_normalizes_null_and_types(
        self, starrocks_connector: StarRocksConnector
    ) -> None:
        result = starrocks_connector.execute_readonly(
            "SELECT NULL AS n"
        )
        assert result.returned_row_count == 1
        assert result.rows[0][0] is None
