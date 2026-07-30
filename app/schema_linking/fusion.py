import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal, TypeAlias

from app.connectors.metadata import SchemaSnapshot
from app.schema_linking.index import (
    EmbeddingIndex,
    EmbeddingIndexBuildError,
    _build_schema_documents,
)
from app.schema_linking.models import RRF_K, RerankEvidence

RetrievalChannel: TypeAlias = Literal["bm25", "embedding"]
RetrievalMode: TypeAlias = Literal["hybrid", "bm25_only"]
EmbeddingDegradation: TypeAlias = Literal[
    "timeout",
    "connection",
    "rate_limited",
    "invalid_response",
]
_CHANNEL_ORDER: tuple[RetrievalChannel, ...] = (
    "bm25",
    "embedding",
)
_RETRIEVAL_MODES = frozenset(("hybrid", "bm25_only"))
_EMBEDDING_DEGRADATIONS = frozenset(
    ("timeout", "connection", "rate_limited", "invalid_response")
)


@dataclass(frozen=True, slots=True)
class RRFContribution:
    channel: RetrievalChannel
    rank: int
    value: float


@dataclass(frozen=True, slots=True)
class FusedCandidate:
    object_id: str
    score: float
    contributions: tuple[RRFContribution, ...]


@dataclass(frozen=True, slots=True)
class EmbeddingRankEvidence:
    object_id: str = field(repr=False)
    similarity: float
    rank: int
    source_document_id: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class EmbeddingRanking:
    table_ranks: tuple[EmbeddingRankEvidence, ...]
    field_ranks: tuple[EmbeddingRankEvidence, ...]


@dataclass(frozen=True, slots=True)
class RetrievalEvidence:
    object_id: str = field(repr=False)
    bm25_rank: int | None
    bm25_score: float
    embedding_rank: int | None
    embedding_similarity: float | None
    fusion_rank: int | None
    fusion_score: float
    contributions: tuple[RRFContribution, ...]


@dataclass(frozen=True, slots=True, weakref_slot=True)
class SchemaRetrievalPool:
    query_sha256: str
    schema_version: str
    authorization_scope_sha256: str
    retrieval_version_id: str
    retrieval_version_contract: Literal[
        "retrieval-version-v1"
    ]
    bm25_version: Literal["bm25-v1"]
    embedding_provider_contract_version: Literal[
        "openai-compatible-embedding-v1"
    ]
    embedding_provider_config_sha256: str
    document_version: Literal["schema-doc-v1"]
    fusion_version: Literal["rrf-v1"]
    rrf_k: Literal[60]
    rerank_version: Literal["schema-rerank-v2"]
    mode: RetrievalMode
    ranked_table_ids: tuple[str, ...] = field(repr=False)
    ranked_field_ids: tuple[str, ...] = field(repr=False)
    table_evidence: tuple[RetrievalEvidence, ...] = field(
        repr=False
    )
    field_evidence: tuple[RetrievalEvidence, ...] = field(
        repr=False
    )
    reranked_table_ids: tuple[str, ...] = field(repr=False)
    rerank_evidence: tuple[RerankEvidence, ...] = field(
        repr=False
    )
    bm25_duration_ms: float = field(default=0.0, compare=False)
    embedding_duration_ms: float = field(
        default=0.0,
        compare=False,
    )
    rrf_duration_ms: float = field(default=0.0, compare=False)
    rerank_duration_ms: float = field(
        default=0.0,
        compare=False,
    )
    embedding_degradation: EmbeddingDegradation | None = None
    rerank_degraded: bool = False

    def __post_init__(self) -> None:
        hashes = (
            self.query_sha256,
            self.schema_version,
            self.authorization_scope_sha256,
            self.retrieval_version_id,
            self.embedding_provider_config_sha256,
        )
        durations_ms = (
            self.bm25_duration_ms,
            self.embedding_duration_ms,
            self.rrf_duration_ms,
            self.rerank_duration_ms,
        )
        fusion_ids = {
            evidence.object_id
            for evidence in self.table_evidence
            if evidence.fusion_rank is not None
        }
        rerank_ids = {
            evidence.object_id
            for evidence in self.rerank_evidence
        }
        if (
            any(
                len(value) != 64
                or any(
                    character not in "0123456789abcdef"
                    for character in value
                )
                for value in hashes
            )
            or any(
                type(value) not in (int, float)
                or not math.isfinite(float(value))
                or value < 0
                for value in durations_ms
            )
            or self.mode not in _RETRIEVAL_MODES
            or self.retrieval_version_contract
            != "retrieval-version-v1"
            or self.bm25_version != "bm25-v1"
            or self.embedding_provider_contract_version
            != "openai-compatible-embedding-v1"
            or self.document_version != "schema-doc-v1"
            or self.fusion_version != "rrf-v1"
            or self.rrf_k != 60
            or self.rerank_version != "schema-rerank-v2"
            or (
                self.embedding_degradation is not None
                and self.embedding_degradation
                not in _EMBEDDING_DEGRADATIONS
            )
            or len(set(self.ranked_table_ids))
            != len(self.ranked_table_ids)
            or len(set(self.ranked_field_ids))
            != len(self.ranked_field_ids)
            or set(self.reranked_table_ids)
            != set(self.ranked_table_ids)
            or len(set(self.reranked_table_ids))
            != len(self.reranked_table_ids)
            or not fusion_ids.issubset(rerank_ids)
            or not rerank_ids.issubset(
                set(self.ranked_table_ids)
            )
            or tuple(
                evidence.rerank_rank
                for evidence in self.rerank_evidence
            )
            != tuple(
                range(1, len(self.rerank_evidence) + 1)
            )
            or tuple(
                evidence.object_id
                for evidence in self.rerank_evidence
            )
            != self.reranked_table_ids[
                : len(self.rerank_evidence)
            ]
            or (
                self.mode == "hybrid"
                and self.embedding_degradation is not None
            )
            or (
                self.mode == "bm25_only"
                and self.embedding_degradation is None
            )
            or type(self.rerank_degraded) is not bool
        ):
            raise ValueError("schema retrieval pool is invalid")

    def __repr__(self) -> str:
        return (
            "SchemaRetrievalPool("
            f"retrieval_version_id={self.retrieval_version_id!r}, "
            f"mode={self.mode!r}, "
            f"table_count={len(self.ranked_table_ids)}, "
            f"field_count={len(self.ranked_field_ids)}, "
            f"embedding_degradation="
            f"{self.embedding_degradation!r}, "
            f"rerank_degraded={self.rerank_degraded!r})"
        )


def _unit_vector(
    value: object,
    *,
    dimension: int,
) -> tuple[float, ...]:
    if not isinstance(value, tuple) or len(value) != dimension:
        raise EmbeddingIndexBuildError() from None
    vector: list[float] = []
    for component in value:
        if type(component) not in (int, float):
            raise EmbeddingIndexBuildError() from None
        number = float(component)
        if not math.isfinite(number):
            raise EmbeddingIndexBuildError() from None
        vector.append(number)
    norm = math.hypot(*vector)
    if not math.isfinite(norm) or norm == 0:
        raise EmbeddingIndexBuildError() from None
    return tuple(component / norm for component in vector)


def rank_embedding_index(
    *,
    index: EmbeddingIndex,
    query_vector: tuple[float, ...],
    authorized_snapshot: SchemaSnapshot,
    limit: int = 20,
) -> EmbeddingRanking:
    expected_documents = _build_schema_documents(
        authorized_snapshot
    )
    if (
        type(limit) is not int
        or not 1 <= limit <= 20
        or index.retrieval_version.schema_version
        != authorized_snapshot.schema_version
        or len(index.documents) != len(index.vectors)
        or index.documents != expected_documents
    ):
        raise EmbeddingIndexBuildError() from None

    table_ids = {
        f"{table.schema_name}.{table.table_name}"
        for table in authorized_snapshot.tables
    }
    field_to_table = {
        (
            f"{table.schema_name}.{table.table_name}."
            f"{column.column_name}"
        ): f"{table.schema_name}.{table.table_name}"
        for table in authorized_snapshot.tables
        for column in table.columns
    }
    expected_document_ids = {*table_ids, *field_to_table}
    observed_document_ids: set[str] = set()
    query = _unit_vector(
        query_vector,
        dimension=index.retrieval_version.embedding_dimension,
    )
    best_table_scores: dict[str, tuple[float, str]] = {}
    field_scores: dict[str, float] = {}

    for document, stored_vector in zip(
        index.documents,
        index.vectors,
        strict=True,
    ):
        if (
            document.object_id in observed_document_ids
            or any(
                table_id not in table_ids
                for table_id in document.table_ids
            )
        ):
            raise EmbeddingIndexBuildError() from None
        observed_document_ids.add(document.object_id)
        vector = _unit_vector(
            stored_vector,
            dimension=index.retrieval_version.embedding_dimension,
        )
        if document.kind == "table":
            if (
                document.object_id not in table_ids
                or document.table_ids != (document.object_id,)
            ):
                raise EmbeddingIndexBuildError() from None
            parent_table = document.object_id
        elif document.kind == "field":
            parent_table = field_to_table.get(document.object_id)
            if (
                parent_table is None
                or document.table_ids != (parent_table,)
            ):
                raise EmbeddingIndexBuildError() from None
        elif document.kind in {"primary_key", "foreign_key"}:
            continue
        else:
            raise EmbeddingIndexBuildError() from None

        similarity = sum(
            left * right
            for left, right in zip(query, vector, strict=True)
        )
        if not math.isfinite(similarity):
            raise EmbeddingIndexBuildError() from None
        if document.kind == "field":
            field_scores[document.object_id] = similarity
        current = best_table_scores.get(parent_table)
        if (
            current is None
            or similarity > current[0]
            or (
                similarity == current[0]
                and document.object_id < current[1]
            )
        ):
            best_table_scores[parent_table] = (
                similarity,
                document.object_id,
            )

    if not expected_document_ids.issubset(observed_document_ids):
        raise EmbeddingIndexBuildError() from None

    ranked_tables = sorted(
        (
            (object_id, score, source_document_id)
            for object_id, (
                score,
                source_document_id,
            ) in best_table_scores.items()
            if score > 0
        ),
        key=lambda item: (-item[1], item[0]),
    )[:limit]
    ranked_fields = sorted(
        (
            (object_id, score)
            for object_id, score in field_scores.items()
            if score > 0
        ),
        key=lambda item: (-item[1], item[0]),
    )[:limit]
    return EmbeddingRanking(
        table_ranks=tuple(
            EmbeddingRankEvidence(
                object_id=object_id,
                similarity=similarity,
                rank=rank,
                source_document_id=source_document_id,
            )
            for rank, (
                object_id,
                similarity,
                source_document_id,
            ) in enumerate(ranked_tables, start=1)
        ),
        field_ranks=tuple(
            EmbeddingRankEvidence(
                object_id=object_id,
                similarity=similarity,
                rank=rank,
                source_document_id=object_id,
            )
            for rank, (object_id, similarity)
            in enumerate(ranked_fields, start=1)
        ),
    )


def reciprocal_rank_fusion(
    channels: Mapping[RetrievalChannel, tuple[str, ...]],
    *,
    k: int = RRF_K,
) -> tuple[FusedCandidate, ...]:
    if (
        type(k) is not int
        or k <= 0
        or not isinstance(channels, Mapping)
    ):
        raise ValueError("RRF input is invalid") from None
    try:
        if any(channel not in _CHANNEL_ORDER for channel in channels):
            raise ValueError
        contributions_by_object: dict[
            str,
            list[RRFContribution],
        ] = {}
        for channel in _CHANNEL_ORDER:
            ranks = channels.get(channel, ())
            if not isinstance(ranks, tuple):
                raise ValueError
            seen: set[str] = set()
            unique_rank = 0
            for object_id in ranks:
                if (
                    not isinstance(object_id, str)
                    or not object_id
                    or object_id != object_id.strip()
                ):
                    raise ValueError
                if object_id in seen:
                    continue
                seen.add(object_id)
                unique_rank += 1
                contributions_by_object.setdefault(
                    object_id,
                    [],
                ).append(
                    RRFContribution(
                        channel=channel,
                        rank=unique_rank,
                        value=1 / (k + unique_rank),
                    )
                )
    except (TypeError, ValueError):
        raise ValueError("RRF input is invalid") from None

    fused = tuple(
        FusedCandidate(
            object_id=object_id,
            score=sum(
                contribution.value
                for contribution in contributions
            ),
            contributions=tuple(contributions),
        )
        for object_id, contributions
        in contributions_by_object.items()
    )
    return tuple(
        sorted(
            fused,
            key=lambda candidate: (
                -candidate.score,
                candidate.object_id,
            ),
        )
    )
