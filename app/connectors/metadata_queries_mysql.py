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
"""

# Number of ``%s`` placeholders is controlled at runtime via
# :func:`_build_in_clause`.  The SQL fragments below use the
# ``{schema_placeholders}`` / ``{table_placeholders}`` formatting
# keys and are finalised by the connector before execution.

_TABLE_COLUMNS_RAW = """
SELECT
    c.TABLE_SCHEMA AS schema_name,
    c.TABLE_NAME AS table_name,
    'table' AS relation_kind,
    NULL AS table_comment,
    c.COLUMN_NAME AS column_name,
    c.ORDINAL_POSITION AS ordinal_position,
    c.DATA_TYPE AS data_type,
    c.COLUMN_TYPE AS formatted_type,
    CASE WHEN c.IS_NULLABLE = 'YES' THEN TRUE ELSE FALSE END AS nullable,
    c.COLUMN_COMMENT AS column_comment
FROM INFORMATION_SCHEMA.COLUMNS AS c
WHERE c.TABLE_SCHEMA IN ({schema_placeholders})
  AND c.TABLE_NAME IN ({table_placeholders})
ORDER BY c.TABLE_SCHEMA, c.TABLE_NAME, c.ORDINAL_POSITION
"""

_PRIMARY_KEYS_RAW = """
SELECT
    k.CONSTRAINT_NAME AS constraint_name,
    'PRIMARY KEY' AS constraint_type,
    k.TABLE_SCHEMA AS schema_name,
    k.TABLE_NAME AS table_name,
    k.COLUMN_NAME AS column_name,
    k.ORDINAL_POSITION AS column_position
FROM INFORMATION_SCHEMA.KEY_COLUMN_USAGE AS k
JOIN INFORMATION_SCHEMA.TABLE_CONSTRAINTS AS tc
  ON tc.CONSTRAINT_NAME = k.CONSTRAINT_NAME
 AND tc.TABLE_SCHEMA = k.TABLE_SCHEMA
 AND tc.TABLE_NAME = k.TABLE_NAME
 AND tc.CONSTRAINT_TYPE = 'PRIMARY KEY'
WHERE k.TABLE_SCHEMA IN ({schema_placeholders})
  AND k.TABLE_NAME IN ({table_placeholders})
ORDER BY k.TABLE_SCHEMA, k.TABLE_NAME, k.CONSTRAINT_NAME, k.ORDINAL_POSITION
"""

_FOREIGN_KEYS_RAW = """
SELECT
    k.CONSTRAINT_NAME AS constraint_name,
    k.TABLE_SCHEMA AS source_schema,
    k.TABLE_NAME AS source_table,
    k.COLUMN_NAME AS source_column,
    k.REFERENCED_TABLE_SCHEMA AS target_schema,
    k.REFERENCED_TABLE_NAME AS target_table,
    k.REFERENCED_COLUMN_NAME AS target_column,
    k.ORDINAL_POSITION AS column_position
FROM INFORMATION_SCHEMA.KEY_COLUMN_USAGE AS k
JOIN INFORMATION_SCHEMA.REFERENTIAL_CONSTRAINTS AS rc
  ON rc.CONSTRAINT_NAME = k.CONSTRAINT_NAME
 AND rc.CONSTRAINT_SCHEMA = k.CONSTRAINT_SCHEMA
 AND rc.TABLE_NAME = k.TABLE_NAME
WHERE k.TABLE_SCHEMA IN ({schema_placeholders})
  AND k.TABLE_NAME IN ({table_placeholders})
  AND k.REFERENCED_TABLE_SCHEMA IS NOT NULL
ORDER BY k.TABLE_SCHEMA, k.TABLE_NAME, k.CONSTRAINT_NAME, k.ORDINAL_POSITION
"""

_UNIQUE_INDEXES_RAW = """
SELECT
    tc.CONSTRAINT_NAME AS index_name,
    tc.TABLE_SCHEMA AS schema_name,
    tc.TABLE_NAME AS table_name,
    GROUP_CONCAT(k.COLUMN_NAME ORDER BY k.ORDINAL_POSITION SEPARATOR ',') AS columns,
    NULL AS definition,
    NULL AS predicate
FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS AS tc
JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE AS k
  ON k.CONSTRAINT_NAME = tc.CONSTRAINT_NAME
 AND k.TABLE_SCHEMA = tc.TABLE_SCHEMA
 AND k.TABLE_NAME = tc.TABLE_NAME
WHERE tc.CONSTRAINT_TYPE = 'UNIQUE'
  AND tc.TABLE_SCHEMA IN ({schema_placeholders})
  AND tc.TABLE_NAME IN ({table_placeholders})
GROUP BY tc.CONSTRAINT_NAME, tc.TABLE_SCHEMA, tc.TABLE_NAME
ORDER BY tc.TABLE_SCHEMA, tc.TABLE_NAME, tc.CONSTRAINT_NAME
"""


def _build_in_clause(count: int) -> str:
    """Return ``%s, %s, ...`` with *count* placeholders."""
    return ", ".join(["%s"] * max(count, 1))


def _finalise_sql(count: int) -> dict[str, str]:
    placeholders_schema = _build_in_clause(count)
    placeholders_table = _build_in_clause(count)
    return {
        "table_columns": _TABLE_COLUMNS_RAW.format(
            schema_placeholders=placeholders_schema,
            table_placeholders=placeholders_table,
        ),
        "primary_keys": _PRIMARY_KEYS_RAW.format(
            schema_placeholders=placeholders_schema,
            table_placeholders=placeholders_table,
        ),
        "foreign_keys": _FOREIGN_KEYS_RAW.format(
            schema_placeholders=placeholders_schema,
            table_placeholders=placeholders_table,
        ),
        "unique_indexes": _UNIQUE_INDEXES_RAW.format(
            schema_placeholders=placeholders_schema,
            table_placeholders=placeholders_table,
        ),
    }


def build_metadata_queries(count: int) -> dict[str, str]:
    """Build parameterised metadata queries for MySQL with *count*
    schema/table placeholders."""
    return _finalise_sql(count)


# ── Default queries (single schema / single table) ──────────────


_default_queries = build_metadata_queries(1)

TABLE_COLUMNS_SQL: str = _default_queries["table_columns"]
PRIMARY_KEYS_SQL: str = _default_queries["primary_keys"]
FOREIGN_KEYS_SQL: str = _default_queries["foreign_keys"]
UNIQUE_INDEXES_SQL: str = _default_queries["unique_indexes"]
