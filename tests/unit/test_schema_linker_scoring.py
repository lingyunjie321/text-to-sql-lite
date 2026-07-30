import pytest

from app.connectors.metadata import (
    ColumnMetadata,
    TableMetadata,
    build_schema_snapshot,
)
from app.schema_linking import link_schema
from app.schema_linking.linker import _tokenize


def _column(
    table_name: str,
    column_name: str,
    position: int,
    *,
    comment: str | None = None,
    aliases: tuple[str, ...] = (),
) -> ColumnMetadata:
    return ColumnMetadata(
        schema_name="public",
        table_name=table_name,
        column_name=column_name,
        ordinal_position=position,
        data_type="text",
        formatted_type="text",
        nullable=False,
        comment=comment,
        aliases=aliases,
    )


FILM = TableMetadata(
    schema_name="public",
    table_name="film",
    relation_kind="table",
    comment="motion pictures catalog",
    aliases=("movies", "影片"),
    columns=(
        _column("film", "film_id", 1, aliases=("影片编号",)),
        _column("film", "title", 2, comment="display name"),
        _column(
            "film",
            "releaseYear",
            3,
            comment="premiere calendar year",
        ),
    ),
)
INVENTORY = TableMetadata(
    schema_name="public",
    table_name="inventory",
    relation_kind="table",
    comment="physical copies",
    columns=(
        _column("inventory", "inventory_id", 1),
        _column("inventory", "title", 2),
    ),
)
SNAPSHOT = build_schema_snapshot(
    tables=(FILM, INVENTORY),
    primary_keys=(),
    foreign_keys=(),
    unique_constraints=(),
    unique_indexes=(),
)
ALLOWED = ("public.film", "public.inventory")


@pytest.mark.parametrize(
    ("question", "matched_token"),
    [
        ("movies", "movies"),
        ("motion pictures", "motion"),
        ("影片", "影片"),
        ("premiere calendar year", "premiere"),
    ],
)
def test_table_alias_comment_unicode_and_field_comment_match(
    question: str,
    matched_token: str,
) -> None:
    result = link_schema(
        question,
        allowed_schemas=("public",),
        allowed_tables=ALLOWED,
        snapshot=SNAPSHOT,
        top_k=10,
    )

    assert result.candidate_tables[0].object_id == "public.film"
    assert result.candidate_tables[0].score > 0
    assert matched_token in result.candidate_tables[0].matched_tokens


def test_field_match_is_scored_and_aggregated_into_its_table() -> None:
    result = link_schema(
        "影片编号",
        allowed_schemas=("public",),
        allowed_tables=ALLOWED,
        snapshot=SNAPSHOT,
        top_k=10,
    )

    assert result.candidate_tables[0].object_id == "public.film"
    assert result.candidate_tables[0].score > 0
    assert result.candidate_fields[0].object_id == "public.film.film_id"
    assert result.candidate_fields[0].score > 0
    assert result.candidate_fields[0].matched_tokens == ("影片编号",)


def test_table_evidence_disambiguates_a_shared_field_name() -> None:
    result = link_schema(
        "film title",
        allowed_schemas=("public",),
        allowed_tables=ALLOWED,
        snapshot=SNAPSHOT,
        top_k=10,
    )

    assert result.candidate_tables[0].object_id == "public.film"
    film_title = next(
        field
        for field in result.candidate_fields
        if field.object_id == "public.film.title"
    )
    inventory_title = next(
        field
        for field in result.candidate_fields
        if field.object_id == "public.inventory.title"
    )
    assert film_title.score > inventory_title.score


def test_tokenizer_normalizes_nfkc_snake_case_and_camel_case() -> None:
    assert set(_tokenize("Ｆｉｌｍ＿Ｃａｔｅｇｏｒｙ releaseYear")) >= {
        "film_category",
        "film",
        "category",
        "releaseyear",
        "release",
        "year",
    }
