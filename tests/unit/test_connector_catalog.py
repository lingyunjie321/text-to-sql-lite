from __future__ import annotations

from dataclasses import replace

import pytest

from app.connectors.metadata import (
    ColumnMetadata,
    ForeignKeyMetadata,
    TableMetadata,
    build_schema_snapshot,
)
from app.connectors.models import ExecutionResult
from app.connectors.catalog import (
    MetadataLimits,
    RelationIdentity,
    discover_metadata,
)


def _column(
    table_name: str,
    column_name: str,
    ordinal_position: int,
    *,
    schema_name: str = "public",
) -> ColumnMetadata:
    return ColumnMetadata(
        schema_name=schema_name,
        table_name=table_name,
        column_name=column_name,
        ordinal_position=ordinal_position,
        data_type="integer",
        formatted_type="integer",
        nullable=False,
        comment=None,
    )


def _table(
    table_name: str,
    *,
    schema_name: str = "public",
    relation_kind: str = "table",
    column_count: int = 1,
) -> TableMetadata:
    return TableMetadata(
        schema_name=schema_name,
        table_name=table_name,
        relation_kind=relation_kind,
        comment=None,
        columns=tuple(
            _column(
                table_name,
                f"column_{index}",
                index,
                schema_name=schema_name,
            )
            for index in range(1, column_count + 1)
        ),
    )


def _foreign_key(index: int) -> ForeignKeyMetadata:
    return ForeignKeyMetadata(
        constraint_name=f"fk_{index}",
        source_schema="public",
        source_table="actor",
        source_columns=("column_1",),
        target_schema="public",
        target_table="staff",
        target_columns=("column_1",),
    )


class CatalogConnectorFake:
    dialect_name = "postgres"

    def __init__(
        self,
        *,
        rows: tuple[tuple[object, ...], ...],
        tables: tuple[TableMetadata, ...],
        foreign_keys: tuple[ForeignKeyMetadata, ...] = (),
    ) -> None:
        self._rows = rows
        self._tables = tables
        self._foreign_keys = foreign_keys
        self.executed_sql: list[str] = []
        self.execute_timeouts: list[float | None] = []
        self.metadata_calls: list[
            tuple[tuple[str, ...], tuple[str, ...], float | None]
        ] = []

    def execute(
        self,
        sql: str,
        *,
        timeout_seconds: float | None = None,
    ) -> ExecutionResult:
        self.executed_sql.append(sql)
        self.execute_timeouts.append(timeout_seconds)
        return ExecutionResult(
            columns=(),
            rows=[list(row) for row in self._rows],
            returned_row_count=len(self._rows),
            truncated=False,
            execution_time_ms=0.0,
        )

    def read_metadata(
        self,
        allowed_schemas: tuple[str, ...],
        allowed_tables: tuple[str, ...],
        *,
        timeout_seconds: float | None = None,
    ):
        self.metadata_calls.append(
            (allowed_schemas, allowed_tables, timeout_seconds)
        )
        allowed = set(allowed_tables)
        tables = tuple(
            table
            for table in self._tables
            if f"{table.schema_name}.{table.table_name}" in allowed
        )
        return build_schema_snapshot(
            tables=tables,
            primary_keys=(),
            foreign_keys=self._foreign_keys,
            unique_constraints=(),
            unique_indexes=(),
        )


def test_postgresql_discovery_excludes_system_schemas_and_sorts_relations():
    connector = CatalogConnectorFake(
        rows=(
            ("public", "z_view", "VIEW"),
            ("pg_catalog", "pg_class", "BASE TABLE"),
            ("pg_toast", "toast_table", "BASE TABLE"),
            ("pg_temp_3", "temp_table", "BASE TABLE"),
            ("information_schema", "tables", "VIEW"),
            ("public", "actor", "BASE TABLE"),
        ),
        tables=(
            _table("z_view", relation_kind="view"),
            _table("actor"),
        ),
    )

    result = discover_metadata(connector, dialect="postgres")

    assert result.relations == (
        RelationIdentity("public", "actor", "table"),
        RelationIdentity("public", "z_view", "view"),
    )
    assert result.truncated is False
    assert connector.execute_timeouts == [30.0]
    assert connector.metadata_calls == [
        (
            ("public",),
            ("public.actor", "public.z_view"),
            30.0,
        )
    ]


def test_mysql_discovery_excludes_system_schemas():
    connector = CatalogConnectorFake(
        rows=(
            ("mysql", "user", "BASE TABLE"),
            ("performance_schema", "accounts", "BASE TABLE"),
            ("information_schema", "tables", "SYSTEM VIEW"),
            ("sys", "host_summary", "VIEW"),
            ("sakila", "film_list", "VIEW"),
            ("sakila", "film", "BASE TABLE"),
        ),
        tables=(
            _table("film", schema_name="sakila"),
            _table(
                "film_list",
                schema_name="sakila",
                relation_kind="view",
            ),
        ),
    )

    result = discover_metadata(connector, dialect="mysql")

    assert result.relations == (
        RelationIdentity("sakila", "film", "table"),
        RelationIdentity("sakila", "film_list", "view"),
    )
    assert "information_schema" in connector.executed_sql[0]


def test_relation_limit_reads_only_complete_selected_relations():
    connector = CatalogConnectorFake(
        rows=(
            ("public", "third", "BASE TABLE"),
            ("public", "first", "BASE TABLE"),
            ("public", "second", "BASE TABLE"),
        ),
        tables=(_table("first"), _table("second"), _table("third")),
    )

    result = discover_metadata(
        connector,
        dialect="postgres",
        limits=replace(MetadataLimits(), max_relations=2),
    )

    assert tuple(table.table_name for table in result.snapshot.tables) == (
        "first",
        "second",
    )
    assert result.truncated is True
    assert connector.metadata_calls[0][1] == (
        "public.first",
        "public.second",
    )


def test_column_limit_stops_before_relation_that_would_split():
    connector = CatalogConnectorFake(
        rows=(
            ("public", "actor", "BASE TABLE"),
            ("public", "staff", "BASE TABLE"),
        ),
        tables=(
            _table("actor", column_count=2),
            _table("staff", column_count=1),
        ),
    )

    result = discover_metadata(
        connector,
        dialect="postgres",
        limits=replace(MetadataLimits(), max_columns=2),
    )

    assert tuple(table.table_name for table in result.snapshot.tables) == (
        "actor",
    )
    assert sum(
        len(table.columns) for table in result.snapshot.tables
    ) == 2
    assert result.relations == (
        RelationIdentity("public", "actor", "table"),
    )
    assert result.truncated is True


def test_foreign_key_limit_keeps_complete_objects_in_canonical_order():
    connector = CatalogConnectorFake(
        rows=(("public", "actor", "BASE TABLE"),),
        tables=(_table("actor"),),
        foreign_keys=(_foreign_key(2), _foreign_key(1)),
    )

    result = discover_metadata(
        connector,
        dialect="postgres",
        limits=replace(MetadataLimits(), max_foreign_keys=1),
    )

    assert tuple(
        foreign_key.constraint_name
        for foreign_key in result.snapshot.foreign_keys
    ) == ("fk_1",)
    assert result.truncated is True


@pytest.mark.parametrize("dialect", ["starrocks", "sqlite", ""])
def test_discovery_rejects_unsupported_dialect(dialect: str):
    connector = CatalogConnectorFake(rows=(), tables=())

    with pytest.raises(ValueError, match="metadata dialect is unsupported"):
        discover_metadata(connector, dialect=dialect)


@pytest.mark.parametrize(
    "limits",
    [
        replace(MetadataLimits(), timeout_seconds=0),
        replace(MetadataLimits(), max_relations=0),
        replace(MetadataLimits(), max_columns=0),
        replace(MetadataLimits(), max_foreign_keys=0),
    ],
)
def test_discovery_rejects_non_positive_limits(limits: MetadataLimits):
    connector = CatalogConnectorFake(rows=(), tables=())

    with pytest.raises(ValueError, match="metadata limits are invalid"):
        discover_metadata(connector, dialect="postgres", limits=limits)
