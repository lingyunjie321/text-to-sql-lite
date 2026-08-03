"""数据库结构目录发现与容量裁剪。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.connectors.base import DatabaseConnector
from app.connectors.errors import (
    DatabaseConnectorError,
    DatabaseError,
    ErrorType,
)
from app.connectors.metadata import (
    SchemaSnapshot,
    TableMetadata,
    build_schema_snapshot,
    normalize_metadata_scope,
)


POSTGRESQL_CATALOG_SQL = """
SELECT table_schema, table_name, table_type
FROM information_schema.tables
WHERE table_schema NOT IN ('pg_catalog', 'information_schema')
  AND table_schema NOT LIKE 'pg_toast%'
  AND table_schema NOT LIKE 'pg_temp_%'
  AND table_schema NOT LIKE 'pg_toast_temp_%'
ORDER BY table_schema, table_name, table_type
LIMIT {limit}
""".strip()

MYSQL_CATALOG_SQL = """
SELECT table_schema, table_name, table_type
FROM information_schema.tables
WHERE table_schema NOT IN (
    'information_schema', 'mysql', 'performance_schema', 'sys'
)
ORDER BY table_schema, table_name, table_type
LIMIT {limit}
""".strip()


@dataclass(frozen=True, slots=True)
class MetadataLimits:
    timeout_seconds: float = 30.0
    max_relations: int = 500
    max_columns: int = 10_000
    max_foreign_keys: int = 5_000


@dataclass(frozen=True, slots=True, order=True)
class RelationIdentity:
    schema_name: str
    relation_name: str
    relation_kind: Literal["table", "view"]

    @property
    def qualified_name(self) -> str:
        return f"{self.schema_name}.{self.relation_name}"


@dataclass(frozen=True, slots=True)
class DiscoveredMetadata:
    snapshot: SchemaSnapshot
    relations: tuple[RelationIdentity, ...]
    truncated: bool


def discover_metadata(
    connector: DatabaseConnector,
    *,
    dialect: str,
    limits: MetadataLimits = MetadataLimits(),
) -> DiscoveredMetadata:
    """发现账号可见的非系统关系，并按固定对象边界裁剪结构。"""
    _validate_limits(limits)
    catalog_sql = _catalog_sql(dialect, limits.max_relations + 1)
    result = connector.execute(
        catalog_sql,
        timeout_seconds=limits.timeout_seconds,
    )
    relations = tuple(
        sorted(
            {
                relation
                for row in result.rows
                if (
                    relation := _relation_from_row(
                        row,
                        dialect=dialect,
                    )
                )
                is not None
            }
        )
    )
    relation_truncated = (
        result.truncated or len(relations) > limits.max_relations
    )
    selected_relations = relations[: limits.max_relations]
    schemas = tuple(
        sorted({relation.schema_name for relation in selected_relations})
    )
    tables = tuple(
        relation.qualified_name for relation in selected_relations
    )
    snapshot = connector.read_metadata(
        schemas,
        tables,
        timeout_seconds=limits.timeout_seconds,
    )
    _ensure_catalog_matches_snapshot(selected_relations, snapshot)
    return _truncate_snapshot(
        snapshot,
        limits=limits,
        already_truncated=relation_truncated,
    )


def validate_allowlist(
    connector: DatabaseConnector,
    *,
    database_type: str,
    allowed_schemas: tuple[str, ...],
    allowed_tables: tuple[str, ...],
    timeout_seconds: float,
) -> SchemaSnapshot:
    """在线确认授权范围中的每个关系都存在且当前账号可见。"""
    dialect = _profile_dialect(database_type)
    schemas, tables = canonical_allowlist(
        allowed_schemas,
        allowed_tables,
        dialect=dialect,
    )
    snapshot = connector.read_metadata(
        schemas,
        tables,
        timeout_seconds=timeout_seconds,
    )
    ensure_snapshot_matches_allowlist(
        snapshot,
        allowed_schemas=schemas,
        allowed_tables=tables,
    )
    return snapshot


def canonical_allowlist(
    allowed_schemas: tuple[str, ...],
    allowed_tables: tuple[str, ...],
    *,
    dialect: str,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """规范化非空授权范围；非法或系统对象统一安全拒绝。"""
    try:
        scope = normalize_metadata_scope(allowed_schemas, allowed_tables)
    except ValueError:
        raise allowlist_mismatch_error() from None
    schemas = tuple(sorted(set(allowed_schemas)))
    tables = tuple(
        sorted(
            f"{schema_name}.{table_name}"
            for schema_name, table_name in scope.table_pairs
        )
    )
    table_schemas = {
        schema_name for schema_name, _ in scope.table_pairs
    }
    if (
        scope.is_empty
        or len(schemas) != len(allowed_schemas)
        or len(tables) != len(allowed_tables)
        or set(schemas) != table_schemas
        or any(
            _is_system_schema(schema_name, dialect=dialect)
            for schema_name in schemas
        )
    ):
        raise allowlist_mismatch_error()
    return schemas, tables


def ensure_snapshot_matches_allowlist(
    snapshot: SchemaSnapshot,
    *,
    allowed_schemas: tuple[str, ...],
    allowed_tables: tuple[str, ...],
) -> None:
    """确认 Connector 没有遗漏或扩大授权关系集合。"""
    if not isinstance(snapshot, SchemaSnapshot):
        raise allowlist_mismatch_error()
    returned_tables = {
        f"{table.schema_name}.{table.table_name}"
        for table in snapshot.tables
    }
    if (
        tuple(snapshot.schemas) != tuple(allowed_schemas)
        or returned_tables != set(allowed_tables)
        or len(returned_tables) != len(snapshot.tables)
    ):
        raise allowlist_mismatch_error()


def allowlist_mismatch_error() -> DatabaseConnectorError:
    return DatabaseConnectorError(
        DatabaseError(
            sqlstate=None,
            error_type=ErrorType.PERMISSION_DENIED,
            code="DB_ALLOWLIST_MISMATCH",
            retryable=False,
            public_message="The datasource allowlist is invalid.",
        )
    )


def _validate_limits(limits: MetadataLimits) -> None:
    if (
        limits.timeout_seconds <= 0
        or limits.max_relations <= 0
        or limits.max_columns <= 0
        or limits.max_foreign_keys <= 0
    ):
        raise ValueError("metadata limits are invalid")


def _catalog_sql(dialect: str, limit: int) -> str:
    if dialect == "postgres":
        return POSTGRESQL_CATALOG_SQL.format(limit=limit)
    if dialect == "mysql":
        return MYSQL_CATALOG_SQL.format(limit=limit)
    raise ValueError("metadata dialect is unsupported")


def _profile_dialect(database_type: str) -> str:
    if database_type == "postgresql":
        return "postgres"
    if database_type == "mysql":
        return "mysql"
    raise allowlist_mismatch_error()


def _relation_from_row(
    row: list[object],
    *,
    dialect: str,
) -> RelationIdentity | None:
    if len(row) != 3 or not all(isinstance(value, str) for value in row):
        raise ValueError("metadata catalog response is invalid")
    schema_name, relation_name, raw_kind = row
    if _is_system_schema(schema_name, dialect=dialect):
        return None
    normalized_kind = raw_kind.strip().upper()
    if normalized_kind == "VIEW":
        relation_kind: Literal["table", "view"] = "view"
    elif normalized_kind in {"BASE TABLE", "FOREIGN TABLE"}:
        relation_kind = "table"
    else:
        raise ValueError("metadata catalog response is invalid")
    if not schema_name or not relation_name:
        raise ValueError("metadata catalog response is invalid")
    return RelationIdentity(
        schema_name=schema_name,
        relation_name=relation_name,
        relation_kind=relation_kind,
    )


def _is_system_schema(schema_name: str, *, dialect: str) -> bool:
    normalized = schema_name.casefold()
    if dialect == "postgres":
        return (
            normalized in {"pg_catalog", "information_schema"}
            or normalized.startswith("pg_toast")
            or normalized.startswith("pg_temp_")
            or normalized.startswith("pg_toast_temp_")
        )
    if dialect == "mysql":
        return normalized in {
            "information_schema",
            "mysql",
            "performance_schema",
            "sys",
        }
    raise ValueError("metadata dialect is unsupported")


def _ensure_catalog_matches_snapshot(
    relations: tuple[RelationIdentity, ...],
    snapshot: SchemaSnapshot,
) -> None:
    expected = {
        (item.schema_name, item.relation_name): item.relation_kind
        for item in relations
    }
    actual = {
        (table.schema_name, table.table_name): table.relation_kind
        for table in snapshot.tables
    }
    if expected != actual:
        raise ValueError("metadata catalog response is inconsistent")


def _truncate_snapshot(
    snapshot: SchemaSnapshot,
    *,
    limits: MetadataLimits,
    already_truncated: bool,
) -> DiscoveredMetadata:
    selected_tables: list[TableMetadata] = []
    column_count = 0
    column_truncated = False
    for table in snapshot.tables:
        next_column_count = column_count + len(table.columns)
        if next_column_count > limits.max_columns:
            column_truncated = True
            break
        selected_tables.append(table)
        column_count = next_column_count

    selected_table_ids = {
        (table.schema_name, table.table_name) for table in selected_tables
    }
    foreign_keys = tuple(
        foreign_key
        for foreign_key in snapshot.foreign_keys
        if (
            foreign_key.source_schema,
            foreign_key.source_table,
        )
        in selected_table_ids
    )
    foreign_key_truncated = len(foreign_keys) > limits.max_foreign_keys
    foreign_keys = foreign_keys[: limits.max_foreign_keys]

    trimmed_snapshot = build_schema_snapshot(
        tables=tuple(selected_tables),
        primary_keys=tuple(
            key
            for key in snapshot.primary_keys
            if (key.schema_name, key.table_name) in selected_table_ids
        ),
        foreign_keys=foreign_keys,
        unique_constraints=tuple(
            constraint
            for constraint in snapshot.unique_constraints
            if (
                constraint.schema_name,
                constraint.table_name,
            )
            in selected_table_ids
        ),
        unique_indexes=tuple(
            index
            for index in snapshot.unique_indexes
            if (index.schema_name, index.table_name) in selected_table_ids
        ),
    )
    relations = tuple(
        RelationIdentity(
            schema_name=table.schema_name,
            relation_name=table.table_name,
            relation_kind=(
                "view" if table.relation_kind == "view" else "table"
            ),
        )
        for table in trimmed_snapshot.tables
    )
    return DiscoveredMetadata(
        snapshot=trimmed_snapshot,
        relations=relations,
        truncated=(
            already_truncated
            or column_truncated
            or foreign_key_truncated
        ),
    )
