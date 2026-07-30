import pytest

from app.connectors.metadata import (
    ColumnMetadata,
    TableMetadata,
    build_schema_snapshot,
)
from app.schema_linking import SchemaTopK, link_schema


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


def _link(
    tables: tuple[TableMetadata, ...],
    question: str,
    *,
    top_k: SchemaTopK,
):
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
        top_k=top_k,
    )


@pytest.mark.parametrize("top_k", (5, 10, 20))
def test_positive_matches_rank_first_within_requested_budget(
    top_k: SchemaTopK,
) -> None:
    tables = tuple(
        _table(
            number,
            aliases=(f"priority{number}",) if number >= 22 else (),
        )
        for number in range(24)
    )

    result = _link(
        tables,
        "priority22 priority23",
        top_k=top_k,
    )
    object_ids = tuple(
        table.object_id for table in result.candidate_tables
    )

    assert len(object_ids) == top_k
    assert result.top_k == top_k
    assert object_ids[:2] == ("public.table_22", "public.table_23")
    assert set(object_ids).issubset(
        {f"public.table_{number:02d}" for number in range(24)}
    )


def test_no_match_returns_all_tables_in_a_narrow_scope() -> None:
    tables = tuple(_table(number) for number in (3, 1, 2, 0))

    result = _link(
        tables,
        "no matching vocabulary",
        top_k=5,
    )

    assert tuple(
        table.object_id for table in result.candidate_tables
    ) == tuple(f"public.table_{number:02d}" for number in range(4))
    assert all(table.score == 0 for table in result.candidate_tables)


@pytest.mark.parametrize("top_k", (5, 10, 20))
def test_no_match_uses_canonical_requested_budget(
    top_k: SchemaTopK,
) -> None:
    tables = tuple(_table(number) for number in reversed(range(24)))

    result = _link(
        tables,
        "no matching vocabulary",
        top_k=top_k,
    )

    assert tuple(
        table.object_id for table in result.candidate_tables
    ) == tuple(f"public.table_{number:02d}" for number in range(top_k))
    assert result.top_k == top_k


def test_candidate_fields_cover_every_selected_table_column() -> None:
    tables = tuple(_table(number) for number in range(12))

    result = _link(tables, "", top_k=10)
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


@pytest.mark.parametrize("invalid", (True, False, 0, 6, 21, -5, 5.0, "20"))
def test_linker_rejects_non_closed_internal_budget(
    invalid: object,
) -> None:
    tables = (_table(0),)
    snapshot = build_schema_snapshot(
        tables=tables,
        primary_keys=(),
        foreign_keys=(),
        unique_constraints=(),
        unique_indexes=(),
    )

    with pytest.raises(
        ValueError,
        match=r"^schema linking context is invalid$",
    ):
        link_schema(
            "film",
            allowed_schemas=("public",),
            allowed_tables=("public.table_00",),
            snapshot=snapshot,
            top_k=invalid,  # type: ignore[arg-type]
        )


def test_linker_requires_an_explicit_internal_budget() -> None:
    tables = (_table(0),)
    snapshot = build_schema_snapshot(
        tables=tables,
        primary_keys=(),
        foreign_keys=(),
        unique_constraints=(),
        unique_indexes=(),
    )

    with pytest.raises(TypeError):
        link_schema(
            "film",
            allowed_schemas=("public",),
            allowed_tables=("public.table_00",),
            snapshot=snapshot,
        )
