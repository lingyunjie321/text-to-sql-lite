"""方言档案：按数据库方言聚合元数据查询 SQL、连接默认值与驱动信息。

每个受支持的方言（PostgreSQL / MySQL / StarRocks）对应一个工厂函数，
返回不可变的 :class:`DialectProfile`，供连接器层与校验层按需取用。
"""

from __future__ import annotations

from dataclasses import dataclass

from app.connectors.types import DialectName


@dataclass(frozen=True, slots=True)
class DialectProfile:
    """Configuration profile for a single SQL dialect.

    Bundles metadata query SQL, dialect identifiers, and connection
    defaults used by the connector layer.
    """

    name: DialectName
    """Canonical short name (``"postgres"``, ``"mysql"``, ``"starrocks"``)."""

    sqlglot_dialect: str
    """Dialect string recognised by `sqlglot <https://sqlglot.com/>`_."""

    # Metadata queries — each key is a query label:
    #   "table_columns", "primary_keys", "foreign_keys", "unique_indexes"
    metadata_queries: dict[str, str]
    """Parameterised SQL for reading schema metadata.

    Expected keys:
    * ``table_columns``       — columns + types + nullability
    * ``primary_keys``        — primary-key constraint definitions
    * ``foreign_keys``        — foreign-key constraint definitions
    * ``unique_indexes``      — unique index definitions
    """

    connection_test_sql: str
    """Lightweight SQL for connectivity checks (e.g. ``"SELECT 1"``)."""

    default_port: int

    supported_drivers: tuple[str, ...]
    """Driver package names the connector layer may use, e.g.
    ``("psycopg",)`` or ``("pymysql",)``."""


# ── Factory functions ────────────────────────────────────────────


def postgresql_dialect() -> DialectProfile:
    """Return the :class:`DialectProfile` for PostgreSQL."""
    from app.connectors.metadata_queries import (
        FOREIGN_KEYS_SQL,
        KEY_CONSTRAINTS_SQL,
        TABLE_COLUMNS_SQL,
        UNIQUE_INDEXES_SQL,
    )

    return DialectProfile(
        name="postgres",
        sqlglot_dialect="postgres",
        metadata_queries={
            "table_columns": TABLE_COLUMNS_SQL,
            "primary_keys": KEY_CONSTRAINTS_SQL,
            "foreign_keys": FOREIGN_KEYS_SQL,
            "unique_indexes": UNIQUE_INDEXES_SQL,
        },
        connection_test_sql="SELECT 1",
        default_port=5432,
        supported_drivers=("psycopg",),
    )


def mysql_dialect() -> DialectProfile:
    """Return the :class:`DialectProfile` for MySQL."""
    from app.connectors.metadata_queries_mysql import (
        FOREIGN_KEYS_SQL,
        PRIMARY_KEYS_SQL,
        TABLE_COLUMNS_SQL,
        UNIQUE_INDEXES_SQL,
    )

    return DialectProfile(
        name="mysql",
        sqlglot_dialect="mysql",
        metadata_queries={
            "table_columns": TABLE_COLUMNS_SQL,
            "primary_keys": PRIMARY_KEYS_SQL,
            "foreign_keys": FOREIGN_KEYS_SQL,
            "unique_indexes": UNIQUE_INDEXES_SQL,
        },
        connection_test_sql="SELECT 1",
        default_port=3306,
        supported_drivers=("pymysql", "mysql-connector-python"),
    )


def starrocks_dialect() -> DialectProfile:
    """Return the :class:`DialectProfile` for StarRocks."""
    from app.connectors.metadata_queries_starrocks import (
        FOREIGN_KEYS_SQL,
        PRIMARY_KEYS_SQL,
        TABLE_COLUMNS_SQL,
        UNIQUE_INDEXES_SQL,
    )

    return DialectProfile(
        name="starrocks",
        sqlglot_dialect="mysql",  # StarRocks SQL is MySQL-compatible in SQLGlot
        metadata_queries={
            "table_columns": TABLE_COLUMNS_SQL,
            "primary_keys": PRIMARY_KEYS_SQL,
            "foreign_keys": FOREIGN_KEYS_SQL,
            "unique_indexes": UNIQUE_INDEXES_SQL,
        },
        connection_test_sql="SELECT 1",
        default_port=9030,
        supported_drivers=("pymysql",),
    )
