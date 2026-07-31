"""连接器协议定义：所有可插拔数据库连接器必须满足的接口契约。

本模块只包含 :class:`DatabaseConnector` 协议，连接器实现采用鸭子类型，
无需继承；工作流与执行层只依赖本协议，不感知具体数据库方言。
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Protocol, runtime_checkable

from app.connectors.metadata import MetadataScope, SchemaSnapshot
from app.connectors.models import ExecutionResult


@runtime_checkable
class DatabaseConnector(Protocol):
    """Protocol that every pluggable database connector must satisfy.

    Connectors are duck-type compatible — no inheritance required.
    """

    @property
    def dialect_name(self) -> str:
        """Database dialect identifier, e.g. ``"postgres"``, ``"mysql"``,
        or ``"starrocks"``."""
        ...

    def open(self) -> None:
        """Open the connection pool and verify connectivity."""
        ...

    def close(self) -> None:
        """Close the connection pool, releasing all resources."""
        ...

    def check_connection(self) -> None:
        """Perform a lightweight connectivity check (e.g. ``SELECT 1``).

        Raises :class:`DatabaseConnectorError` on failure.
        """
        ...

    def execute(
        self,
        sql: str,
        *,
        timeout_seconds: float | None = None,
    ) -> ExecutionResult:
        """Execute *sql* and return the result set.

        Parameters
        ----------
        sql:
            The SQL statement to execute.
        timeout_seconds:
            Optional per-call timeout.  Falls back to the connector's
            default when not set.

        Returns
        -------
        ExecutionResult
        """
        ...

    def read_metadata(
        self,
        allowed_schemas: tuple[str, ...],
        allowed_tables: tuple[str, ...],
        *,
        timeout_seconds: float | None = None,
    ) -> SchemaSnapshot:
        """Return a schema snapshot scoped to the supplied identifiers.

        The resulting :class:`SchemaSnapshot` is used by the validation
        pipeline to check SQL correctness before execution.
        """
        ...

    @contextmanager
    def read_only_snapshot(self):
        """Context manager that enters a read-only snapshot transaction.

        Inside the ``with`` block all `execute` and `read_metadata`
        calls should reuse the same snapshot connection so that metadata
        and data are consistent.
        """
        ...
