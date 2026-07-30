from collections.abc import Sequence

import pytest

from app.connectors.metadata import (
    ColumnMetadata,
    ForeignKeyMetadata,
    SchemaSnapshot,
    TableMetadata,
    build_schema_snapshot,
)
from app.generation import (
    GenerationContext,
    GenerationResult,
    GeneratedSQL,
    LLMMessage,
    generate_sql,
)
from app.schema_linking import link_schema
from app.validation import validate_sql


def _table(table_name: str, *column_names: str) -> TableMetadata:
    return TableMetadata(
        schema_name="public",
        table_name=table_name,
        relation_kind="table",
        comment=None,
        columns=tuple(
            ColumnMetadata(
                schema_name="public",
                table_name=table_name,
                column_name=column_name,
                ordinal_position=position,
                data_type=(
                    "int4" if column_name.endswith("_id") else "text"
                ),
                formatted_type=(
                    "integer"
                    if column_name.endswith("_id")
                    else "text"
                ),
                nullable=False,
                comment=None,
            )
            for position, column_name in enumerate(
                column_names,
                start=1,
            )
        ),
    )


FILM = _table("film", "film_id", "title", "language_id")
LANGUAGE = _table("language", "language_id", "name")
FILM_LANGUAGE = ForeignKeyMetadata(
    constraint_name="film_language_id_fkey",
    source_schema="public",
    source_table="film",
    source_columns=("language_id",),
    target_schema="public",
    target_table="language",
    target_columns=("language_id",),
)


def _snapshot(
    tables: tuple[TableMetadata, ...],
    foreign_keys: tuple[ForeignKeyMetadata, ...] = (),
) -> SchemaSnapshot:
    return build_schema_snapshot(
        tables=tables,
        primary_keys=(),
        foreign_keys=foreign_keys,
        unique_constraints=(),
        unique_indexes=(),
    )


class FixedProvider:
    def __init__(self, output: GeneratedSQL) -> None:
        self.output = output
        self.calls = 0

    def generate(
        self,
        messages: Sequence[LLMMessage],
        *,
        timeout_seconds: float | None = None,
    ) -> GenerationResult:
        del timeout_seconds
        self.calls += 1
        return GenerationResult(
            output=self.output,
            input_tokens=20,
            output_tokens=10,
            model="fixed-stub",
            prompt_version="mvp-v1",
        )


@pytest.mark.integration
@pytest.mark.parametrize(
    ("question", "snapshot", "allowed_tables", "model_output"),
    [
        (
            "film title",
            _snapshot((FILM,)),
            ("public.film",),
            GeneratedSQL(sql="SELECT film_id, title FROM film"),
        ),
        (
            "film language",
            _snapshot((FILM, LANGUAGE), (FILM_LANGUAGE,)),
            ("public.film", "public.language"),
            GeneratedSQL(
                sql=(
                    "SELECT f.title, l.name "
                    "FROM film AS f "
                    "JOIN language AS l "
                    "ON l.language_id = f.language_id"
                )
            ),
        ),
    ],
)
def test_link_generate_validate_pipeline(
    question: str,
    snapshot: SchemaSnapshot,
    allowed_tables: tuple[str, ...],
    model_output: GeneratedSQL,
) -> None:
    linking = link_schema(
        question,
        allowed_schemas=("public",),
        allowed_tables=allowed_tables,
        snapshot=snapshot,
        top_k=10,
    )
    provider = FixedProvider(model_output)

    generated = generate_sql(
        GenerationContext(
            question=question,
            normalized_question=question,
            normalized_time=None,
            dialect="postgres",
            schema_linking=linking,
            snapshot=snapshot,
        ),
        provider=provider,
    )
    validation = validate_sql(
        generated.output.sql or "",
        allowed_schemas=("public",),
        allowed_tables=allowed_tables,
        snapshot=snapshot,
    )

    assert provider.calls == 1
    assert linking.schema_version == snapshot.schema_version
    assert validation.is_valid, validation.issue


@pytest.mark.integration
def test_clarification_output_stops_before_validation() -> None:
    snapshot = _snapshot((FILM,))
    linking = link_schema(
        "film",
        allowed_schemas=("public",),
        allowed_tables=("public.film",),
        snapshot=snapshot,
        top_k=10,
    )
    provider = FixedProvider(
        GeneratedSQL(clarification_reason="Which date range?")
    )

    generated = generate_sql(
        GenerationContext(
            question="Show recent films",
            normalized_question="Show recent films",
            normalized_time=None,
            dialect="postgres",
            schema_linking=linking,
            snapshot=snapshot,
        ),
        provider=provider,
    )

    assert generated.output.sql is None
    assert generated.output.clarification_reason == "Which date range?"
    assert provider.calls == 1
