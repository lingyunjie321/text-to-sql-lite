"""连接器注册表：按数据源 ID 登记与检索连接器实例。

注册表是工作流运行时解析 ``datasource_id`` 到具体连接器的唯一入口，
并负责统一关闭所有已登记连接器。
"""

from __future__ import annotations

from app.connectors.base import DatabaseConnector
from app.connectors.errors import DatabaseConnectorError, DatabaseError, ErrorType


class ConnectorRegistry:
    """Thread-safe registry of named database connectors.

    Typical lifecycle::

        registry = ConnectorRegistry()
        registry.register("pagila", pg_connector)
        registry.register("orders-db", mysql_connector)

        with registry.get("pagila") as connector:
            ...

        registry.close_all()
    """

    def __init__(self) -> None:
        self._connectors: dict[str, DatabaseConnector] = {}

    def register(
        self,
        datasource_id: str,
        connector: DatabaseConnector,
    ) -> None:
        """Register *connector* under *datasource_id*.

        Duplicate datasource ids are rejected so the existing connector
        remains the sole lifecycle owner for that id.
        """
        if not datasource_id.strip():
            raise ValueError("datasource_id must be non-empty")
        if datasource_id in self._connectors:
            raise ValueError("datasource_id is already registered")
        # Duck-type check (not isinstance, to allow Mock objects in tests)
        if not callable(getattr(connector, "execute", None)):
            raise TypeError(
                "connector must implement execute(sql, *, timeout_seconds=None)"
            )
        self._connectors[datasource_id] = connector

    def get(self, datasource_id: str) -> DatabaseConnector:
        """Retrieve the connector registered under *datasource_id*.

        Raises :class:`DatabaseConnectorError` when the datasource is
        unknown.
        """
        connector = self._connectors.get(datasource_id)
        if connector is None:
            raise DatabaseConnectorError(
                DatabaseError(
                    sqlstate=None,
                    error_type=ErrorType.CONNECTION_ERROR,
                    code="DB_UNKNOWN_DATASOURCE",
                    retryable=False,
                    public_message=f"Unknown datasource: {datasource_id!r}",
                )
            )
        return connector

    def list_datasources(self) -> list[str]:
        """Return a sorted list of registered datasource ids."""
        return sorted(self._connectors.keys())

    def close_all(self) -> None:
        """Close every registered connector."""
        errors: list[tuple[str, Exception]] = []
        for datasource_id, connector in reversed(
            tuple(self._connectors.items())
        ):
            try:
                connector.close()
            except Exception as exc:
                errors.append((datasource_id, exc))
        self._connectors.clear()
        if errors:
            datasource_ids = ", ".join(
                datasource_id for datasource_id, _ in errors
            )
            raise DatabaseConnectorError(
                DatabaseError(
                    sqlstate=None,
                    error_type=ErrorType.CONNECTION_ERROR,
                    code="DB_CLOSE_ERROR",
                    retryable=False,
                    public_message=(
                        "Failed to close connectors: "
                        f"{datasource_ids}"
                    ),
                )
            )
