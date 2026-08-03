from __future__ import annotations

from contextlib import contextmanager

import pytest

from app.connectors.catalog import discover_metadata
from app.connectors.errors import DatabaseConnectorError
from app.connectors.metadata import (
    ColumnMetadata,
    TableMetadata,
    build_schema_snapshot,
)
from app.connectors.models import ExecutionResult
from app.connectors.scoped import ProfileScopedConnector


def _snapshot(*table_names: str):
    tables = tuple(
        TableMetadata(
            schema_name="public",
            table_name=table_name,
            relation_kind="table",
            comment=None,
            columns=(
                ColumnMetadata(
                    schema_name="public",
                    table_name=table_name,
                    column_name="id",
                    ordinal_position=1,
                    data_type="integer",
                    formatted_type="integer",
                    nullable=False,
                    comment=None,
                ),
            ),
        )
        for table_name in table_names
    )
    return build_schema_snapshot(
        tables=tables,
        primary_keys=(),
        foreign_keys=(),
        unique_constraints=(),
        unique_indexes=(),
    )


class DiscoverableConnector:
    dialect_name = "postgres"

    def __init__(self) -> None:
        self.metadata_calls: list[tuple[str, ...]] = []

    def execute(self, sql: str, *, timeout_seconds=None):
        del sql, timeout_seconds
        return ExecutionResult(
            columns=(),
            rows=[
                ["public", "actor", "BASE TABLE"],
                ["public", "private_ledger", "BASE TABLE"],
            ],
            returned_row_count=2,
            truncated=False,
            execution_time_ms=0.0,
        )

    def read_metadata(
        self,
        allowed_schemas,
        allowed_tables,
        *,
        timeout_seconds=None,
    ):
        del allowed_schemas, timeout_seconds
        self.metadata_calls.append(tuple(allowed_tables))
        names = tuple(table.split(".", 1)[1] for table in allowed_tables)
        return _snapshot(*names)

    @contextmanager
    def read_only_snapshot(self):
        yield self


def test_discoverable_metadata_never_expands_workflow_allowlist():
    raw_connector = DiscoverableConnector()
    discovered = discover_metadata(raw_connector, dialect="postgres")
    scoped = ProfileScopedConnector(
        delegate=raw_connector,
        allowed_schemas=("public",),
        allowed_tables=("public.actor",),
    )

    assert tuple(
        relation.qualified_name for relation in discovered.relations
    ) == ("public.actor", "public.private_ledger")

    with pytest.raises(DatabaseConnectorError) as captured:
        scoped.read_metadata(
            ("public",),
            ("public.actor", "public.private_ledger"),
        )

    assert captured.value.details.code == "DB_ALLOWLIST_MISMATCH"
    assert raw_connector.metadata_calls == [
        ("public.actor", "public.private_ledger"),
    ]


def test_allowlist_error_never_contains_discovered_object_names():
    raw_connector = DiscoverableConnector()
    scoped = ProfileScopedConnector(
        delegate=raw_connector,
        allowed_schemas=("public",),
        allowed_tables=("public.actor",),
    )

    with pytest.raises(DatabaseConnectorError) as captured:
        scoped.read_metadata(
            ("public",),
            ("public.private_ledger",),
        )

    public_error = str(captured.value)
    assert "actor" not in public_error
    assert "private_ledger" not in public_error
