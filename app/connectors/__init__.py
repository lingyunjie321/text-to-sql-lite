"""Database connector contracts."""

from app.connectors.metadata import (
    ColumnMetadata,
    ForeignKeyMetadata,
    MetadataScope,
    PrimaryKeyMetadata,
    SchemaSnapshot,
    TableMetadata,
    UniqueConstraintMetadata,
    UniqueIndexMetadata,
    build_schema_snapshot,
    empty_schema_snapshot,
    normalize_metadata_scope,
)
from app.connectors.postgresql import PostgreSQLConnector

__all__ = [
    "ColumnMetadata",
    "ForeignKeyMetadata",
    "MetadataScope",
    "PostgreSQLConnector",
    "PrimaryKeyMetadata",
    "SchemaSnapshot",
    "TableMetadata",
    "UniqueConstraintMetadata",
    "UniqueIndexMetadata",
    "build_schema_snapshot",
    "empty_schema_snapshot",
    "normalize_metadata_scope",
]
