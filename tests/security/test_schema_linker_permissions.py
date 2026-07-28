from dataclasses import replace

from app.connectors.metadata import (
    ColumnMetadata,
    ForeignKeyMetadata,
    TableMetadata,
    build_schema_snapshot,
)
from app.schema_linking import link_schema


def _table(
    table_name: str,
    *column_names: str,
    comment: str | None = None,
    aliases: tuple[str, ...] = (),
) -> TableMetadata:
    return TableMetadata(
        schema_name="public",
        table_name=table_name,
        relation_kind="table",
        comment=comment,
        aliases=aliases,
        columns=tuple(
            ColumnMetadata(
                schema_name="public",
                table_name=table_name,
                column_name=column_name,
                ordinal_position=position,
                data_type="text",
                formatted_type="text",
                nullable=False,
                comment=None,
            )
            for position, column_name in enumerate(column_names, start=1)
        ),
    )


FILM = _table("film", "film_id", "title")
PAYROLL = _table(
    "payroll",
    "employee_id",
    "secret_compensation",
    comment="confidential salaries",
    aliases=("薪资",),
)
UNAUTHORIZED_FK = ForeignKeyMetadata(
    constraint_name="payroll_film_fkey",
    source_schema="public",
    source_table="payroll",
    source_columns=("employee_id",),
    target_schema="public",
    target_table="film",
    target_columns=("film_id",),
)


def _snapshot(payroll: TableMetadata):
    return build_schema_snapshot(
        tables=(FILM, payroll),
        primary_keys=(),
        foreign_keys=(UNAUTHORIZED_FK,),
        unique_constraints=(),
        unique_indexes=(),
    )


def test_unauthorized_metadata_cannot_change_result_or_version() -> None:
    original = link_schema(
        "confidential salaries secret compensation 薪资",
        allowed_schemas=("public",),
        allowed_tables=("public.film",),
        snapshot=_snapshot(PAYROLL),
    )
    changed = link_schema(
        "confidential salaries secret compensation 薪资",
        allowed_schemas=("public",),
        allowed_tables=("public.film",),
        snapshot=_snapshot(
            replace(
                PAYROLL,
                comment="different private vocabulary",
                aliases=("executive bonus",),
            )
        ),
    )

    assert changed == original
    assert original.schema_version != _snapshot(PAYROLL).schema_version
    assert original.join_paths == ()
    assert tuple(
        table.object_id for table in original.candidate_tables
    ) == ("public.film",)
    assert all(
        "payroll" not in field.object_id
        for field in original.candidate_fields
    )


def test_empty_authorization_returns_no_metadata() -> None:
    result = link_schema(
        "film payroll",
        allowed_schemas=(),
        allowed_tables=("public.film", "public.payroll"),
        snapshot=_snapshot(PAYROLL),
    )

    assert result.candidate_tables == ()
    assert result.candidate_fields == ()
    assert result.join_paths == ()


def test_fk_with_an_unauthorized_endpoint_is_removed_before_graph_use() -> None:
    result = link_schema(
        "film payroll",
        allowed_schemas=("public",),
        allowed_tables=("public.film",),
        snapshot=_snapshot(PAYROLL),
    )

    assert result.join_paths == ()
    assert all(
        edge.constraint_name != "payroll_film_fkey"
        for path in result.join_paths
        for edge in path.edges
    )
