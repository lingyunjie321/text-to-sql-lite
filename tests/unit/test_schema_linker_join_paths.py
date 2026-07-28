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
    aliases: tuple[str, ...] = (),
) -> TableMetadata:
    return TableMetadata(
        schema_name="public",
        table_name=table_name,
        relation_kind="table",
        comment=None,
        aliases=aliases,
        columns=tuple(
            ColumnMetadata(
                schema_name="public",
                table_name=table_name,
                column_name=column_name,
                ordinal_position=position,
                data_type="int4",
                formatted_type="integer",
                nullable=False,
                comment=None,
            )
            for position, column_name in enumerate(column_names, start=1)
        ),
    )


FILM = _table("film", "film_id", aliases=("movies",))
CATEGORY = _table(
    "category",
    "category_id",
    "tenant_id",
    aliases=("genres",),
)
BRIDGE = _table("zz_bridge", "left_id", "right_id", "tenant_ref")
ACTOR = _table("actor", "actor_id")
SECRET = _table("secret_shortcut", "film_ref", "category_ref")
BRIDGE_TO_FILM = ForeignKeyMetadata(
    constraint_name="bridge_film_fkey",
    source_schema="public",
    source_table="zz_bridge",
    source_columns=("left_id",),
    target_schema="public",
    target_table="film",
    target_columns=("film_id",),
)
BRIDGE_TO_CATEGORY = ForeignKeyMetadata(
    constraint_name="bridge_category_tenant_fkey",
    source_schema="public",
    source_table="zz_bridge",
    source_columns=("right_id", "tenant_ref"),
    target_schema="public",
    target_table="category",
    target_columns=("category_id", "tenant_id"),
)
SECRET_TO_FILM = ForeignKeyMetadata(
    constraint_name="secret_film_fkey",
    source_schema="public",
    source_table="secret_shortcut",
    source_columns=("film_ref",),
    target_schema="public",
    target_table="film",
    target_columns=("film_id",),
)
SECRET_TO_CATEGORY = ForeignKeyMetadata(
    constraint_name="secret_category_fkey",
    source_schema="public",
    source_table="secret_shortcut",
    source_columns=("category_ref",),
    target_schema="public",
    target_table="category",
    target_columns=("category_id",),
)


def _link(
    tables: tuple[TableMetadata, ...],
    foreign_keys: tuple[ForeignKeyMetadata, ...],
    *,
    allowed_tables: tuple[str, ...] | None = None,
):
    snapshot = build_schema_snapshot(
        tables=tables,
        primary_keys=(),
        foreign_keys=foreign_keys,
        unique_constraints=(),
        unique_indexes=(),
    )
    return link_schema(
        "movies genres",
        allowed_schemas=("public",),
        allowed_tables=allowed_tables
        or tuple(f"public.{table.table_name}" for table in tables),
        snapshot=snapshot,
    )


def test_fk_path_adds_an_intermediate_table_within_top_k_budget() -> None:
    fillers = tuple(
        _table(f"noise_{number:02d}", "noise_id")
        for number in range(9)
    )

    result = _link(
        (FILM, CATEGORY, BRIDGE, *fillers),
        (BRIDGE_TO_FILM, BRIDGE_TO_CATEGORY),
    )

    assert len(result.candidate_tables) == 10
    assert "public.zz_bridge" in {
        table.object_id for table in result.candidate_tables
    }
    film_category_path = next(
        path
        for path in result.join_paths
        if {path.tables[0], path.tables[-1]}
        == {"public.film", "public.category"}
    )
    assert film_category_path.tables == (
        "public.category",
        "public.zz_bridge",
        "public.film",
    )
    composite_edge = next(
        edge
        for edge in film_category_path.edges
        if edge.constraint_name == "bridge_category_tenant_fkey"
    )
    assert composite_edge.source_columns == ("right_id", "tenant_ref")
    assert composite_edge.target_columns == ("category_id", "tenant_id")


def test_fk_connectivity_promotes_a_related_table_before_noise_cutoff() -> None:
    anchor = _table("anchor", "anchor_id")
    related = _table("zz_related", "left_id")
    related_fk = ForeignKeyMetadata(
        constraint_name="related_anchor_fkey",
        source_schema="public",
        source_table="zz_related",
        source_columns=("left_id",),
        target_schema="public",
        target_table="anchor",
        target_columns=("anchor_id",),
    )
    fillers = tuple(
        _table(f"noise_{number:02d}", "noise_id")
        for number in range(10)
    )
    snapshot = build_schema_snapshot(
        tables=(anchor, related, *fillers),
        primary_keys=(),
        foreign_keys=(related_fk,),
        unique_constraints=(),
        unique_indexes=(),
    )

    result = link_schema(
        "anchor",
        allowed_schemas=("public",),
        allowed_tables=tuple(
            f"public.{table.table_name}"
            for table in (anchor, related, *fillers)
        ),
        snapshot=snapshot,
    )

    selected = {
        table.object_id for table in result.candidate_tables
    }
    assert len(selected) == 10
    assert "public.anchor" in selected
    assert "public.zz_related" in selected
    assert any(
        path.tables
        == ("public.anchor", "public.zz_related")
        for path in result.join_paths
    )


def test_no_match_wide_fallback_stays_canonical_even_with_fk_paths() -> None:
    canonical_tables = tuple(
        _table(chr(ord("a") + number), "entity_id")
        for number in range(11)
    )
    bridge = _table("z_bridge", "left_id", "right_id")
    bridge_to_a = ForeignKeyMetadata(
        constraint_name="bridge_a_fkey",
        source_schema="public",
        source_table="z_bridge",
        source_columns=("left_id",),
        target_schema="public",
        target_table="a",
        target_columns=("entity_id",),
    )
    bridge_to_b = ForeignKeyMetadata(
        constraint_name="bridge_b_fkey",
        source_schema="public",
        source_table="z_bridge",
        source_columns=("right_id",),
        target_schema="public",
        target_table="b",
        target_columns=("entity_id",),
    )

    result = _link(
        (*canonical_tables, bridge),
        (bridge_to_a, bridge_to_b),
    )

    assert tuple(
        table.object_id for table in result.candidate_tables
    ) == tuple(f"public.{table_name}" for table_name in "abcdefghij")


def test_unreachable_candidate_has_no_fabricated_join_path() -> None:
    result = _link(
        (FILM, CATEGORY, BRIDGE, ACTOR),
        (BRIDGE_TO_FILM, BRIDGE_TO_CATEGORY),
    )

    assert not any(
        "public.actor" in path.tables for path in result.join_paths
    )


def test_unauthorized_shortcut_never_enters_candidates_or_paths() -> None:
    result = _link(
        (FILM, CATEGORY, BRIDGE, SECRET),
        (
            BRIDGE_TO_FILM,
            BRIDGE_TO_CATEGORY,
            SECRET_TO_FILM,
            SECRET_TO_CATEGORY,
        ),
        allowed_tables=(
            "public.film",
            "public.category",
            "public.zz_bridge",
        ),
    )

    assert "public.secret_shortcut" not in {
        table.object_id for table in result.candidate_tables
    }
    assert all(
        "public.secret_shortcut" not in path.tables
        for path in result.join_paths
    )
    assert all(
        not edge.constraint_name.startswith("secret_")
        for path in result.join_paths
        for edge in path.edges
    )
