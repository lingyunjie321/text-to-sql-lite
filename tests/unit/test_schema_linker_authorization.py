import pytest

from app.connectors.metadata import (
    ColumnMetadata,
    TableMetadata,
    build_schema_snapshot,
    empty_schema_snapshot,
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


SNAPSHOT = build_schema_snapshot(
    tables=(
        _table("film", "film_id", "title"),
        _table(
            "payroll",
            "employee_id",
            "secret_compensation",
            comment="confidential salaries",
            aliases=("薪资",),
        ),
    ),
    primary_keys=(),
    foreign_keys=(),
    unique_constraints=(),
    unique_indexes=(),
)


def test_linking_filters_snapshot_before_building_candidates() -> None:
    result = link_schema(
        "confidential salaries secret compensation 薪资",
        allowed_schemas=("public",),
        allowed_tables=("public.film",),
        snapshot=SNAPSHOT,
    )

    assert tuple(table.object_id for table in result.candidate_tables) == (
        "public.film",
    )
    assert {
        field.object_id for field in result.candidate_fields
    } == {
        "public.film.film_id",
        "public.film.title",
    }
    assert all(not table.matched_tokens for table in result.candidate_tables)
    assert all(not field.matched_tokens for field in result.candidate_fields)
    assert result.join_paths == ()


def test_empty_authorization_returns_empty_filtered_snapshot_result() -> None:
    result = link_schema(
        "film title",
        allowed_schemas=("public",),
        allowed_tables=(),
        snapshot=SNAPSHOT,
    )

    assert result.candidate_tables == ()
    assert result.candidate_fields == ()
    assert result.join_paths == ()
    assert result.schema_version == empty_schema_snapshot().schema_version


@pytest.mark.parametrize(
    ("allowed_schemas", "allowed_tables"),
    [
        (("public",), ("film",)),
        (("public",), ("public.",)),
        (("",), ("public.film",)),
    ],
)
def test_malformed_scope_uses_one_public_error(
    allowed_schemas: tuple[str, ...],
    allowed_tables: tuple[str, ...],
) -> None:
    with pytest.raises(
        ValueError,
        match=r"^schema linking context is invalid$",
    ):
        link_schema(
            "film",
            allowed_schemas=allowed_schemas,
            allowed_tables=allowed_tables,
            snapshot=SNAPSHOT,
        )
