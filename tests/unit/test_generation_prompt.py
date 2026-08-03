import json
from dataclasses import replace

import pytest

from app.connectors.metadata import (
    ColumnMetadata,
    ForeignKeyMetadata,
    PrimaryKeyMetadata,
    TableMetadata,
    build_schema_snapshot,
)
from app.generation import GenerationContext, build_generation_messages
from app.generation.models import MYSQL_PROMPT_VERSION, PROMPT_VERSION
from app.generation.prompt import SYSTEM_PROMPT
from app.schema_linking import (
    CandidateField,
    CandidateTable,
    JoinEdge,
    JoinPath,
    SchemaLinkingResult,
)
from app.validation import ALLOWED_FUNCTIONS


def _table(
    table_name: str,
    *columns: str,
    comment: str | None = None,
    aliases: dict[str, tuple[str, ...]] | None = None,
) -> TableMetadata:
    return TableMetadata(
        schema_name="public",
        table_name=table_name,
        relation_kind="table",
        comment=comment,
        columns=tuple(
            ColumnMetadata(
                schema_name="public",
                table_name=table_name,
                column_name=column_name,
                ordinal_position=position,
                data_type="int4" if column_name.endswith("_id") else "text",
                formatted_type=(
                    "integer" if column_name.endswith("_id") else "text"
                ),
                nullable=False,
                comment=None,
                aliases=(
                    aliases.get(column_name, ())
                    if aliases is not None
                    else ()
                ),
            )
            for position, column_name in enumerate(columns, start=1)
        ),
    )


FILM = _table("film", "film_id", "title", "language_id")
LANGUAGE = _table("language", "language_id", "name")
UNSELECTED = _table(
    "staff",
    "staff_id",
    "email",
    comment="must never enter the generation prompt",
)
FILM_LANGUAGE = ForeignKeyMetadata(
    constraint_name="film_language_id_fkey",
    source_schema="public",
    source_table="film",
    source_columns=("language_id",),
    target_schema="public",
    target_table="language",
    target_columns=("language_id",),
)
SNAPSHOT = build_schema_snapshot(
    tables=(FILM, LANGUAGE, UNSELECTED),
    primary_keys=(
        PrimaryKeyMetadata(
            constraint_name="film_pkey",
            schema_name="public",
            table_name="film",
            columns=("film_id",),
        ),
        PrimaryKeyMetadata(
            constraint_name="language_pkey",
            schema_name="public",
            table_name="language",
            columns=("language_id",),
        ),
        PrimaryKeyMetadata(
            constraint_name="staff_pkey",
            schema_name="public",
            table_name="staff",
            columns=("staff_id",),
        ),
    ),
    foreign_keys=(FILM_LANGUAGE,),
    unique_constraints=(),
    unique_indexes=(),
)
EDGE = JoinEdge(
    constraint_name=FILM_LANGUAGE.constraint_name,
    source_table="public.film",
    source_columns=FILM_LANGUAGE.source_columns,
    target_table="public.language",
    target_columns=FILM_LANGUAGE.target_columns,
)
LINKING = SchemaLinkingResult(
    candidate_tables=tuple(
        CandidateTable(
            object_id=f"public.{table.table_name}",
            schema_name="public",
            table_name=table.table_name,
            relation_kind=table.relation_kind,
            comment=table.comment,
            score=2.0,
            matched_tokens=(table.table_name,),
        )
        for table in (FILM, LANGUAGE)
    ),
    candidate_fields=tuple(
        CandidateField(
            object_id=f"public.{table.table_name}.{column.column_name}",
            schema_name="public",
            table_name=table.table_name,
            column_name=column.column_name,
            formatted_type=column.formatted_type,
            nullable=column.nullable,
            comment=column.comment,
            score=1.0,
            matched_tokens=(column.column_name,),
        )
        for table in (FILM, LANGUAGE)
        for column in table.columns
    ),
    join_paths=(
        JoinPath(
            tables=("public.film", "public.language"),
            edges=(EDGE,),
        ),
    ),
    schema_version=SNAPSHOT.schema_version,
    top_k=10,
)


def _context() -> GenerationContext:
    return GenerationContext(
        question="列出影片标题和语言名称",
        normalized_question="列出影片标题和语言名称",
        normalized_time="2026-07-28T00:00:00+08:00",
        dialect="postgres",
        schema_linking=LINKING,
        snapshot=SNAPSHOT,
    )


def test_prompt_is_deterministic_and_contains_explicit_safety_rules() -> None:
    first = build_generation_messages(_context())
    second = build_generation_messages(_context())

    assert first == second
    assert tuple(message.role for message in first) == (
        "system",
        "user",
    )
    system = first[0].content.lower()
    assert "postgresql" in system
    assert "single" in system
    assert "read-only" in system
    assert "wildcard" in system
    assert "max_result_rows" in system
    assert "allowed_functions" in system
    assert "clarification_reason" in system
    assert "json" in system


def test_mysql_prompt_is_separate_and_keeps_postgresql_prompt_unchanged(
) -> None:
    postgres_messages = build_generation_messages(_context())
    mysql_messages = build_generation_messages(
        replace(_context(), dialect="mysql")
    )
    mysql_payload = json.loads(mysql_messages[1].content)

    assert postgres_messages[0].content == SYSTEM_PROMPT
    assert postgres_messages[0].prompt_version == PROMPT_VERSION
    assert "MySQL" in mysql_messages[0].content
    assert "PostgreSQL" not in mysql_messages[0].content
    assert mysql_messages[0].prompt_version == MYSQL_PROMPT_VERSION
    assert mysql_messages[1].prompt_version == MYSQL_PROMPT_VERSION
    assert mysql_payload["prompt_version"] == MYSQL_PROMPT_VERSION
    assert mysql_payload["dialect"] == "mysql"
    assert "COUNT" in mysql_payload["allowed_functions"]
    assert "DATE_TRUNC" not in mysql_payload["allowed_functions"]


def test_prompt_serializes_only_candidate_schema_context() -> None:
    messages = build_generation_messages(_context())
    payload = json.loads(messages[1].content)

    assert payload["question"] == "列出影片标题和语言名称"
    assert payload["prompt_version"] == PROMPT_VERSION
    assert payload["normalized_time"] == "2026-07-28T00:00:00+08:00"
    assert payload["dialect"] == "postgres"
    assert payload["schema_version"] == SNAPSHOT.schema_version
    assert payload["max_result_rows"] == 1000
    assert payload["allowed_functions"] == list(ALLOWED_FUNCTIONS)
    assert {
        table["object_id"] for table in payload["candidate_tables"]
    } == {"public.film", "public.language"}
    assert {
        field["object_id"] for field in payload["candidate_fields"]
    } == {
        "public.film.film_id",
        "public.film.title",
        "public.film.language_id",
        "public.language.language_id",
        "public.language.name",
    }
    assert {
        key["table"] for key in payload["primary_keys"]
    } == {"public.film", "public.language"}
    assert payload["foreign_keys"] == [
        {
            "constraint_name": "film_language_id_fkey",
            "source_columns": ["language_id"],
            "source_table": "public.film",
            "target_columns": ["language_id"],
            "target_table": "public.language",
        }
    ]
    assert payload["join_paths"][0]["tables"] == [
        "public.film",
        "public.language",
    ]
    assert "public.staff" not in messages[1].content
    assert "must never enter" not in messages[1].content


def test_prompt_projects_selected_fields_and_matching_keys() -> None:
    selected = (
        "public.film.title",
        "public.film.language_id",
        "public.language.language_id",
    )
    messages = build_generation_messages(
        replace(_context(), selected_field_ids=selected)
    )
    payload = json.loads(messages[1].content)

    assert tuple(
        field["object_id"]
        for field in payload["candidate_fields"]
    ) == selected
    assert payload["primary_keys"] == [
        {
            "constraint_name": "language_pkey",
            "table": "public.language",
            "columns": ["language_id"],
        }
    ]
    assert payload["foreign_keys"] == [
        {
            "constraint_name": "film_language_id_fkey",
            "source_columns": ["language_id"],
            "source_table": "public.film",
            "target_columns": ["language_id"],
            "target_table": "public.language",
        }
    ]
    assert len(payload["join_paths"]) == 1


def test_prompt_omits_keys_and_paths_with_pruned_endpoint_fields() -> None:
    messages = build_generation_messages(
        replace(
            _context(),
            selected_field_ids=("public.film.title",),
        )
    )
    payload = json.loads(messages[1].content)

    assert payload["primary_keys"] == []
    assert payload["foreign_keys"] == []
    assert payload["join_paths"] == []


@pytest.mark.parametrize(
    "selected",
    (
        ("public.staff.staff_id",),
        ("public.film.title", "public.film.title"),
        ["public.film.title"],
    ),
)
def test_prompt_rejects_invalid_field_projection(
    selected: object,
) -> None:
    with pytest.raises(
        ValueError,
        match=r"^generation context is invalid$",
    ):
        build_generation_messages(
            replace(
                _context(),
                selected_field_ids=selected,  # type: ignore[arg-type]
            )
        )


def test_prompt_sources_descriptive_metadata_from_snapshot() -> None:
    context = _context()
    tampered_linking = replace(
        context.schema_linking,
        candidate_tables=(
            replace(
                context.schema_linking.candidate_tables[0],
                relation_kind="forged_kind",
                comment="forged table comment",
            ),
            context.schema_linking.candidate_tables[1],
        ),
        candidate_fields=(
            replace(
                context.schema_linking.candidate_fields[0],
                comment="forged field comment",
            ),
            *context.schema_linking.candidate_fields[1:],
        ),
    )

    messages = build_generation_messages(
        replace(context, schema_linking=tampered_linking)
    )
    payload = json.loads(messages[1].content)

    film_table = next(
        table
        for table in payload["candidate_tables"]
        if table["object_id"] == "public.film"
    )
    film_id = next(
        field
        for field in payload["candidate_fields"]
        if field["object_id"] == "public.film.film_id"
    )
    assert film_table["relation_kind"] == "table"
    assert film_table["comment"] is None
    assert film_id["comment"] is None


def test_prompt_sources_field_aliases_only_from_snapshot() -> None:
    context = _context()
    film_with_alias = _table(
        "film",
        "film_id",
        "title",
        "language_id",
        aliases={"title": ("catalog_name",)},
    )
    snapshot = build_schema_snapshot(
        tables=(film_with_alias, LANGUAGE, UNSELECTED),
        primary_keys=SNAPSHOT.primary_keys,
        foreign_keys=SNAPSHOT.foreign_keys,
        unique_constraints=(),
        unique_indexes=(),
    )
    linking = replace(
        context.schema_linking,
        schema_version=snapshot.schema_version,
    )

    payload = json.loads(
        build_generation_messages(
            replace(
                context,
                schema_linking=linking,
                snapshot=snapshot,
            )
        )[1].content
    )
    title = next(
        field
        for field in payload["candidate_fields"]
        if field["object_id"] == "public.film.title"
    )
    unaliased = next(
        field
        for field in payload["candidate_fields"]
        if field["object_id"] == "public.film.film_id"
    )

    assert title["aliases"] == ["catalog_name"]
    assert unaliased["aliases"] == []
    assert "source_definition_sha256" not in payload
    assert "polarity" not in payload


def _wide_context(
    *,
    table_count: int,
    top_k: int,
) -> GenerationContext:
    tables = tuple(
        _table(f"table_{number:02d}", "entity_id")
        for number in range(table_count)
    )
    snapshot = build_schema_snapshot(
        tables=tables,
        primary_keys=(),
        foreign_keys=(),
        unique_constraints=(),
        unique_indexes=(),
    )
    linking = SchemaLinkingResult(
        candidate_tables=tuple(
            CandidateTable(
                object_id=f"public.{table.table_name}",
                schema_name="public",
                table_name=table.table_name,
                relation_kind="table",
                comment=None,
                score=0.0,
                matched_tokens=(),
            )
            for table in tables
        ),
        candidate_fields=(),
        join_paths=(),
        schema_version=snapshot.schema_version,
        top_k=top_k,  # type: ignore[arg-type]
    )
    return GenerationContext(
        question="list entities",
        normalized_question="list entities",
        normalized_time=None,
        dialect="postgres",
        schema_linking=linking,
        snapshot=snapshot,
    )


def test_prompt_accepts_twenty_candidates_for_twenty_budget() -> None:
    messages = build_generation_messages(
        _wide_context(table_count=20, top_k=20)
    )

    payload = json.loads(messages[1].content)
    assert len(payload["candidate_tables"]) == 20


def test_prompt_rejects_six_candidates_for_five_budget() -> None:

    with pytest.raises(
        ValueError,
        match=r"^generation context is invalid$",
    ):
        build_generation_messages(_wide_context(table_count=6, top_k=5))
