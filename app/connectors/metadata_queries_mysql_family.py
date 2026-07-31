"""MySQL 协议家族的 ``information_schema`` 元数据查询共享实现。

MySQL 与 StarRocks 均通过 MySQL 协议暴露 ``information_schema``，两者的
元数据查询仅在方言细节上不同（例如 StarRocks 无外键约束、表列查询需过滤
``BASE TABLE``）。本模块集中存放：

* 占位符渲染机制（``build_in_clause`` / ``build_family_queries``）；
* MySQL 基准 SQL 模板（StarRocks 复用其中的主键模板）。

各方言模块（``metadata_queries_mysql`` / ``metadata_queries_starrocks``）
只声明自己的模板差异，并委托本模块完成 ``{schema_placeholders}`` /
``{table_placeholders}`` 占位符渲染，对外暴露的查询字典结构保持一致::

    {
        "table_columns": ...,
        "primary_keys": ...,
        "foreign_keys": ...,
        "unique_indexes": ...,
    }

.. note::

    MySQL 协议驱动的 ``%s`` 占位符与 PostgreSQL 的 ``%s`` 语义不同，
    参数风格由连接器负责映射。
"""

# ── MySQL 基准 SQL 模板（占位符数量在渲染期确定）────────────────


MYSQL_TABLE_COLUMNS_RAW = """
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

# StarRocks 的 ``information_schema`` 对主键约束的暴露方式与 MySQL
# 一致（PRIMARY KEY 表模型），因此两个方言共用同一份模板。
MYSQL_PRIMARY_KEYS_RAW = """
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

MYSQL_FOREIGN_KEYS_RAW = """
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

MYSQL_UNIQUE_INDEXES_RAW = """
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


# ── 占位符渲染机制 ─────────────────────────────────────────────


def build_in_clause(count: int) -> str:
    """返回包含 *count* 个 ``%s`` 占位符的 ``IN`` 子句片段。

    *count* 小于 1 时按 1 处理，保证生成的 SQL 始终可执行。
    """
    return ", ".join(["%s"] * max(count, 1))


def build_family_queries(
    count: int,
    *,
    table_columns_raw: str,
    primary_keys_raw: str,
    foreign_keys_raw: str,
    unique_indexes_raw: str,
) -> dict[str, str]:
    """按 *count* 渲染四个元数据查询模板的占位符。

    参数为各方言的原始 SQL 模板（含 ``{schema_placeholders}`` 与
    ``{table_placeholders}`` 格式化键）；返回键固定的查询字典，
    键为 ``table_columns`` / ``primary_keys`` / ``foreign_keys`` /
    ``unique_indexes``。
    """
    placeholders_schema = build_in_clause(count)
    placeholders_table = build_in_clause(count)
    return {
        "table_columns": table_columns_raw.format(
            schema_placeholders=placeholders_schema,
            table_placeholders=placeholders_table,
        ),
        "primary_keys": primary_keys_raw.format(
            schema_placeholders=placeholders_schema,
            table_placeholders=placeholders_table,
        ),
        "foreign_keys": foreign_keys_raw.format(
            schema_placeholders=placeholders_schema,
            table_placeholders=placeholders_table,
        ),
        "unique_indexes": unique_indexes_raw.format(
            schema_placeholders=placeholders_schema,
            table_placeholders=placeholders_table,
        ),
    }
