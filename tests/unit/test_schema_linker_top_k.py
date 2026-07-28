import inspect

from app.connectors.metadata import (
    ColumnMetadata,
    TableMetadata,
    build_schema_snapshot,
)
from app.schema_linking import TOP_K, link_schema


def _table(
    number: int,
    *,
    aliases: tuple[str, ...] = (),
) -> TableMetadata:
    table_name = f"table_{number:02d}"
    return TableMetadata(
        schema_name="public",
        table_name=table_name,
        relation_kind="table",
        comment=None,
        aliases=aliases,
        columns=(
            ColumnMetadata(
                schema_name="public",
                table_name=table_name,
                column_name=f"{table_name}_id",
                ordinal_position=1,
                data_type="int4",
                formatted_type="integer",
                nullable=False,
                comment=None,
            ),
            ColumnMetadata(
                schema_name="public",
                table_name=table_name,
                column_name="description",
                ordinal_position=2,
                data_type="text",
                formatted_type="text",
                nullable=True,
                comment=None,
            ),
        ),
    )


def _link(tables: tuple[TableMetadata, ...], question: str):
    snapshot = build_schema_snapshot(
        tables=tables,
        primary_keys=(),
        foreign_keys=(),
        unique_constraints=(),
        unique_indexes=(),
    )
    return link_schema(
        question,
        allowed_schemas=("public",),
        allowed_tables=tuple(
            f"public.{table.table_name}" for table in tables
        ),
        snapshot=snapshot,
    )


def test_positive_matches_rank_first_without_exceeding_fixed_top_k() -> None:
    tables = tuple(
        _table(
            number,
            aliases=(f"priority{number}",) if number >= 10 else (),
        )
        for number in range(12)
    )

    result = _link(tables, "priority10 priority11")
    object_ids = tuple(
        table.object_id for table in result.candidate_tables
    )

    assert len(object_ids) == TOP_K == 10
    assert object_ids[:2] == ("public.table_10", "public.table_11")


def test_no_match_returns_all_tables_in_a_narrow_scope() -> None:
    tables = tuple(_table(number) for number in (3, 1, 2, 0))

    result = _link(tables, "no matching vocabulary")

    assert tuple(
        table.object_id for table in result.candidate_tables
    ) == tuple(f"public.table_{number:02d}" for number in range(4))
    assert all(table.score == 0 for table in result.candidate_tables)


def test_no_match_uses_canonical_first_ten_for_a_wide_scope() -> None:
    tables = tuple(_table(number) for number in reversed(range(12)))

    result = _link(tables, "no matching vocabulary")

    assert tuple(
        table.object_id for table in result.candidate_tables
    ) == tuple(f"public.table_{number:02d}" for number in range(10))


def test_candidate_fields_cover_every_selected_table_column() -> None:
    tables = tuple(_table(number) for number in range(12))

    result = _link(tables, "")
    selected = {
        table.object_id for table in result.candidate_tables
    }
    field_ids = {
        field.object_id for field in result.candidate_fields
    }

    assert all(
        field_id.rsplit(".", 1)[0] in selected
        for field_id in field_ids
    )
    assert field_ids == {
        f"{table_id}.{column_name}"
        for table_id in selected
        for column_name in (
            f"{table_id.rsplit('.', 1)[1]}_id",
            "description",
        )
    }


def test_top_k_is_not_a_caller_controlled_parameter() -> None:
    assert "top_k" not in inspect.signature(link_schema).parameters
