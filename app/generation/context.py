from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Literal

from app.generation.models import GenerationContext, LLMMessage
from app.generation.prompt import build_generation_messages

CONTEXT_ESTIMATOR_VERSION = "utf8-bytes-div-3-v1"
CONTEXT_INPUT_BUDGET_NUMERATOR = 4
CONTEXT_INPUT_BUDGET_DENOMINATOR = 5

ContextSelectionErrorCode = Literal[
    "CONTEXT_LIMITS_INVALID",
    "CONTEXT_REQUIRED_OVERFLOW",
]


class ContextSelectionError(RuntimeError):
    def __init__(
        self,
        code: ContextSelectionErrorCode,
        *,
        candidate_field_count: int | None = None,
        required_field_count: int | None = None,
        estimated_tokens: int | None = None,
        usable_input_tokens: int | None = None,
    ) -> None:
        super().__init__("generation context selection failed")
        self.code = code
        self.candidate_field_count = candidate_field_count
        self.required_field_count = required_field_count
        self.estimated_tokens = estimated_tokens
        self.usable_input_tokens = usable_input_tokens


@dataclass(frozen=True, slots=True)
class ContextSelection:
    field_ids: tuple[str, ...]
    required_field_count: int
    selected_field_count: int
    pruned_field_count: int
    estimated_tokens: int
    usable_input_tokens: int
    estimator_version: Literal[
        "utf8-bytes-div-3-v1"
    ] = CONTEXT_ESTIMATOR_VERSION


def estimate_message_tokens(
    messages: Sequence[LLMMessage],
) -> int:
    if (
        isinstance(messages, (str, bytes, bytearray))
        or not isinstance(messages, Sequence)
        or any(
            not isinstance(message, LLMMessage)
            for message in messages
        )
    ):
        raise ValueError("generation messages are invalid")
    byte_count = sum(
        len(message.content.encode("utf-8"))
        for message in messages
    )
    return math.ceil(byte_count / 3)


def _field_sort_key(
    object_id: str,
    *,
    scores: dict[str, float],
    table_ranks: dict[str, int],
) -> tuple[float, int, str]:
    return (
        -scores[object_id],
        table_ranks[object_id.rsplit(".", 1)[0]],
        object_id,
    )


def _ordered_field_ids(
    context: GenerationContext,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    fields = {
        field.object_id: field
        for field in context.schema_linking.candidate_fields
    }
    scores = {
        object_id: float(field.score)
        for object_id, field in fields.items()
    }
    table_ranks = {
        table.object_id: rank
        for rank, table in enumerate(
            context.schema_linking.candidate_tables
        )
    }
    def sort_key(object_id: str) -> tuple[float, int, str]:
        return _field_sort_key(
            object_id,
            scores=scores,
            table_ranks=table_ranks,
        )

    direct_ids = tuple(
        sorted(
            (
                object_id
                for object_id, field in fields.items()
                if field.matched_tokens
            ),
            key=sort_key,
        )
    )
    seen = set(direct_ids)
    join_ids: list[str] = []
    for path in context.schema_linking.join_paths:
        for edge in path.edges:
            for table_id, columns in (
                (edge.source_table, edge.source_columns),
                (edge.target_table, edge.target_columns),
            ):
                for column in columns:
                    object_id = f"{table_id}.{column}"
                    if object_id in fields and object_id not in seen:
                        join_ids.append(object_id)
                        seen.add(object_id)

    positive_ids = tuple(
        sorted(
            (
                object_id
                for object_id, field in fields.items()
                if field.score > 0 and object_id not in seen
            ),
            key=sort_key,
        )
    )
    seen.update(positive_ids)
    retrieval_pool = context.schema_linking.retrieval_pool
    embedding_evidence = (
        {
            evidence.object_id: evidence
            for evidence in retrieval_pool.field_evidence
            if (
                evidence.object_id in fields
                and evidence.embedding_rank is not None
                and evidence.embedding_similarity is not None
                and evidence.embedding_similarity > 0
            )
        }
        if retrieval_pool is not None
        else {}
    )
    embedding_ids = tuple(
        sorted(
            (
                object_id
                for object_id in embedding_evidence
                if object_id not in seen
            ),
            key=lambda object_id: (
                embedding_evidence[object_id].fusion_rank
                if embedding_evidence[object_id].fusion_rank
                is not None
                else len(fields) + 1,
                embedding_evidence[object_id].embedding_rank,
                table_ranks[
                    object_id.rsplit(".", 1)[0]
                ],
                object_id,
            ),
        )
    )
    seen.update(embedding_ids)
    required_ids = (
        *direct_ids,
        *join_ids,
        *positive_ids,
        *embedding_ids,
    )
    optional_ids = tuple(
        sorted(
            (
                object_id
                for object_id in fields
                if object_id not in seen
            ),
            key=sort_key,
        )
    )
    return required_ids, optional_ids


def _estimate_context(
    context: GenerationContext,
    field_ids: tuple[str, ...],
) -> int:
    return estimate_message_tokens(
        build_generation_messages(
            replace(
                context,
                selected_field_ids=field_ids,
            )
        )
    )


def select_generation_context(
    context: GenerationContext,
    *,
    max_input_tokens: int,
    max_output_tokens: int,
) -> ContextSelection:
    if (
        type(max_input_tokens) is not int
        or type(max_output_tokens) is not int
        or max_input_tokens <= 0
        or max_output_tokens <= 0
        or max_output_tokens >= max_input_tokens
    ):
        raise ContextSelectionError(
            "CONTEXT_LIMITS_INVALID"
        ) from None

    usable_input_tokens = (
        max_input_tokens
        * CONTEXT_INPUT_BUDGET_NUMERATOR
        // CONTEXT_INPUT_BUDGET_DENOMINATOR
        - max_output_tokens
    )
    required_ids, optional_ids = _ordered_field_ids(context)
    estimated_tokens = _estimate_context(
        context,
        required_ids,
    )
    if estimated_tokens > usable_input_tokens:
        raise ContextSelectionError(
            "CONTEXT_REQUIRED_OVERFLOW",
            candidate_field_count=len(
                context.schema_linking.candidate_fields
            ),
            required_field_count=len(required_ids),
            estimated_tokens=estimated_tokens,
            usable_input_tokens=usable_input_tokens,
        ) from None

    selected_ids = required_ids
    for object_id in optional_ids:
        candidate_ids = (*selected_ids, object_id)
        candidate_tokens = _estimate_context(
            context,
            candidate_ids,
        )
        if candidate_tokens <= usable_input_tokens:
            selected_ids = candidate_ids
            estimated_tokens = candidate_tokens

    total_fields = len(
        context.schema_linking.candidate_fields
    )
    return ContextSelection(
        field_ids=selected_ids,
        required_field_count=len(required_ids),
        selected_field_count=len(selected_ids),
        pruned_field_count=total_fields - len(selected_ids),
        estimated_tokens=estimated_tokens,
        usable_input_tokens=usable_input_tokens,
    )
