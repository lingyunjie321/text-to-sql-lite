"""Construction of configured database connectors without side effects."""

from __future__ import annotations

from app.config import DatabaseSettings
from app.connectors.base import DatabaseConnector
from app.connectors.mysql import MySQLConnector
from app.connectors.postgresql import PostgreSQLConnector
from app.connectors.starrocks import StarRocksConnector


class ConnectorFactory:
    """Create a connector for validated settings; callers own its lifecycle."""

    def create(self, settings: DatabaseSettings) -> DatabaseConnector:
        if not isinstance(settings, DatabaseSettings):
            raise ValueError("database settings are invalid")
        if settings.type == "postgresql":
            return PostgreSQLConnector(settings)
        if settings.type == "mysql":
            return MySQLConnector(
                host=settings.host,
                port=settings.port,
                user=settings.username,
                password=settings.password_value or "",
                database=settings.database,
                min_pool_size=settings.min_pool_size,
                max_pool_size=settings.max_pool_size,
                pool_timeout_seconds=settings.pool_timeout_seconds,
                statement_timeout_seconds=settings.statement_timeout_seconds,
                max_result_rows=settings.max_result_rows,
                connection_retry_count=settings.connection_retry_count,
            )
        if settings.type == "starrocks":
            return StarRocksConnector(
                host=settings.host,
                port=settings.port,
                user=settings.username,
                password=settings.password_value or "",
                database=settings.database,
                min_pool_size=settings.min_pool_size,
                max_pool_size=settings.max_pool_size,
                pool_timeout_seconds=settings.pool_timeout_seconds,
                statement_timeout_seconds=settings.statement_timeout_seconds,
                max_result_rows=settings.max_result_rows,
                connection_retry_count=settings.connection_retry_count,
            )
        raise ValueError("database type is unsupported")
