from dataclasses import replace

from app.connectors.metadata import (
    ColumnMetadata,
    TableMetadata,
    build_schema_snapshot,
)
from app.schema_linking import link_schema


def _table(
    table_name: str,
    *,
    comment: str | None = None,
    aliases: tuple[str, ...] = (),
) -> TableMetadata:
    return TableMetadata(
        schema_name="public",
        table_name=table_name,
        relation_kind="table",
        comment=comment,
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
        ),
    )


def _snapshot(*tables: TableMetadata):
    return build_schema_snapshot(
        tables=tables,
        primary_keys=(),
        foreign_keys=(),
        unique_constraints=(),
        unique_indexes=(),
    )


def _link(snapshot):
    return link_schema(
        "directorcut",
        allowed_schemas=("public",),
        allowed_tables=("public.archive", "public.film"),
        snapshot=snapshot,
        top_k=10,
    )


def test_authorized_metadata_change_updates_version_and_ranking() -> None:
    film = _table("film")
    archive = _table("archive", comment="directorcut")
    before = _link(_snapshot(film, archive))
    after = _link(
        _snapshot(
            replace(film, aliases=("directorcut",)),
            archive,
        )
    )

    assert before.schema_version != after.schema_version
    assert before.candidate_tables[0].object_id == "public.archive"
    assert after.candidate_tables[0].object_id == "public.film"
    assert after.candidate_tables[0].score > before.candidate_tables[1].score


def test_unauthorized_change_does_not_update_authorized_version() -> None:
    film = _table("film")
    hidden = _table("hidden", comment="private")
    changed_hidden = replace(
        hidden,
        comment="different private metadata",
        aliases=("secret",),
    )

    first = link_schema(
        "film",
        allowed_schemas=("public",),
        allowed_tables=("public.film",),
        snapshot=_snapshot(film, hidden),
        top_k=10,
    )
    second = link_schema(
        "film",
        allowed_schemas=("public",),
        allowed_tables=("public.film",),
        snapshot=_snapshot(film, changed_hidden),
        top_k=10,
    )

    assert second == first


def test_missing_field_feedback_can_trigger_stateless_relinking() -> None:
    snapshot = _snapshot(_table("film"))

    first = link_schema(
        "film_name",
        allowed_schemas=("public",),
        allowed_tables=("public.film",),
        snapshot=snapshot,
        top_k=10,
    )
    repaired = link_schema(
        "film film_id",
        allowed_schemas=("public",),
        allowed_tables=("public.film",),
        snapshot=snapshot,
        top_k=10,
    )

    assert first.schema_version == repaired.schema_version
    assert {
        field.object_id for field in first.candidate_fields
    } == {"public.film.film_id"}
    assert {
        field.object_id for field in repaired.candidate_fields
    } == {"public.film.film_id"}
    assert all(
        field.column_name != "film_name"
        for field in repaired.candidate_fields
    )
