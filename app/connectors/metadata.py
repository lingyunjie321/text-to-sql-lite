"""元数据模型与 schema 快照构建。

定义表、列、主键、外键、唯一约束/索引等不可变元数据结构，以及把
授权范围规范化为 :class:`MetadataScope`、把元数据组装为带内容摘要
（``schema_version``）的 :class:`SchemaSnapshot` 的构建函数。快照是
SQL 校验与 schema linking 的唯一元数据来源。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, replace


@dataclass(frozen=True, slots=True)
class ColumnMetadata:
    """单个列的元数据：名称、序号位置、类型、可空性与注释。"""

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
    """单张表/视图的元数据：关系类型、注释与有序列集合。"""

    schema_name: str
    table_name: str
    relation_kind: str
    comment: str | None
    columns: tuple[ColumnMetadata, ...]
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PrimaryKeyMetadata:
    """主键约束：约束名、所属表与有序列名。"""

    constraint_name: str
    schema_name: str
    table_name: str
    columns: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ForeignKeyMetadata:
    """外键约束：源表列与目标表列的有序对应关系。"""

    constraint_name: str
    source_schema: str
    source_table: str
    source_columns: tuple[str, ...]
    target_schema: str
    target_table: str
    target_columns: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class UniqueConstraintMetadata:
    """唯一约束：约束名、所属表与有序列名。"""

    constraint_name: str
    schema_name: str
    table_name: str
    columns: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class UniqueIndexMetadata:
    """唯一索引：索引名、有序列名、定义文本与可选谓词。"""

    index_name: str
    schema_name: str
    table_name: str
    columns: tuple[str, ...]
    definition: str
    predicate: str | None


@dataclass(frozen=True, slots=True)
class SchemaSnapshot:
    """授权范围内数据库结构的不可变快照。

    ``schema_version`` 为全部元数据的规范化 SHA-256 摘要，任何结构
    变化都会改变该值，用于缓存失效与检索版本契约校验。
    """

    schemas: tuple[str, ...]
    tables: tuple[TableMetadata, ...]
    primary_keys: tuple[PrimaryKeyMetadata, ...]
    foreign_keys: tuple[ForeignKeyMetadata, ...]
    unique_constraints: tuple[UniqueConstraintMetadata, ...]
    unique_indexes: tuple[UniqueIndexMetadata, ...]
    schema_version: str


@dataclass(frozen=True, slots=True)
class MetadataScope:
    """规范化后的元数据读取范围。

    ``schemas`` 为去重排序后的 schema 列表；``table_pairs`` 为授权
    范围内实际存在的 ``(schema, table)`` 对（已过滤掉不在授权
    schema 中的表）。
    """

    schemas: tuple[str, ...]
    table_pairs: tuple[tuple[str, str], ...]

    @property
    def is_empty(self) -> bool:
        """范围为真（无任何可读取的表对）时为 ``True``。"""
        return not self.schemas or not self.table_pairs

    @property
    def schema_parameters(self) -> list[str]:
        """与 ``table_pairs`` 对齐的 schema 参数序列（用于 SQL 占位符）。"""
        return [schema for schema, _ in self.table_pairs]

    @property
    def table_parameters(self) -> list[str]:
        """与 ``table_pairs`` 对齐的表名参数序列（用于 SQL 占位符）。"""
        return [table for _, table in self.table_pairs]


def normalize_metadata_scope(
    allowed_schemas: tuple[str, ...],
    allowed_tables: tuple[str, ...],
) -> MetadataScope:
    """把授权 schema/表列表规范化为 :class:`MetadataScope`。

    ``allowed_tables`` 必须为 ``schema.table`` 形式；不在授权 schema
    中的表会被丢弃。空标识符或未限定表名抛出 :class:`ValueError`。
    """
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
    """把各类元数据组装为规范化 :class:`SchemaSnapshot`。

    所有集合按固定规则排序（表按名称、列按序号位置），随后对规范化
    JSON 取 SHA-256 得到确定性的 ``schema_version``。
    """
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
    """返回不含任何表的空快照（用于授权范围为空的场景）。"""
    return build_schema_snapshot(
        tables=(),
        primary_keys=(),
        foreign_keys=(),
        unique_constraints=(),
        unique_indexes=(),
    )
