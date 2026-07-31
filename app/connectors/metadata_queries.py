"""PostgreSQL 元数据查询：基于 ``pg_catalog`` 的参数化 SQL。

所有查询通过 ``AUTHORIZED_CTE`` 把授权范围（schema 列表、表列表）
作为数组参数注入，只读取授权范围内的表列、键约束、外键与唯一索引
元数据。占位符为 psycopg 的 ``%s`` 风格。
"""

AUTHORIZED_CTE = """
WITH authorized(schema_name, table_name) AS (
    SELECT *
    FROM unnest(%s::text[], %s::text[])
)
"""


TABLE_COLUMNS_SQL = AUTHORIZED_CTE + """
SELECT
    namespace.nspname AS schema_name,
    relation.relname AS table_name,
    CASE relation.relkind
        WHEN 'r' THEN 'table'
        ELSE 'partitioned_table'
    END AS relation_kind,
    obj_description(relation.oid, 'pg_class') AS table_comment,
    attribute.attname AS column_name,
    attribute.attnum AS ordinal_position,
    type.typname AS data_type,
    format_type(attribute.atttypid, attribute.atttypmod) AS formatted_type,
    NOT attribute.attnotnull AS nullable,
    col_description(relation.oid, attribute.attnum) AS column_comment
FROM pg_catalog.pg_namespace AS namespace
JOIN pg_catalog.pg_class AS relation
  ON relation.relnamespace = namespace.oid
JOIN authorized AS auth
  ON auth.schema_name = namespace.nspname
 AND auth.table_name = relation.relname
JOIN pg_catalog.pg_attribute AS attribute
  ON attribute.attrelid = relation.oid
JOIN pg_catalog.pg_type AS type
  ON type.oid = attribute.atttypid
WHERE relation.relkind IN ('r', 'p')
  AND attribute.attnum > 0
  AND NOT attribute.attisdropped
ORDER BY namespace.nspname, relation.relname, attribute.attnum
"""


KEY_CONSTRAINTS_SQL = AUTHORIZED_CTE + """
SELECT
    constraint_record.conname AS constraint_name,
    constraint_record.contype AS constraint_kind,
    namespace.nspname AS schema_name,
    relation.relname AS table_name,
    attribute.attname AS column_name,
    key_column.position AS column_position
FROM pg_catalog.pg_constraint AS constraint_record
JOIN pg_catalog.pg_class AS relation
  ON relation.oid = constraint_record.conrelid
JOIN pg_catalog.pg_namespace AS namespace
  ON namespace.oid = relation.relnamespace
JOIN authorized AS auth
  ON auth.schema_name = namespace.nspname
 AND auth.table_name = relation.relname
CROSS JOIN LATERAL unnest(constraint_record.conkey)
  WITH ORDINALITY AS key_column(attnum, position)
JOIN pg_catalog.pg_attribute AS attribute
  ON attribute.attrelid = relation.oid
 AND attribute.attnum = key_column.attnum
WHERE relation.relkind IN ('r', 'p')
  AND constraint_record.contype IN ('p', 'u')
ORDER BY
    namespace.nspname,
    relation.relname,
    constraint_record.conname,
    key_column.position
"""


FOREIGN_KEYS_SQL = AUTHORIZED_CTE + """
SELECT
    constraint_record.conname AS constraint_name,
    source_namespace.nspname AS source_schema,
    source_relation.relname AS source_table,
    source_attribute.attname AS source_column,
    target_namespace.nspname AS target_schema,
    target_relation.relname AS target_table,
    target_attribute.attname AS target_column,
    source_key.position AS column_position
FROM pg_catalog.pg_constraint AS constraint_record
JOIN pg_catalog.pg_class AS source_relation
  ON source_relation.oid = constraint_record.conrelid
JOIN pg_catalog.pg_namespace AS source_namespace
  ON source_namespace.oid = source_relation.relnamespace
JOIN authorized AS source_auth
  ON source_auth.schema_name = source_namespace.nspname
 AND source_auth.table_name = source_relation.relname
JOIN pg_catalog.pg_class AS target_relation
  ON target_relation.oid = constraint_record.confrelid
JOIN pg_catalog.pg_namespace AS target_namespace
  ON target_namespace.oid = target_relation.relnamespace
JOIN authorized AS target_auth
  ON target_auth.schema_name = target_namespace.nspname
 AND target_auth.table_name = target_relation.relname
CROSS JOIN LATERAL unnest(constraint_record.conkey)
  WITH ORDINALITY AS source_key(attnum, position)
JOIN LATERAL unnest(constraint_record.confkey)
  WITH ORDINALITY AS target_key(attnum, position)
  ON target_key.position = source_key.position
JOIN pg_catalog.pg_attribute AS source_attribute
  ON source_attribute.attrelid = source_relation.oid
 AND source_attribute.attnum = source_key.attnum
JOIN pg_catalog.pg_attribute AS target_attribute
  ON target_attribute.attrelid = target_relation.oid
 AND target_attribute.attnum = target_key.attnum
WHERE constraint_record.contype = 'f'
  AND source_relation.relkind IN ('r', 'p')
  AND target_relation.relkind IN ('r', 'p')
ORDER BY
    source_namespace.nspname,
    source_relation.relname,
    constraint_record.conname,
    source_key.position
"""


UNIQUE_INDEXES_SQL = AUTHORIZED_CTE + """
SELECT
    index_relation.relname AS index_name,
    namespace.nspname AS schema_name,
    relation.relname AS table_name,
    array_agg(attribute.attname ORDER BY index_key.position) AS columns,
    pg_get_indexdef(index_record.indexrelid) AS definition,
    pg_get_expr(index_record.indpred, index_record.indrelid) AS predicate
FROM pg_catalog.pg_index AS index_record
JOIN pg_catalog.pg_class AS relation
  ON relation.oid = index_record.indrelid
JOIN pg_catalog.pg_namespace AS namespace
  ON namespace.oid = relation.relnamespace
JOIN authorized AS auth
  ON auth.schema_name = namespace.nspname
 AND auth.table_name = relation.relname
JOIN pg_catalog.pg_class AS index_relation
  ON index_relation.oid = index_record.indexrelid
CROSS JOIN LATERAL unnest(index_record.indkey)
  WITH ORDINALITY AS index_key(attnum, position)
JOIN pg_catalog.pg_attribute AS attribute
  ON attribute.attrelid = relation.oid
 AND attribute.attnum = index_key.attnum
WHERE relation.relkind IN ('r', 'p')
  AND index_record.indisunique
  AND NOT index_record.indisprimary
  AND NOT EXISTS (
      SELECT 1
      FROM pg_catalog.pg_constraint AS constraint_record
      WHERE constraint_record.conindid = index_record.indexrelid
  )
  AND NOT EXISTS (
      SELECT 1
      FROM unnest(index_record.indkey) AS expression_key(attnum)
      WHERE expression_key.attnum = 0
  )
GROUP BY
    index_relation.relname,
    namespace.nspname,
    relation.relname,
    index_record.indexrelid,
    index_record.indrelid,
    index_record.indpred
ORDER BY namespace.nspname, relation.relname, index_relation.relname
"""
