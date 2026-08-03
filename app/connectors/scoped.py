"""只允许 Workflow 使用 Profile 授权范围的连接器视图。"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from app.connectors.base import DatabaseConnector
from app.connectors.catalog import (
    allowlist_mismatch_error,
    canonical_allowlist,
    ensure_snapshot_matches_allowlist,
)
from app.connectors.metadata import SchemaSnapshot
from app.connectors.models import ExecutionResult


class ProfileScopedConnector:
    """在 Connector 边界固定 DatasourceProfile 的 allowlist。"""

    def __init__(
        self,
        *,
        delegate: DatabaseConnector,
        allowed_schemas: tuple[str, ...],
        allowed_tables: tuple[str, ...],
    ) -> None:
        self._delegate = delegate
        self._allowed_schemas, self._allowed_tables = canonical_allowlist(
            allowed_schemas,
            allowed_tables,
            dialect=delegate.dialect_name,
        )

    @property
    def dialect_name(self) -> str:
        return self._delegate.dialect_name

    def open(self) -> None:
        self._delegate.open()

    def close(self) -> None:
        self._delegate.close()

    def check_connection(self) -> None:
        self._delegate.check_connection()

    def execute(
        self,
        sql: str,
        *,
        timeout_seconds: float | None = None,
    ) -> ExecutionResult:
        return self._delegate.execute(
            sql,
            timeout_seconds=timeout_seconds,
        )

    def read_metadata(
        self,
        allowed_schemas: tuple[str, ...],
        allowed_tables: tuple[str, ...],
        *,
        timeout_seconds: float | None = None,
    ) -> SchemaSnapshot:
        requested_schemas, requested_tables = canonical_allowlist(
            allowed_schemas,
            allowed_tables,
            dialect=self.dialect_name,
        )
        requested_schema_set = set(requested_schemas)
        expected_tables = tuple(
            table
            for table in self._allowed_tables
            if table.split(".", 1)[0] in requested_schema_set
        )
        if (
            not requested_schema_set.issubset(self._allowed_schemas)
            or requested_tables != expected_tables
        ):
            raise allowlist_mismatch_error()
        snapshot = self._delegate.read_metadata(
            requested_schemas,
            requested_tables,
            timeout_seconds=timeout_seconds,
        )
        ensure_snapshot_matches_allowlist(
            snapshot,
            allowed_schemas=requested_schemas,
            allowed_tables=requested_tables,
        )
        return snapshot

    @contextmanager
    def read_only_snapshot(self) -> Iterator[ProfileScopedConnector]:
        with self._delegate.read_only_snapshot():
            yield self

    def _consume_retry_count(self) -> int:
        consume = getattr(self._delegate, "_consume_retry_count", None)
        if not callable(consume):
            return 0
        value = consume()
        return value if type(value) is int and value >= 0 else 0
