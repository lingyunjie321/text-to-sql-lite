from app.connectors.metadata import (
    SchemaSnapshot,
    build_schema_snapshot,
    normalize_metadata_scope,
)


def authorize_schema_snapshot(
    *,
    allowed_schemas: tuple[str, ...],
    allowed_tables: tuple[str, ...],
    snapshot: SchemaSnapshot,
) -> SchemaSnapshot:
    try:
        scope = normalize_metadata_scope(
            allowed_schemas,
            allowed_tables,
        )
    except ValueError:
        raise ValueError("schema linking context is invalid") from None

    visible_tables = set(scope.table_pairs)
    tables = tuple(
        table
        for table in snapshot.tables
        if (table.schema_name, table.table_name) in visible_tables
    )
    visible_columns = {
        (table.schema_name, table.table_name): {
            column.column_name for column in table.columns
        }
        for table in tables
    }

    def columns_are_visible(
        schema_name: str,
        table_name: str,
        columns: tuple[str, ...],
    ) -> bool:
        table_columns = visible_columns.get(
            (schema_name, table_name)
        )
        return (
            table_columns is not None
            and set(columns).issubset(table_columns)
        )

    primary_keys = tuple(
        key
        for key in snapshot.primary_keys
        if columns_are_visible(
            key.schema_name,
            key.table_name,
            key.columns,
        )
    )
    foreign_keys = tuple(
        key
        for key in snapshot.foreign_keys
        if columns_are_visible(
            key.source_schema,
            key.source_table,
            key.source_columns,
        )
        and columns_are_visible(
            key.target_schema,
            key.target_table,
            key.target_columns,
        )
    )
    unique_constraints = tuple(
        constraint
        for constraint in snapshot.unique_constraints
        if columns_are_visible(
            constraint.schema_name,
            constraint.table_name,
            constraint.columns,
        )
    )
    unique_indexes = tuple(
        index
        for index in snapshot.unique_indexes
        if columns_are_visible(
            index.schema_name,
            index.table_name,
            index.columns,
        )
    )
    return build_schema_snapshot(
        tables=tables,
        primary_keys=primary_keys,
        foreign_keys=foreign_keys,
        unique_constraints=unique_constraints,
        unique_indexes=unique_indexes,
    )
