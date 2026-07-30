from dataclasses import FrozenInstanceError

import pytest

from app.schema_linking import (
    CandidateField,
    CandidateTable,
    JoinEdge,
    JoinPath,
    SchemaLinkingResult,
)


def test_schema_linking_contracts_are_immutable_and_tuple_based() -> None:
    table = CandidateTable(
        object_id="public.film",
        schema_name="public",
        table_name="film",
        relation_kind="table",
        comment="Movies available in the store",
        score=4.25,
        matched_tokens=("film",),
    )
    field = CandidateField(
        object_id="public.film.title",
        schema_name="public",
        table_name="film",
        column_name="title",
        formatted_type="character varying(255)",
        nullable=False,
        comment="Movie title",
        score=2.5,
        matched_tokens=("title",),
    )
    edge = JoinEdge(
        constraint_name="film_language_id_fkey",
        source_table="public.film",
        source_columns=("language_id",),
        target_table="public.language",
        target_columns=("language_id",),
    )
    path = JoinPath(
        tables=("public.film", "public.language"),
        edges=(edge,),
    )
    result = SchemaLinkingResult(
        candidate_tables=(table,),
        candidate_fields=(field,),
        join_paths=(path,),
        schema_version="snapshot-v1",
        top_k=10,
    )

    assert isinstance(result.candidate_tables, tuple)
    assert isinstance(result.candidate_fields, tuple)
    assert isinstance(result.join_paths, tuple)
    assert result.top_k == 10
    assert table.object_id == "public.film"
    assert field.object_id == "public.film.title"
    assert path.edges == (edge,)

    with pytest.raises(FrozenInstanceError):
        table.score = 0.0  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        result.schema_version = "snapshot-v2"  # type: ignore[misc]


@pytest.mark.parametrize("invalid", (True, 6, "20"))
def test_schema_linking_result_rejects_non_closed_budget(
    invalid: object,
) -> None:
    with pytest.raises(
        ValueError,
        match=r"^schema linking context is invalid$",
    ):
        SchemaLinkingResult(
            candidate_tables=(),
            candidate_fields=(),
            join_paths=(),
            schema_version="snapshot-v1",
            top_k=invalid,  # type: ignore[arg-type]
        )
