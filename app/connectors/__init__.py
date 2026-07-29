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
from app.connectors.view_semantics import (
    FrozenSemanticConnector,
    ViewSemanticManifest,
    load_view_semantic_manifest,
)

__all__ = [
    "ColumnMetadata",
    "ForeignKeyMetadata",
    "FrozenSemanticConnector",
    "MetadataScope",
    "PostgreSQLConnector",
    "PrimaryKeyMetadata",
    "SchemaSnapshot",
    "TableMetadata",
    "UniqueConstraintMetadata",
    "UniqueIndexMetadata",
    "ViewSemanticManifest",
    "build_schema_snapshot",
    "empty_schema_snapshot",
    "load_view_semantic_manifest",
    "normalize_metadata_scope",
]
