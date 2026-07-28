from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, replace


@dataclass(frozen=True, slots=True)
class ColumnMetadata:
    schema_name: str
    table_name: str
    column_name: str
    ordinal_position: int
    data_type: str
    formatted_type: str
    nullable: bool
    comment: str | None
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class TableMetadata:
    schema_name: str
    table_name: str
    relation_kind: str
    comment: str | None
    columns: tuple[ColumnMetadata, ...]
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PrimaryKeyMetadata:
    constraint_name: str
    schema_name: str
    table_name: str
    columns: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ForeignKeyMetadata:
    constraint_name: str
    source_schema: str
    source_table: str
    source_columns: tuple[str, ...]
    target_schema: str
    target_table: str
    target_columns: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class UniqueConstraintMetadata:
    constraint_name: str
    schema_name: str
    table_name: str
    columns: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class UniqueIndexMetadata:
    index_name: str
    schema_name: str
    table_name: str
    columns: tuple[str, ...]
    definition: str
    predicate: str | None


@dataclass(frozen=True, slots=True)
class SchemaSnapshot:
    schemas: tuple[str, ...]
    tables: tuple[TableMetadata, ...]
    primary_keys: tuple[PrimaryKeyMetadata, ...]
    foreign_keys: tuple[ForeignKeyMetadata, ...]
    unique_constraints: tuple[UniqueConstraintMetadata, ...]
    unique_indexes: tuple[UniqueIndexMetadata, ...]
    schema_version: str


@dataclass(frozen=True, slots=True)
class MetadataScope:
    schemas: tuple[str, ...]
    table_pairs: tuple[tuple[str, str], ...]

    @property
    def is_empty(self) -> bool:
        return not self.schemas or not self.table_pairs

    @property
    def schema_parameters(self) -> list[str]:
        return [schema for schema, _ in self.table_pairs]

    @property
    def table_parameters(self) -> list[str]:
        return [table for _, table in self.table_pairs]


def normalize_metadata_scope(
    allowed_schemas: tuple[str, ...],
    allowed_tables: tuple[str, ...],
) -> MetadataScope:
    if any(not schema.strip() for schema in allowed_schemas):
        raise ValueError("metadata scope contains an empty identifier")
    if not allowed_schemas or not allowed_tables:
        return MetadataScope(
            schemas=tuple(sorted(set(allowed_schemas))),
            table_pairs=(),
        )

    schemas = tuple(sorted(set(allowed_schemas)))
    schema_set = set(schemas)
    table_pairs: set[tuple[str, str]] = set()
    for qualified_table in allowed_tables:
        if not qualified_table.strip():
            raise ValueError("metadata scope contains an empty identifier")
        if "." not in qualified_table:
            raise ValueError("allowed table must be schema-qualified")
        schema_name, table_name = qualified_table.split(".", 1)
        if not schema_name.strip() or not table_name.strip():
            raise ValueError("metadata scope contains an empty identifier")
        if schema_name in schema_set:
            table_pairs.add((schema_name, table_name))

    return MetadataScope(
        schemas=schemas,
        table_pairs=tuple(sorted(table_pairs)),
    )


def build_schema_snapshot(
    *,
    tables: tuple[TableMetadata, ...],
    primary_keys: tuple[PrimaryKeyMetadata, ...],
    foreign_keys: tuple[ForeignKeyMetadata, ...],
    unique_constraints: tuple[UniqueConstraintMetadata, ...],
    unique_indexes: tuple[UniqueIndexMetadata, ...],
) -> SchemaSnapshot:
    canonical_tables = tuple(
        replace(
            table,
            columns=tuple(
                sorted(
                    table.columns,
                    key=lambda column: column.ordinal_position,
                )
            ),
        )
        for table in sorted(
            tables,
            key=lambda item: (item.schema_name, item.table_name),
        )
    )
    canonical_primary_keys = tuple(
        sorted(
            primary_keys,
            key=lambda item: (
                item.schema_name,
                item.table_name,
                item.constraint_name,
            ),
        )
    )
    canonical_foreign_keys = tuple(
        sorted(
            foreign_keys,
            key=lambda item: (
                item.source_schema,
                item.source_table,
                item.constraint_name,
                item.target_schema,
                item.target_table,
            ),
        )
    )
    canonical_unique_constraints = tuple(
        sorted(
            unique_constraints,
            key=lambda item: (
                item.schema_name,
                item.table_name,
                item.constraint_name,
            ),
        )
    )
    canonical_unique_indexes = tuple(
        sorted(
            unique_indexes,
            key=lambda item: (
                item.schema_name,
                item.table_name,
                item.index_name,
            ),
        )
    )
    schemas = tuple(
        sorted({table.schema_name for table in canonical_tables})
    )
    canonical_data = {
        "schemas": schemas,
        "tables": tuple(asdict(table) for table in canonical_tables),
        "primary_keys": tuple(
            asdict(primary_key)
            for primary_key in canonical_primary_keys
        ),
        "foreign_keys": tuple(
            asdict(foreign_key)
            for foreign_key in canonical_foreign_keys
        ),
        "unique_constraints": tuple(
            asdict(constraint)
            for constraint in canonical_unique_constraints
        ),
        "unique_indexes": tuple(
            asdict(index)
            for index in canonical_unique_indexes
        ),
    }
    payload = json.dumps(
        canonical_data,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return SchemaSnapshot(
        schemas=schemas,
        tables=canonical_tables,
        primary_keys=canonical_primary_keys,
        foreign_keys=canonical_foreign_keys,
        unique_constraints=canonical_unique_constraints,
        unique_indexes=canonical_unique_indexes,
        schema_version=hashlib.sha256(payload).hexdigest(),
    )


def empty_schema_snapshot() -> SchemaSnapshot:
    return build_schema_snapshot(
        tables=(),
        primary_keys=(),
        foreign_keys=(),
        unique_constraints=(),
        unique_indexes=(),
    )
