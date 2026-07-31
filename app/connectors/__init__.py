"""Pluggable database connector contracts.

Supports PostgreSQL, MySQL, and StarRocks backends through a common
:class:`DatabaseConnector` protocol and per-dialect connector classes.
"""

from app.connectors.base import DatabaseConnector
from app.connectors.dialect import (
    DialectProfile,
    mysql_dialect,
    postgresql_dialect,
    starrocks_dialect,
)
from app.connectors.errors import (
    DatabaseConnectorError,
    DatabaseError,
    ErrorType,
    PostgreSQLConnectorError,
    classify_mysql_error_code,
    classify_sqlstate,
    normalize_database_error,
)
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
from app.connectors.models import (
    ExecutionResult,
    ResultColumn,
    normalize_value as _legacy_normalize_value,
)
from app.connectors.postgresql import PostgreSQLConnector
from app.connectors.mysql import MySQLConnector
from app.connectors.starrocks import StarRocksConnector
from app.connectors.registry import ConnectorRegistry
from app.connectors.types import (
    DialectName,
    normalize_value,
)
from app.connectors.view_semantics import (
    FrozenSemanticConnector,
    ViewSemanticManifest,
    load_view_semantic_manifest,
)

__all__ = [
    # Protocol & dialogs
    "DatabaseConnector",
    "DialectProfile",
    "DialectName",
    "postgresql_dialect",
    "mysql_dialect",
    "starrocks_dialect",
    # Connectors
    "ConnectorRegistry",
    "PostgreSQLConnector",
    "MySQLConnector",
    "StarRocksConnector",
    "FrozenSemanticConnector",
    "ViewSemanticManifest",
    "load_view_semantic_manifest",
    # Errors
    "DatabaseConnectorError",
    "PostgreSQLConnectorError",
    "DatabaseError",
    "ErrorType",
    "classify_sqlstate",
    "classify_mysql_error_code",
    "normalize_database_error",
    # Metadata
    "build_schema_snapshot",
    "ColumnMetadata",
    "empty_schema_snapshot",
    "ForeignKeyMetadata",
    "MetadataScope",
    "normalize_metadata_scope",
    "PrimaryKeyMetadata",
    "SchemaSnapshot",
    "TableMetadata",
    "UniqueConstraintMetadata",
    "UniqueIndexMetadata",
    # Models
    "ExecutionResult",
    "ResultColumn",
    "normalize_value",
]
