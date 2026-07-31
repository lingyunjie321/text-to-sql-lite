"""Parameterised metadata queries for MySQL using ``information_schema``.

All queries accept two positional parameters for schema and table
filtering::

    cursor.execute(SQL, (schema_list, table_list))

Where *schema_list* and *table_list* are ``tuple[str, ...]``.  The
driver's parameter substitution handles ``%s`` placeholders correctly
for the ``IN (…)`` clauses.

.. note::

    MySQL's ``%s`` placeholder is not compatible with PostgreSQL's
    ``%s`` — the connector is responsible for mapping the parameter
    style.

The SQL templates and the placeholder-rendering machinery live in
:mod:`app.connectors.metadata_queries_mysql_family`; this module only
binds the MySQL dialect declarations to the public query-building API.
"""

from app.connectors.metadata_queries_mysql_family import (
    MYSQL_FOREIGN_KEYS_RAW,
    MYSQL_PRIMARY_KEYS_RAW,
    MYSQL_TABLE_COLUMNS_RAW,
    MYSQL_UNIQUE_INDEXES_RAW,
    build_family_queries,
)


def build_metadata_queries(count: int) -> dict[str, str]:
    """Build parameterised metadata queries for MySQL with *count*
    schema/table placeholders."""
    return build_family_queries(
        count,
        table_columns_raw=MYSQL_TABLE_COLUMNS_RAW,
        primary_keys_raw=MYSQL_PRIMARY_KEYS_RAW,
        foreign_keys_raw=MYSQL_FOREIGN_KEYS_RAW,
        unique_indexes_raw=MYSQL_UNIQUE_INDEXES_RAW,
    )


# ── Default queries (single schema / single table) ──────────────


_default_queries = build_metadata_queries(1)

TABLE_COLUMNS_SQL: str = _default_queries["table_columns"]
PRIMARY_KEYS_SQL: str = _default_queries["primary_keys"]
FOREIGN_KEYS_SQL: str = _default_queries["foreign_keys"]
UNIQUE_INDEXES_SQL: str = _default_queries["unique_indexes"]
