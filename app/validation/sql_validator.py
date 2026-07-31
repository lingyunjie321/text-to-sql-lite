from sqlglot import ErrorLevel, exp, parse
from sqlglot.errors import OptimizeError, ParseError, UnsupportedError
from sqlglot.optimizer.normalize_identifiers import normalize_identifiers
from sqlglot.optimizer.qualify import qualify
from sqlglot.optimizer.scope import Scope, traverse_scope

from app.connectors.metadata import (
    SchemaSnapshot,
    normalize_metadata_scope,
)
from app.validation.models import (
    ValidationIssue,
    ValidationResult,
    failure_result,
    success_result,
)
from app.validation.policy import (
    ALLOWED_CAST_TARGET_TYPES,
    ALLOWED_FUNCTION_NAMES,
    ALLOWED_NON_FUNCTION_NODE_TYPES,
    COLUMN_INVALID,
    CONTEXT_INVALID,
    DIALECT_ERROR,
    FORBIDDEN_NODE,
    FORBIDDEN_NODE_TYPES,
    FUNCTION_NOT_ALLOWED,
    MULTIPLE_STATEMENTS,
    MAX_CAST_TYPE_PARAMETERS,
    NOT_READ_ONLY,
    OBJECT_AMBIGUOUS,
    OBJECT_NOT_ALLOWED,
    OBJECT_UNKNOWN,
    PARSE_ERROR,
    UNKNOWN_AST,
    WILDCARD_FORBIDDEN,
)

_SQLGLOT_DIALECT_MAP: dict[str, str] = {
    "postgresql": "postgres",
    "postgres": "postgres",
    "mysql": "mysql",
    "starrocks": "mysql",  # StarRocks uses MySQL-compatible SQLGlot dialect
}


def validate_sql(
    sql: str,
    *,
    allowed_schemas: tuple[str, ...],
    allowed_tables: tuple[str, ...],
    snapshot: SchemaSnapshot,
    dialect: str = "postgres",
) -> ValidationResult:
    sqlglot_dialect = _SQLGLOT_DIALECT_MAP.get(dialect, dialect)
    try:
        expressions = [
            expression
            for expression in parse(
                sql,
                read=sqlglot_dialect,
                error_level=ErrorLevel.RAISE,
            )
            if expression
        ]
    except ParseError:
        return failure_result(PARSE_ERROR)
    if not expressions:
        return failure_result(PARSE_ERROR)
    if len(expressions) != 1:
        return failure_result(MULTIPLE_STATEMENTS)

    expression = expressions[0]
    if not isinstance(expression, exp.Select):
        return failure_result(NOT_READ_ONLY)

    structural_issue = _validate_structure(expression)
    if structural_issue is not None:
        return failure_result(structural_issue)

    try:
        authorization = normalize_metadata_scope(
            allowed_schemas,
            allowed_tables,
        )
    except ValueError:
        return failure_result(CONTEXT_INVALID)
    authorized_tables = set(authorization.table_pairs)
    snapshot_tables = {
        (table.schema_name, table.table_name)
        for table in snapshot.tables
    }
    if not snapshot_tables.issubset(authorized_tables):
        return failure_result(CONTEXT_INVALID)

    resolved_expression = normalize_identifiers(
        expression.copy(),
        dialect=sqlglot_dialect,
    )
    referenced_tables: list[str] = []
    seen_table_nodes: set[int] = set()
    for query_scope in traverse_scope(resolved_expression):
        for source in query_scope.sources.values():
            if isinstance(source, Scope):
                continue
            if not isinstance(source, exp.Table):
                return failure_result(UNKNOWN_AST)
            if id(source) in seen_table_nodes:
                continue
            seen_table_nodes.add(id(source))

            resolved_table, issue = _resolve_table(
                source,
                authorized_tables=authorized_tables,
                snapshot_tables=snapshot_tables,
            )
            if issue is not None:
                return failure_result(issue)
            assert resolved_table is not None
            schema_name, table_name = resolved_table
            if not source.db:
                source.set(
                    "db",
                    exp.to_identifier(
                        schema_name,
                        quoted=schema_name != schema_name.lower(),
                    ),
                )
            referenced_tables.append(f"{schema_name}.{table_name}")

    try:
        qualified_expression = qualify(
            resolved_expression,
            dialect=sqlglot_dialect,
            schema=_schema_mapping(snapshot),
            expand_stars=False,
            infer_schema=False,
            validate_qualify_columns=True,
            quote_identifiers=False,
            identify=False,
            sql=None,
        )
    except OptimizeError:
        return failure_result(COLUMN_INVALID)

    if _contains_whole_row_reference(qualified_expression):
        return failure_result(WILDCARD_FORBIDDEN)

    referenced_columns = _referenced_columns(qualified_expression)
    function_issue = _validate_functions(qualified_expression)
    if function_issue is not None:
        return failure_result(function_issue)

    try:
        normalized_sql = expression.sql(
            dialect=sqlglot_dialect,
            unsupported_level=ErrorLevel.RAISE,
        )
    except UnsupportedError:
        return failure_result(DIALECT_ERROR)
    return success_result(
        normalized_sql,
        referenced_tables=tuple(referenced_tables),
        referenced_columns=referenced_columns,
    )


def _validate_structure(
    expression: exp.Expression,
) -> ValidationIssue | None:
    for node in expression.walk():
        if isinstance(node, FORBIDDEN_NODE_TYPES):
            return FORBIDDEN_NODE
        if isinstance(node, exp.Star):
            if not (
                isinstance(node.parent, exp.Count)
                and not node.args.get("table")
            ):
                return WILDCARD_FORBIDDEN
            continue
        if isinstance(node, exp.Func):
            continue
        if type(node) not in ALLOWED_NON_FUNCTION_NODE_TYPES:
            return UNKNOWN_AST
    return None


def _validate_functions(
    expression: exp.Expression,
) -> ValidationIssue | None:
    for function in expression.find_all(exp.Func):
        if type(function) in ALLOWED_NON_FUNCTION_NODE_TYPES:
            continue
        if isinstance(function, exp.If):
            if isinstance(function.parent, exp.Case):
                continue
            return FUNCTION_NOT_ALLOWED
        if isinstance(function, exp.Cast) and not _cast_target_is_allowed(
            function
        ):
            return FUNCTION_NOT_ALLOWED
        if type(function) not in ALLOWED_FUNCTION_NAMES:
            return FUNCTION_NOT_ALLOWED
    return None


def _cast_target_is_allowed(cast: exp.Cast) -> bool:
    target = cast.args.get("to")
    if (
        not isinstance(target, exp.DataType)
        or target.this not in ALLOWED_CAST_TARGET_TYPES
    ):
        return False

    parameters = target.expressions
    if not parameters:
        return True
    maximum = MAX_CAST_TYPE_PARAMETERS.get(target.this)
    if maximum is None or len(parameters) > maximum:
        return False
    return all(_safe_cast_type_parameter(item) for item in parameters)


def _safe_cast_type_parameter(expression: exp.Expression) -> bool:
    if not isinstance(expression, exp.DataTypeParam):
        return False
    value = expression.this
    if not isinstance(value, exp.Literal) or value.is_string:
        return False
    try:
        return int(value.this) >= 0
    except (TypeError, ValueError):
        return False


def _resolve_table(
    table: exp.Table,
    *,
    authorized_tables: set[tuple[str, str]],
    snapshot_tables: set[tuple[str, str]],
) -> tuple[tuple[str, str] | None, ValidationIssue | None]:
    if table.catalog:
        return None, OBJECT_NOT_ALLOWED

    table_name = table.name
    if table.db:
        resolved = (table.db, table_name)
        if resolved not in authorized_tables:
            return None, OBJECT_NOT_ALLOWED
    else:
        matches = sorted(
            candidate
            for candidate in authorized_tables
            if candidate[1] == table_name
        )
        if not matches:
            return None, OBJECT_NOT_ALLOWED
        if len(matches) > 1:
            return None, OBJECT_AMBIGUOUS
        resolved = matches[0]

    if resolved not in snapshot_tables:
        return None, OBJECT_UNKNOWN
    return resolved, None


def _schema_mapping(snapshot: SchemaSnapshot) -> dict[str, object]:
    mapping: dict[str, object] = {}
    for table in snapshot.tables:
        schema = mapping.setdefault(
            _mapping_identifier(table.schema_name),
            {},
        )
        assert isinstance(schema, dict)
        schema[_mapping_identifier(table.table_name)] = {
            _mapping_identifier(column.column_name): column.formatted_type
            for column in table.columns
        }
    return mapping


def _mapping_identifier(identifier: str) -> str:
    if identifier == identifier.lower():
        return identifier
    return f'"{identifier.replace('"', '""')}"'


def _referenced_columns(
    qualified_expression: exp.Expression,
) -> tuple[str, ...]:
    references: set[str] = set()
    for query_scope in traverse_scope(qualified_expression):
        for column in query_scope.columns:
            if not column.table:
                continue
            source = query_scope.sources.get(column.table)
            if not isinstance(source, exp.Table):
                continue
            if not source.db:
                continue
            references.add(
                f"{source.db}.{source.name}.{column.name}"
            )
    return tuple(sorted(references))


def _contains_whole_row_reference(
    qualified_expression: exp.Expression,
) -> bool:
    return qualified_expression.find(exp.TableColumn) is not None
