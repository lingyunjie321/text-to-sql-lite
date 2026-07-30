from __future__ import annotations

import hashlib
import json
import math
import struct
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Literal, TypeAlias, cast

from pydantic import BaseModel, ConfigDict, Field, field_validator

if TYPE_CHECKING:
    from app.schema_linking.fusion import SchemaRetrievalPool

SchemaTopK: TypeAlias = Literal[5, 10, 20]
SUPPORTED_SCHEMA_TOP_KS: tuple[SchemaTopK, ...] = (5, 10, 20)
PROBE_SCHEMA_TOP_K: SchemaTopK = 20
RETRIEVAL_VERSION_CONTRACT = "retrieval-version-v1"
BM25_VERSION = "bm25-v1"
RRF_K = 60


class RetrievalVersion(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
    )

    datasource_id: str = Field(min_length=1)
    authorization_scope_sha256: str = Field(
        pattern=r"^[0-9a-f]{64}$"
    )
    schema_version: str = Field(pattern=r"^[0-9a-f]{64}$")
    semantic_version: str = Field(min_length=1)
    bm25_version: str = Field(min_length=1)
    embedding_provider_contract_version: str = Field(
        min_length=1
    )
    embedding_model: str = Field(min_length=1)
    embedding_dimension: int = Field(ge=1)
    embedding_provider_config_sha256: str = Field(
        pattern=r"^[0-9a-f]{64}$"
    )
    document_version: str = Field(min_length=1)
    fusion_version: str = Field(min_length=1)
    rrf_k: int = Field(ge=1)
    rerank_version: str = Field(min_length=1)

    @field_validator(
        "datasource_id",
        "semantic_version",
        "bm25_version",
        "embedding_provider_contract_version",
        "embedding_model",
        "document_version",
        "fusion_version",
        "rerank_version",
    )
    @classmethod
    def reject_surrounding_whitespace(cls, value: str) -> str:
        if value != value.strip():
            raise ValueError("retrieval version value is invalid")
        return value

    @property
    def retrieval_version_id(self) -> str:
        digest = hashlib.sha256()
        components = [
            RETRIEVAL_VERSION_CONTRACT.encode("utf-8")
        ]
        for name, value in sorted(self.model_dump().items()):
            components.extend(
                (
                    name.encode("utf-8"),
                    json.dumps(
                        value,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode("utf-8"),
                )
            )
        for component in components:
            digest.update(struct.pack(">Q", len(component)))
            digest.update(component)
        return digest.hexdigest()


def validate_schema_top_k(value: object) -> SchemaTopK:
    if (
        type(value) is not int
        or value not in SUPPORTED_SCHEMA_TOP_KS
    ):
        raise ValueError("schema linking context is invalid")
    return cast(SchemaTopK, value)


@dataclass(frozen=True, slots=True)
class CandidateTable:
    object_id: str
    schema_name: str
    table_name: str
    relation_kind: str
    comment: str | None
    score: float
    matched_tokens: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CandidateField:
    object_id: str
    schema_name: str
    table_name: str
    column_name: str
    formatted_type: str
    nullable: bool
    comment: str | None
    score: float
    matched_tokens: tuple[str, ...]


class RerankReason(str, Enum):
    REQUIRED_BRIDGE = "required_bridge"
    FIELD_COVERAGE = "field_coverage"
    APPROVED_ALIAS = "approved_alias"
    JOIN_CONNECTIVITY = "join_connectivity"
    SHORTER_JOIN_PATH = "shorter_join_path"
    GRAIN_KEY_COVERAGE = "grain_key_coverage"
    FUSION_RANK = "fusion_rank"
    DISCONNECTED_PENALTY = "disconnected_penalty"
    CANONICAL_TIE_BREAK = "canonical_tie_break"


@dataclass(frozen=True, slots=True)
class RerankEvidence:
    object_id: str = field(repr=False)
    fusion_rank: int
    rerank_rank: int
    fusion_score: float
    direct_field_count: int
    approved_alias_count: int
    required_bridge: bool
    join_connected: bool
    relevant_path_edges: int | None
    has_direct_evidence: bool
    reason_codes: tuple[RerankReason, ...]
    grain_key_coverage: bool = False

    def __post_init__(self) -> None:
        ordered_reasons = tuple(
            reason
            for reason in RerankReason
            if reason in self.reason_codes
        )
        if (
            not self.object_id
            or self.object_id != self.object_id.strip()
            or type(self.fusion_rank) is not int
            or self.fusion_rank < 1
            or type(self.rerank_rank) is not int
            or self.rerank_rank < 1
            or type(self.fusion_score) not in (int, float)
            or not math.isfinite(float(self.fusion_score))
            or self.fusion_score < 0
            or type(self.direct_field_count) is not int
            or self.direct_field_count < 0
            or type(self.approved_alias_count) is not int
            or self.approved_alias_count < 0
            or type(self.required_bridge) is not bool
            or type(self.join_connected) is not bool
            or type(self.has_direct_evidence) is not bool
            or type(self.grain_key_coverage) is not bool
            or (
                self.relevant_path_edges is not None
                and (
                    type(self.relevant_path_edges) is not int
                    or self.relevant_path_edges < 1
                )
            )
            or (
                self.join_connected
                != (self.relevant_path_edges is not None)
            )
            or any(
                not isinstance(reason, RerankReason)
                for reason in self.reason_codes
            )
            or len(set(self.reason_codes)) != len(self.reason_codes)
            or self.reason_codes != ordered_reasons
        ):
            raise ValueError("rerank evidence is invalid")


@dataclass(frozen=True, slots=True)
class JoinEdge:
    constraint_name: str
    source_table: str
    source_columns: tuple[str, ...]
    target_table: str
    target_columns: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class JoinPath:
    tables: tuple[str, ...]
    edges: tuple[JoinEdge, ...]


@dataclass(frozen=True, slots=True)
class SchemaLinkingResult:
    candidate_tables: tuple[CandidateTable, ...]
    candidate_fields: tuple[CandidateField, ...]
    join_paths: tuple[JoinPath, ...]
    schema_version: str
    top_k: SchemaTopK
    retrieval_version_id: str | None = None
    retrieval_pool: SchemaRetrievalPool | None = None

    def __post_init__(self) -> None:
        validate_schema_top_k(self.top_k)
        if (
            (self.retrieval_version_id is None)
            != (self.retrieval_pool is None)
            or (
                self.retrieval_pool is not None
                and self.retrieval_pool.retrieval_version_id
                != self.retrieval_version_id
            )
        ):
            raise ValueError("schema linking result is invalid")
