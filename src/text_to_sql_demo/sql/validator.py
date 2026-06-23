from sqlglot import exp

from text_to_sql_demo.schema.catalog import DatabaseSchemaMetadata
from text_to_sql_demo.sql.dialect import (
    DialectError,
    DialectService,
    SQLDialectParseError,
    UnsupportedDialectError,
)
from text_to_sql_demo.sql.models import SQLError, SQLValidationResult


class SQLValidator:
    """基于 SQLGlot 和 Schema metadata 的 SQL 校验器。"""

    def validate(
        self,
        *,
        sql: str,
        schema: DatabaseSchemaMetadata | dict,
        dialect: str,
        render_dialect: str | None = None,
        allow_transpile: bool = False,
    ) -> SQLValidationResult:
        schema_metadata = DatabaseSchemaMetadata.model_validate(schema)
        dialect_service = DialectService()
        try:
            expression = dialect_service.parse_one(sql, dialect=dialect)
        except SQLDialectParseError as exc:
            return SQLValidationResult(
                success=False,
                error=SQLError(
                    category="syntax_error",
                    message="SQL 语法解析失败",
                    raw_message=str(exc),
                ),
            )
        except UnsupportedDialectError as exc:
            return SQLValidationResult(
                success=False,
                error=SQLError(
                    category="dialect_error",
                    message="SQL 方言不支持",
                    raw_message=str(exc),
                ),
            )
        except DialectError as exc:
            return SQLValidationResult(
                success=False,
                error=SQLError(
                    category="dialect_error",
                    message=str(exc),
                    raw_message=str(exc),
                ),
            )

        readonly_error = _validate_read_only(expression)
        if readonly_error is not None:
            return SQLValidationResult(success=False, error=readonly_error)

        schema_error = _validate_schema(expression, schema_metadata)
        if schema_error is not None:
            return SQLValidationResult(success=False, error=schema_error)

        target_render_dialect = render_dialect if allow_transpile and render_dialect else dialect
        try:
            normalized_sql = dialect_service.render_expression(expression, dialect=dialect)
            rendered_sql = dialect_service.render_expression(
                expression,
                dialect=target_render_dialect,
            )
        except UnsupportedDialectError as exc:
            return SQLValidationResult(
                success=False,
                error=SQLError(
                    category="dialect_error",
                    message="SQL 方言不支持",
                    raw_message=str(exc),
                ),
            )

        return SQLValidationResult(
            success=True,
            normalized_sql=normalized_sql,
            rendered_sql=rendered_sql,
        )


def _validate_read_only(expression: exp.Expression) -> SQLError | None:
    forbidden_types = (
        exp.Insert,
        exp.Update,
        exp.Delete,
        exp.Drop,
        exp.Create,
        exp.Alter,
        exp.Command,
    )
    if any(expression.find(forbidden_type) is not None for forbidden_type in forbidden_types):
        return SQLError(category="dialect_error", message="只允许只读 SELECT 查询")
    if expression.find(exp.Select) is None:
        return SQLError(category="dialect_error", message="只允许 SELECT 查询")
    return None


def _validate_schema(
    expression: exp.Expression,
    schema: DatabaseSchemaMetadata,
) -> SQLError | None:
    table_aliases: dict[str, str] = {}
    referenced_tables: list[str] = []
    derived_columns = _collect_derived_columns(expression)
    for table in expression.find_all(exp.Table):
        table_name = table.name
        if table_name not in schema.tables:
            return SQLError(
                category="unknown_table",
                message=f"表不存在: {table_name}",
                table=table_name,
            )
        referenced_tables.append(table_name)
        table_aliases[table.alias_or_name] = table_name
        table_aliases[table_name] = table_name

    for column in expression.find_all(exp.Column):
        column_name = column.name
        if column_name == "*":
            continue
        qualifier = column.table
        if qualifier:
            table_name = table_aliases.get(qualifier, qualifier)
            if table_name not in schema.tables:
                return SQLError(
                    category="unknown_table",
                    message=f"表不存在: {table_name}",
                    table=table_name,
                )
            if column_name not in schema.tables[table_name].columns:
                return SQLError(
                    category="unknown_column",
                    message=f"字段不存在: {table_name}.{column_name}",
                    table=table_name,
                    column=column_name,
                )
            continue

        matching_tables = [
            table_name
            for table_name in referenced_tables
            if column_name in schema.tables[table_name].columns
        ]
        if not matching_tables:
            if column_name in derived_columns:
                continue
            return SQLError(
                category="unknown_column",
                message=f"字段不存在: {column_name}",
                column=column_name,
            )
        if len(matching_tables) > 1:
            return SQLError(
                category="ambiguous_column",
                message=f"字段不明确: {column_name}",
                column=column_name,
            )

    return None


def _collect_derived_columns(expression: exp.Expression) -> set[str]:
    """收集子查询和 CTE 暴露给外层查询的派生列名。"""
    columns: set[str] = set()
    for subquery in expression.find_all(exp.Subquery):
        columns.update(_select_output_columns(subquery.this))
    for cte in expression.find_all(exp.CTE):
        columns.update(_select_output_columns(cte.this))
    return columns


def _select_output_columns(expression: exp.Expression) -> set[str]:
    if not isinstance(expression, exp.Select):
        return set()
    return {
        item.alias_or_name
        for item in expression.expressions
        if item.alias_or_name
    }
