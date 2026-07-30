from __future__ import annotations

import math
from typing import Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from app.connectors.errors import ErrorType
from app.reflection import RepairStrategy
from app.schema_linking import RerankReason
from app.workflow import (
    ComplexityDecision,
    ComplexityReason,
    ContextSelectionObservation,
    FinalStatus,
    ModelRoutingObservation,
    QueryComplexity,
)


class TraceNode(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    node: str = Field(min_length=1)
    duration_ms: float = Field(ge=0)
    attempt_number: int | None = Field(default=None, ge=0)
    route: str | None = Field(default=None, min_length=1)


class TraceAttempt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    attempt_number: int = Field(ge=0, le=3)
    fingerprint: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    validation_passed: bool | None = None
    execution_succeeded: bool = False
    error_type: ErrorType | None = None
    database_duration_ms: float | None = Field(default=None, ge=0)


class TraceGeneration(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    call_number: int = Field(ge=1, le=4)
    attempt_number: int = Field(ge=0, le=3)
    model_config_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    provider_contract_version: str = Field(min_length=1)
    effective_contract_version: str = Field(min_length=1)
    repair_strategy: RepairStrategy | None = None
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)


class TraceContextSelection(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
    )

    call_number: int = Field(ge=1)
    attempt_number: int = Field(ge=0, le=3)
    estimator_version: Literal["utf8-bytes-div-3-v1"]
    candidate_field_count: int = Field(ge=0)
    required_field_count: int = Field(ge=0)
    selected_field_count: int = Field(ge=0)
    pruned_field_count: int = Field(ge=0)
    estimated_tokens: int = Field(ge=0)
    usable_input_tokens: int
    outcome: Literal["selected", "required_overflow"]

    @model_validator(mode="after")
    def validate_selection(self) -> Self:
        try:
            ContextSelectionObservation.model_validate(
                self.model_dump()
            )
        except ValueError as error:
            raise ValueError(
                "trace context selection is invalid"
            ) from error
        return self


class TraceModelRouting(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
    )

    call_number: int = Field(ge=1)
    attempt_number: int = Field(ge=0, le=3)
    route_id: Literal[
        "simple_route",
        "standard_route",
        "complex_route",
    ]
    route_table_version: Literal["model-routes-v1"]
    primary_model_config_hash: str = Field(
        pattern=r"^[0-9a-f]{64}$"
    )
    model_config_hash: str = Field(
        pattern=r"^[0-9a-f]{64}$"
    )
    data_boundary_hash: str = Field(
        pattern=r"^[0-9a-f]{64}$"
    )
    provider_call_count: int = Field(ge=0, le=2)
    fallback_used: bool
    outcome: Literal[
        "succeeded",
        "failed",
        "context_rejected",
    ]
    error_code: str | None = None
    primary_error_code: str | None = None
    failure_stage: Literal[
        "provider",
        "normalization",
    ] | None = None

    @model_validator(mode="after")
    def validate_routing(self) -> Self:
        try:
            ModelRoutingObservation(
                call_number=self.call_number,
                attempt_number=self.attempt_number,
                route_id=self.route_id,
                route_table_version=(
                    self.route_table_version
                ),
                primary_model_config_sha256=(
                    self.primary_model_config_hash
                ),
                model_config_sha256=(
                    self.model_config_hash
                ),
                data_boundary_sha256=(
                    self.data_boundary_hash
                ),
                provider_call_count=(
                    self.provider_call_count
                ),
                fallback_used=self.fallback_used,
                outcome=self.outcome,
                error_code=self.error_code,
                primary_error_code=self.primary_error_code,
                failure_stage=self.failure_stage,
            )
        except ValueError as error:
            raise ValueError(
                "trace model routing is invalid"
            ) from error
        return self


class TraceComplexity(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
    )

    level: QueryComplexity
    schema_top_k: Literal[5, 10, 20]
    reason_codes: tuple[ComplexityReason, ...]
    policy_version: Literal["complexity-v1"]

    @field_validator("schema_top_k", mode="before")
    @classmethod
    def validate_schema_top_k(cls, value: object) -> int:
        if type(value) is not int:
            raise ValueError("trace complexity is invalid")
        return value

    @model_validator(mode="after")
    def validate_mapping(self) -> Self:
        try:
            ComplexityDecision(
                level=self.level,
                schema_top_k=self.schema_top_k,
                reason_codes=self.reason_codes,
                policy_version=self.policy_version,
            )
        except ValueError as error:
            raise ValueError("trace complexity is invalid") from error
        return self


class TraceRetrieval(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
    )

    retrieval_version_id: str = Field(
        pattern=r"^[0-9a-f]{64}$"
    )
    retrieval_version_contract: Literal[
        "retrieval-version-v1"
    ]
    bm25_version: Literal["bm25-v1"]
    embedding_provider_contract_version: Literal[
        "openai-compatible-embedding-v1"
    ]
    embedding_provider_config_hash: str = Field(
        pattern=r"^[0-9a-f]{64}$"
    )
    document_version: Literal["schema-doc-v1"]
    fusion_version: Literal["rrf-v1"]
    rrf_k: Literal[60]
    rerank_version: Literal["schema-rerank-v2"]
    outcome: Literal["succeeded", "failed"] = "succeeded"
    mode: Literal["hybrid", "bm25_only"]
    failure_code: Literal[
        "EMBEDDING_INVALID_INPUT",
        "EMBEDDING_TIMEOUT",
        "EMBEDDING_CONNECTION_ERROR",
        "EMBEDDING_HTTP_ERROR",
        "EMBEDDING_RATE_LIMITED",
        "EMBEDDING_INVALID_RESPONSE",
    ] | None = None
    embedding_degradation: Literal[
        "timeout",
        "connection",
        "rate_limited",
        "invalid_response",
    ] | None = None
    candidate_table_count: int = Field(default=0, ge=0)
    candidate_field_count: int = Field(default=0, ge=0)
    probe_table_count: int = Field(default=0, ge=0)
    probe_field_count: int = Field(default=0, ge=0)
    final_table_count: int = Field(default=0, ge=0)
    final_field_count: int = Field(default=0, ge=0)
    embedding_table_count: int = Field(default=0, ge=0)
    embedding_field_count: int = Field(default=0, ge=0)
    fusion_table_count: int = Field(default=0, ge=0)
    fusion_field_count: int = Field(default=0, ge=0)
    rerank_changed_count: int = Field(default=0, ge=0)
    rerank_reason_codes: tuple[RerankReason, ...] = ()
    rerank_degraded: bool = False
    bm25_duration_ms: float = Field(default=0.0, ge=0)
    embedding_duration_ms: float = Field(default=0.0, ge=0)
    rrf_duration_ms: float = Field(default=0.0, ge=0)
    rerank_duration_ms: float = Field(default=0.0, ge=0)

    @field_validator(
        "bm25_duration_ms",
        "embedding_duration_ms",
        "rrf_duration_ms",
        "rerank_duration_ms",
        mode="before",
    )
    @classmethod
    def validate_stage_duration_ms(cls, value: object) -> float:
        if (
            type(value) not in (int, float)
            or not math.isfinite(float(value))
            or value < 0
        ):
            raise ValueError("trace retrieval is invalid")
        return float(value)

    @field_validator(
        "candidate_table_count",
        "candidate_field_count",
        "probe_table_count",
        "probe_field_count",
        "final_table_count",
        "final_field_count",
        "embedding_table_count",
        "embedding_field_count",
        "fusion_table_count",
        "fusion_field_count",
        "rerank_changed_count",
        mode="before",
    )
    @classmethod
    def reject_coerced_counts(cls, value: object) -> int:
        if type(value) is not int:
            raise ValueError("trace retrieval is invalid")
        return value

    @field_validator("rerank_reason_codes", mode="before")
    @classmethod
    def validate_reason_input(
        cls,
        value: object,
    ) -> tuple[RerankReason, ...]:
        if (
            type(value) is not tuple
            or any(
                not isinstance(reason, RerankReason)
                for reason in value
            )
        ):
            raise ValueError("trace retrieval is invalid")
        return value

    @model_validator(mode="after")
    def validate_retrieval(self) -> Self:
        ordered_reasons = tuple(
            reason
            for reason in RerankReason
            if reason in self.rerank_reason_codes
        )
        if (
            (
                self.outcome == "succeeded"
                and (
                    self.failure_code is not None
                    or (
                        self.mode == "hybrid"
                        and self.embedding_degradation is not None
                    )
                    or (
                        self.mode == "bm25_only"
                        and self.embedding_degradation is None
                    )
                )
            )
            or (
                self.outcome == "failed"
                and (
                    self.mode != "hybrid"
                    or self.failure_code is None
                    or self.embedding_degradation is not None
                    or self.candidate_table_count != 0
                    or self.candidate_field_count != 0
                    or self.probe_table_count != 0
                    or self.probe_field_count != 0
                    or self.final_table_count != 0
                    or self.final_field_count != 0
                    or self.embedding_table_count != 0
                    or self.embedding_field_count != 0
                    or self.fusion_table_count != 0
                    or self.fusion_field_count != 0
                    or self.rerank_changed_count != 0
                    or self.rerank_reason_codes
                    or self.rerank_degraded
                    or self.rrf_duration_ms != 0
                    or self.rerank_duration_ms != 0
                )
            )
            or self.embedding_table_count
            > self.candidate_table_count
            or self.probe_table_count > self.candidate_table_count
            or self.probe_field_count > self.candidate_field_count
            or self.final_table_count > self.probe_table_count
            or self.final_field_count > self.probe_field_count
            or self.fusion_table_count
            > self.candidate_table_count
            or self.rerank_changed_count
            > self.candidate_table_count
            or self.embedding_field_count
            > self.candidate_field_count
            or self.fusion_field_count
            > self.candidate_field_count
            or len(set(self.rerank_reason_codes))
            != len(self.rerank_reason_codes)
            or self.rerank_reason_codes != ordered_reasons
        ):
            raise ValueError("trace retrieval is invalid")
        return self


class TraceRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    request_id: str = Field(min_length=1)
    trace_id: str = Field(min_length=1)
    final_status: FinalStatus
    error_type: ErrorType | None = None
    error_code: str | None = Field(default=None, min_length=1)
    schema_version: str | None = Field(default=None, min_length=1)
    complexity: TraceComplexity | None = None
    retrieval: TraceRetrieval | None = None
    repair_count: int = Field(ge=0, le=3)
    infrastructure_retry_count: int = Field(ge=0)
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    database_duration_ms: float | None = Field(default=None, ge=0)
    returned_row_count: int = Field(ge=0, le=1000)
    truncated: bool = False
    nodes: tuple[TraceNode, ...] = ()
    attempts: tuple[TraceAttempt, ...] = ()
    generations: tuple[TraceGeneration, ...] = ()
    context_selections: tuple[
        TraceContextSelection,
        ...,
    ] = ()
    model_routes: tuple[TraceModelRouting, ...] = ()
