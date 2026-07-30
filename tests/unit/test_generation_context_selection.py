from dataclasses import replace

import pytest

from app.generation import build_generation_messages
from app.schema_linking import (
    RRFContribution,
    RetrievalEvidence,
    SchemaRetrievalPool,
)
from tests.unit.test_generation_prompt import _context


def _selection_context():
    context = _context()
    fields = tuple(
        replace(
            field,
            score=(
                1.0
                if field.object_id == "public.language.name"
                else 0.0
            ),
            matched_tokens=(
                ("title",)
                if field.object_id == "public.film.title"
                else ()
            ),
        )
        for field in context.schema_linking.candidate_fields
    )
    return replace(
        context,
        schema_linking=replace(
            context.schema_linking,
            candidate_fields=fields,
        ),
    )


def _embedding_only_selection_context():
    context = _selection_context()
    fields = tuple(
        replace(
            field,
            score=(
                1.0
                if field.object_id == "public.language.name"
                else 0.0
            ),
            matched_tokens=(
                ("filter", "aggregate", "time")
                if field.object_id == "public.language.name"
                else ()
            ),
        )
        for field in context.schema_linking.candidate_fields
    )
    ranked_field_ids = (
        "public.film.title",
        *(
            field.object_id
            for field in fields
            if field.object_id != "public.film.title"
        ),
    )
    field_evidence = tuple(
        RetrievalEvidence(
            object_id=object_id,
            bm25_rank=None,
            bm25_score=0.0,
            embedding_rank=(
                1 if object_id == "public.film.title" else None
            ),
            embedding_similarity=(
                0.9
                if object_id == "public.film.title"
                else None
            ),
            fusion_rank=(
                1 if object_id == "public.film.title" else None
            ),
            fusion_score=(
                1 / 61
                if object_id == "public.film.title"
                else 0.0
            ),
            contributions=(
                (
                    RRFContribution(
                        channel="embedding",
                        rank=1,
                        value=1 / 61,
                    ),
                )
                if object_id == "public.film.title"
                else ()
            ),
        )
        for object_id in ranked_field_ids
    )
    table_ids = tuple(
        table.object_id
        for table in context.schema_linking.candidate_tables
    )
    table_evidence = tuple(
        RetrievalEvidence(
            object_id=object_id,
            bm25_rank=None,
            bm25_score=0.0,
            embedding_rank=None,
            embedding_similarity=None,
            fusion_rank=None,
            fusion_score=0.0,
            contributions=(),
        )
        for object_id in table_ids
    )
    retrieval_version_id = "b" * 64
    pool = SchemaRetrievalPool(
        query_sha256="a" * 64,
        schema_version=context.snapshot.schema_version,
        authorization_scope_sha256="c" * 64,
        retrieval_version_id=retrieval_version_id,
        retrieval_version_contract="retrieval-version-v1",
        bm25_version="bm25-v1",
        embedding_provider_contract_version=(
            "openai-compatible-embedding-v1"
        ),
        embedding_provider_config_sha256="d" * 64,
        document_version="schema-doc-v1",
        fusion_version="rrf-v1",
        rrf_k=60,
        rerank_version="schema-rerank-v2",
        mode="hybrid",
        ranked_table_ids=table_ids,
        ranked_field_ids=ranked_field_ids,
        table_evidence=table_evidence,
        field_evidence=field_evidence,
        reranked_table_ids=table_ids,
        rerank_evidence=(),
    )
    return replace(
        context,
        schema_linking=replace(
            context.schema_linking,
            candidate_fields=fields,
            retrieval_version_id=retrieval_version_id,
            retrieval_pool=pool,
        ),
    )


def test_message_estimator_uses_complete_utf8_contents() -> None:
    from app.generation.context import estimate_message_tokens
    from app.generation.models import LLMMessage

    messages = (
        LLMMessage(role="system", content="abc"),
        LLMMessage(role="user", content="中"),
    )

    assert estimate_message_tokens(messages) == 2


def test_selector_orders_direct_join_positive_then_optional_fields() -> None:
    from app.generation.context import select_generation_context

    selection = select_generation_context(
        _selection_context(),
        max_input_tokens=32_768,
        max_output_tokens=2_048,
    )

    assert selection.field_ids == (
        "public.film.title",
        "public.film.language_id",
        "public.language.language_id",
        "public.language.name",
        "public.film.film_id",
    )
    assert selection.required_field_count == 4
    assert selection.selected_field_count == 5
    assert selection.estimated_tokens <= (
        selection.usable_input_tokens
    )


def test_selector_prunes_optional_fields_at_exact_required_budget() -> None:
    from app.generation.context import (
        estimate_message_tokens,
        select_generation_context,
    )

    context = _selection_context()
    required_ids = (
        "public.film.title",
        "public.film.language_id",
        "public.language.language_id",
        "public.language.name",
    )
    required_messages = build_generation_messages(
        replace(context, selected_field_ids=required_ids)
    )
    required_tokens = estimate_message_tokens(
        required_messages
    )
    max_output_tokens = 10
    max_input_tokens = 1
    while (
        max_input_tokens * 4 // 5 - max_output_tokens
        < required_tokens
    ):
        max_input_tokens += 1

    selection = select_generation_context(
        context,
        max_input_tokens=max_input_tokens,
        max_output_tokens=max_output_tokens,
    )

    assert selection.field_ids == required_ids
    assert selection.estimated_tokens <= required_tokens
    assert selection.pruned_field_count == 1


def test_tight_budget_keeps_embedding_business_and_join_key_evidence() -> None:
    from app.generation.context import (
        estimate_message_tokens,
        select_generation_context,
    )

    context = _embedding_only_selection_context()
    required_ids = (
        "public.language.name",
        "public.film.language_id",
        "public.language.language_id",
        "public.film.title",
    )
    required_messages = build_generation_messages(
        replace(context, selected_field_ids=required_ids)
    )
    required_tokens = estimate_message_tokens(required_messages)
    max_output_tokens = 10
    max_input_tokens = 1
    while (
        max_input_tokens * 4 // 5 - max_output_tokens
        < required_tokens
    ):
        max_input_tokens += 1

    selection = select_generation_context(
        context,
        max_input_tokens=max_input_tokens,
        max_output_tokens=max_output_tokens,
    )

    assert selection.field_ids == required_ids
    assert selection.required_field_count == len(required_ids)
    assert "public.film.film_id" not in selection.field_ids
    assert selection.pruned_field_count == 1


def test_selector_fails_atomically_when_required_context_overflows() -> None:
    from app.generation.context import (
        ContextSelectionError,
        select_generation_context,
    )

    with pytest.raises(ContextSelectionError) as captured:
        select_generation_context(
            _selection_context(),
            max_input_tokens=100,
            max_output_tokens=99,
        )

    assert captured.value.code == "CONTEXT_REQUIRED_OVERFLOW"


@pytest.mark.parametrize(
    ("max_input_tokens", "max_output_tokens"),
    ((True, 10), (100, False), (0, 10), (100, 0), (10, 10)),
)
def test_selector_rejects_invalid_model_limits(
    max_input_tokens: object,
    max_output_tokens: object,
) -> None:
    from app.generation.context import (
        ContextSelectionError,
        select_generation_context,
    )

    with pytest.raises(ContextSelectionError) as captured:
        select_generation_context(
            _selection_context(),
            max_input_tokens=max_input_tokens,  # type: ignore[arg-type]
            max_output_tokens=max_output_tokens,  # type: ignore[arg-type]
        )

    assert captured.value.code == "CONTEXT_LIMITS_INVALID"
