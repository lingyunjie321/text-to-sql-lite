from dataclasses import replace
import re

from sqlglot import exp, parse
from sqlglot.errors import ParseError

from app.connectors.metadata import (
    SchemaSnapshot,
    TableMetadata,
)
from app.generation.models import GeneratedSQL, GenerationResult

_SIMPLE_COLUMN_NAME = re.compile(r"^[a-z][a-z0-9_]*$")


def _aggregate_alias(expression: exp.Expression) -> str | None:
    if not isinstance(expression, (exp.Count, exp.Sum)):
        return None
    counted = expression.this
    if not isinstance(counted, exp.Column):
        return None
    column_name = counted.name
    if not _SIMPLE_COLUMN_NAME.fullmatch(column_name):
        return None
    base_name = (
        column_name[:-3]
        if isinstance(expression, exp.Count)
        and column_name.endswith("_id")
        else column_name
    )
    if not base_name:
        return None
    if isinstance(expression, exp.Count):
        return f"{base_name}_count"
    return f"total_{base_name}"


def _projection_alias(expression: exp.Expression) -> str | None:
    if isinstance(expression, exp.Column):
        column_name = expression.name
        return (
            column_name
            if _SIMPLE_COLUMN_NAME.fullmatch(column_name)
            else None
        )
    if isinstance(expression, exp.TimestampTrunc):
        column = expression.this
        unit = expression.args.get("unit")
        if not isinstance(column, exp.Column) or not isinstance(
            unit,
            exp.Var,
        ):
            return None
        column_name = column.name
        unit_name = unit.name.casefold()
        if (
            not _SIMPLE_COLUMN_NAME.fullmatch(column_name)
            or not _SIMPLE_COLUMN_NAME.fullmatch(unit_name)
        ):
            return None
        base_name = (
            column_name[:-5]
            if column_name.endswith("_date")
            else column_name
        )
        return f"{base_name}_{unit_name}"
    aggregates = tuple(
        node
        for node in expression.walk()
        if isinstance(node, (exp.Count, exp.Sum))
    )
    if len(aggregates) != 1:
        return None
    return _aggregate_alias(aggregates[0])


def _root_table_metadata(
    statement: exp.Select,
    snapshot: SchemaSnapshot,
) -> tuple[TableMetadata, ...]:
    sources: list[TableMetadata] = []
    for table in statement.find_all(exp.Table):
        if table.find_ancestor(exp.Select) is not statement:
            continue
        matches = tuple(
            metadata
            for metadata in snapshot.tables
            if metadata.table_name == table.name
            and (not table.db or metadata.schema_name == table.db)
        )
        if len(matches) != 1:
            continue
        metadata = matches[0]
        sources.append(metadata)
    return tuple(sources)


def normalize_generated_sql(
    sql: str,
    *,
    snapshot: SchemaSnapshot | None = None,
) -> str:
    """Canonicalize deterministic projection aliases without fixing SQL."""
    try:
        statements = parse(sql, read="postgres")
    except ParseError:
        return sql
    if len(statements) != 1:
        return sql
    statement = statements[0]
    if not isinstance(statement, exp.Select):
        return sql

    sources: tuple[TableMetadata, ...] = ()
    if snapshot is not None:
        sources = _root_table_metadata(statement, snapshot)

    source_column_names = {
        column.column_name
        for table in sources
        for column in table.columns
    }
    projections = tuple(statement.expressions)
    original_outputs: list[str | None] = []
    proposed_aliases: dict[int, str] = {}
    original_aliases: dict[int, exp.Identifier] = {}
    for index, projection in enumerate(projections):
        output_name = projection.alias_or_name
        original_outputs.append(output_name or None)
        if not isinstance(projection, exp.Alias):
            continue
        canonical_alias = _projection_alias(projection.this)
        alias_node = projection.args.get("alias")
        if (
            canonical_alias is None
            or not isinstance(alias_node, exp.Identifier)
            or alias_node.name == canonical_alias
            or alias_node.name in source_column_names
        ):
            continue
        proposed_aliases[index] = canonical_alias
        original_aliases[index] = alias_node

    nonempty_original = tuple(
        output for output in original_outputs if output is not None
    )
    planned_outputs = tuple(
        proposed_aliases.get(index, output)
        for index, output in enumerate(original_outputs)
    )
    nonempty_planned = tuple(
        output for output in planned_outputs if output is not None
    )
    if (
        len(nonempty_original) != len(set(nonempty_original))
        or len(nonempty_planned) != len(set(nonempty_planned))
    ):
        return sql

    replacements: list[tuple[int, int, str]] = []
    alias_renames: dict[str, str] = {}
    for index, canonical_alias in proposed_aliases.items():
        alias_node = original_aliases[index]
        alias_renames[alias_node.name] = canonical_alias
        start = alias_node.meta.get("start")
        end = alias_node.meta.get("end")
        if not isinstance(start, int) or not isinstance(end, int):
            return sql
        replacements.append((start, end + 1, canonical_alias))

    if snapshot is not None and alias_renames:
        for clause_name in ("group", "order"):
            clause = statement.args.get(clause_name)
            if not isinstance(clause, exp.Expression):
                continue
            for column in clause.find_all(exp.Column):
                canonical_alias = alias_renames.get(column.name)
                identifier = column.args.get("this")
                if (
                    canonical_alias is None
                    or column.table
                    or column.name in source_column_names
                    or not isinstance(identifier, exp.Identifier)
                ):
                    continue
                start = identifier.meta.get("start")
                end = identifier.meta.get("end")
                if not isinstance(start, int) or not isinstance(end, int):
                    return sql
                replacements.append(
                    (start, end + 1, canonical_alias)
                )

    normalized = sql
    for start, end, alias in sorted(
        replacements,
        key=lambda item: item[0],
        reverse=True,
    ):
        normalized = f"{normalized[:start]}{alias}{normalized[end:]}"
    return normalized


def normalize_generation_result(
    result: GenerationResult,
    *,
    snapshot: SchemaSnapshot | None = None,
) -> GenerationResult:
    sql = result.output.sql
    if sql is None:
        return result
    normalized_sql = normalize_generated_sql(
        sql,
        snapshot=snapshot,
    )
    if normalized_sql == sql:
        return result
    return replace(
        result,
        output=GeneratedSQL(sql=normalized_sql),
    )
