"""Parameterised metadata queries for StarRocks using ``information_schema``.

StarRocks is MySQL-protocol compatible but has limitations:
- No referential integrity / foreign-key constraints.
- Primary keys available via the PRIMARY KEY table model (StarRocks 3.x).
- Unique indexes are implemented through the PRIMARY KEY model.

All queries accept two positional parameters for schema and table
filtering (``%s`` placeholders, matching the pymysql driver).
"""

# ── Raw SQL templates (placeholder count resolved at runtime) ─────

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
JOIN INFORMATION_SCHEMA.TABLES AS t
  ON t.TABLE_SCHEMA = c.TABLE_SCHEMA
 AND t.TABLE_NAME = c.TABLE_NAME
 AND t.TABLE_TYPE = 'BASE TABLE'
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

# StarRocks does **not** support traditional foreign-key constraints.
# The query returns an empty result set while keeping the same column
# layout as MySQL so that the mapping layer works unchanged.
_FOREIGN_KEYS_RAW = """
SELECT
    NULL AS constraint_name,
    NULL AS source_schema,
    NULL AS source_table,
    NULL AS source_column,
    NULL AS target_schema,
    NULL AS target_table,
    NULL AS target_column,
    NULL AS column_position
FROM INFORMATION_SCHEMA.TABLES
WHERE TABLE_SCHEMA IN ({schema_placeholders})
  AND TABLE_NAME IN ({table_placeholders})
  AND 1 = 0
"""

# StarRocks unique keys are implemented via the PRIMARY KEY table model;
# the UNIQUE constraint type may not be populated in TABLE_CONSTRAINTS.
# This query returns an empty result set.
_UNIQUE_INDEXES_RAW = """
SELECT
    tc.CONSTRAINT_NAME AS index_name,
    tc.TABLE_SCHEMA AS schema_name,
    tc.TABLE_NAME AS table_name,
    NULL AS columns,
    NULL AS definition,
    NULL AS predicate
FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS AS tc
WHERE tc.CONSTRAINT_TYPE = 'UNIQUE'
  AND tc.TABLE_SCHEMA IN ({schema_placeholders})
  AND tc.TABLE_NAME IN ({table_placeholders})
  AND 1 = 0
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
    """Build parameterised metadata queries for StarRocks with *count*
    schema/table placeholders."""
    return _finalise_sql(count)


# ── Default queries (single schema / single table) ──────────────

_default_queries = build_metadata_queries(1)

TABLE_COLUMNS_SQL: str = _default_queries["table_columns"]
PRIMARY_KEYS_SQL: str = _default_queries["primary_keys"]
FOREIGN_KEYS_SQL: str = _default_queries["foreign_keys"]
UNIQUE_INDEXES_SQL: str = _default_queries["unique_indexes"]
