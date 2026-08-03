from dataclasses import replace

import pytest

from app.connectors.metadata import (
    ColumnMetadata,
    TableMetadata,
    build_schema_snapshot,
    empty_schema_snapshot,
)
from app.generation import (
    GenerationContext,
    GenerationResult,
    GeneratedSQL,
    LLMMessage,
    generate_sql,
)
from app.schema_linking import (
    CandidateField,
    CandidateTable,
    JoinEdge,
    JoinPath,
    SchemaLinkingResult,
)


FILM = TableMetadata(
    schema_name="public",
    table_name="film",
    relation_kind="table",
    comment=None,
    columns=(
        ColumnMetadata(
            schema_name="public",
            table_name="film",
            column_name="film_id",
            ordinal_position=1,
            data_type="int4",
            formatted_type="integer",
            nullable=False,
            comment=None,
        ),
    ),
)
SNAPSHOT = build_schema_snapshot(
    tables=(FILM,),
    primary_keys=(),
    foreign_keys=(),
    unique_constraints=(),
    unique_indexes=(),
)
TABLE = CandidateTable(
    object_id="public.film",
    schema_name="public",
    table_name="film",
    relation_kind="table",
    comment=None,
    score=1.0,
    matched_tokens=("film",),
)
FIELD = CandidateField(
    object_id="public.film.film_id",
    schema_name="public",
    table_name="film",
    column_name="film_id",
    formatted_type="integer",
    nullable=False,
    comment=None,
    score=1.0,
    matched_tokens=("film",),
)
LINKING = SchemaLinkingResult(
    candidate_tables=(TABLE,),
    candidate_fields=(FIELD,),
    join_paths=(),
    schema_version=SNAPSHOT.schema_version,
    top_k=10,
)
CONTEXT = GenerationContext(
    question="List film identifiers",
    normalized_question="List film identifiers",
    normalized_time=None,
    dialect="postgres",
    schema_linking=LINKING,
    snapshot=SNAPSHOT,
)


class StubProvider:
    def __init__(self, result: GenerationResult) -> None:
        self.result = result
        self.calls: list[tuple[LLMMessage, ...]] = []

    def generate(
        self,
        messages: tuple[LLMMessage, ...],
        *,
        timeout_seconds: float | None = None,
    ) -> GenerationResult:
        del timeout_seconds
        self.calls.append(messages)
        return self.result


def _provider() -> StubProvider:
    return StubProvider(
        GenerationResult(
            output=GeneratedSQL(sql="SELECT film_id FROM film"),
            input_tokens=42,
            output_tokens=8,
            model="stub-model",
            prompt_version="mvp-v1",
        )
    )


def test_generate_sql_calls_provider_once_and_preserves_result() -> None:
    provider = _provider()

    result = generate_sql(CONTEXT, provider=provider)

    assert result is provider.result
    assert len(provider.calls) == 1
    assert tuple(message.role for message in provider.calls[0]) == (
        "system",
        "user",
    )


def _fabricated_path() -> tuple[JoinPath, ...]:
    edge = JoinEdge(
        constraint_name="fabricated_fkey",
        source_table="public.film",
        source_columns=("film_id",),
        target_table="public.film",
        target_columns=("film_id",),
    )
    return (
        JoinPath(
            tables=("public.film", "public.film"),
            edges=(edge,),
        ),
    )


@pytest.mark.parametrize(
    "context",
    [
        replace(CONTEXT, question="   "),
        replace(CONTEXT, dialect="sqlite"),
        replace(CONTEXT, max_result_rows=0),
        replace(CONTEXT, max_result_rows=1001),
        replace(CONTEXT, max_result_rows=True),
        replace(
            CONTEXT,
            schema_linking=replace(
                LINKING,
                candidate_tables=(),
                candidate_fields=(),
            ),
        ),
        replace(CONTEXT, snapshot=empty_schema_snapshot()),
        replace(
            CONTEXT,
            schema_linking=replace(
                LINKING,
                candidate_tables=(
                    replace(
                        TABLE,
                        object_id="public.staff",
                        table_name="staff",
                    ),
                ),
            ),
        ),
        replace(
            CONTEXT,
            schema_linking=replace(
                LINKING,
                candidate_fields=(
                    replace(
                        FIELD,
                        object_id="public.film.missing",
                        column_name="missing",
                    ),
                ),
            ),
        ),
        replace(
            CONTEXT,
            schema_linking=replace(
                LINKING,
                join_paths=_fabricated_path(),
            ),
        ),
    ],
)
def test_invalid_context_never_calls_provider(
    context: GenerationContext,
) -> None:
    provider = _provider()

    with pytest.raises(
        ValueError,
        match=r"^generation context is invalid$",
    ):
        generate_sql(context, provider=provider)

    assert provider.calls == []
