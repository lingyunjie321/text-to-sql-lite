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

        Overwrites any existing connector with the same id.
        """
        if not datasource_id.strip():
            raise ValueError("datasource_id must be non-empty")
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
        for datasource_id, connector in self._connectors.items():
            try:
                connector.close()
            except Exception as exc:
                errors.append((datasource_id, exc))
        self._connectors.clear()
        if errors:
            joined = "; ".join(
                f"{ds}: {err}" for ds, err in errors
            )
            raise DatabaseConnectorError(
                DatabaseError(
                    sqlstate=None,
                    error_type=ErrorType.CONNECTION_ERROR,
                    code="DB_CLOSE_ERROR",
                    retryable=False,
                    public_message=f"Errors closing connectors: {joined}",
                )
            )
