from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Literal, Protocol, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from app.connectors.errors import DatabaseError, ErrorType
from app.connectors.metadata import SchemaSnapshot
from app.connectors.models import ExecutionResult
from app.generation import (
    CONTEXT_ESTIMATOR_VERSION,
    MODEL_ROUTE_TABLE_VERSION,
    ModelRoutingRuntime,
)
from app.reflection import (
    AttemptHistory,
    RepairStrategy,
    SQLAttempt,
)
from app.schema_linking import (
    CandidateField,
    CandidateTable,
    JoinPath,
    RetrievalFailureEvidence,
)
from app.schema_linking.fusion import SchemaRetrievalPool
from app.schema_linking.index import RetrievalRuntime
from app.validation import ValidationResult

MAX_WORKFLOW_STEPS = 32
REQUEST_TIMEOUT_SECONDS = 120
REPAIR_PROMPT_VERSION = "repair-v1"


class QueryComplexity(str, Enum):
    SIMPLE = "simple"
    MEDIUM = "medium"
    COMPLEX = "complex"


class ComplexityReason(str, Enum):
    AGGREGATION_REQUESTED = "aggregation_requested"
    WINDOW_OR_RANKING_REQUESTED = "window_or_ranking_requested"
    SUBQUERY_OR_ANTI_JOIN_REQUESTED = "subquery_or_anti_join_requested"
    TIME_ANALYSIS_REQUESTED = "time_analysis_requested"
    MULTIPLE_POSITIVE_TABLES = "multiple_positive_tables"
    RELEVANT_JOIN_PATH = "relevant_join_path"
    LONG_JOIN_PATH = "long_join_path"
    REPAIR_HISTORY = "repair_history"
    DEFAULT_SIMPLE = "default_simple"


_HIGH_COMPLEXITY_REASONS = frozenset(
    {
        ComplexityReason.WINDOW_OR_RANKING_REQUESTED,
        ComplexityReason.SUBQUERY_OR_ANTI_JOIN_REQUESTED,
        ComplexityReason.LONG_JOIN_PATH,
        ComplexityReason.REPAIR_HISTORY,
    }
)
_MEDIUM_COMPLEXITY_REASONS = frozenset(
    {
        ComplexityReason.AGGREGATION_REQUESTED,
        ComplexityReason.TIME_ANALYSIS_REQUESTED,
        ComplexityReason.MULTIPLE_POSITIVE_TABLES,
        ComplexityReason.RELEVANT_JOIN_PATH,
    }
)


class ComplexityDecision(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
    )

    level: QueryComplexity
    schema_top_k: Literal[5, 10, 20]
    reason_codes: tuple[ComplexityReason, ...]
    policy_version: Literal["complexity-v1"] = "complexity-v1"

    @field_validator("level", mode="before")
    @classmethod
    def validate_level(
        cls,
        value: object,
    ) -> QueryComplexity:
        if not isinstance(value, QueryComplexity):
            raise ValueError("complexity decision is invalid")
        return value

    @field_validator("schema_top_k", mode="before")
    @classmethod
    def validate_schema_top_k(cls, value: object) -> int:
        if type(value) is not int or value not in {5, 10, 20}:
            raise ValueError("complexity decision is invalid")
        return value

    @field_validator("reason_codes", mode="before")
    @classmethod
    def validate_reason_codes(
        cls,
        value: object,
    ) -> tuple[ComplexityReason, ...]:
        if (
            type(value) is not tuple
            or any(
                not isinstance(reason, ComplexityReason)
                for reason in value
            )
        ):
            raise ValueError("complexity decision is invalid")
        return value

    @field_validator("policy_version", mode="before")
    @classmethod
    def validate_policy_version(cls, value: object) -> str:
        if value != "complexity-v1":
            raise ValueError("complexity decision is invalid")
        return "complexity-v1"

    @model_validator(mode="after")
    def validate_mapping(self) -> Self:
        reasons = set(self.reason_codes)
        ordered_reasons = tuple(
            reason
            for reason in ComplexityReason
            if reason in reasons
        )
        if (
            not reasons
            or len(reasons) != len(self.reason_codes)
            or self.reason_codes != ordered_reasons
            or (
                ComplexityReason.DEFAULT_SIMPLE in reasons
                and reasons != {ComplexityReason.DEFAULT_SIMPLE}
            )
        ):
            raise ValueError("complexity decision is invalid")

        if reasons == {ComplexityReason.DEFAULT_SIMPLE}:
            expected = (QueryComplexity.SIMPLE, 5)
        elif (
            reasons & _HIGH_COMPLEXITY_REASONS
            or len(reasons & _MEDIUM_COMPLEXITY_REASONS) >= 2
        ):
            expected = (QueryComplexity.COMPLEX, 20)
        elif reasons & _MEDIUM_COMPLEXITY_REASONS:
            expected = (QueryComplexity.MEDIUM, 10)
        else:
            raise ValueError("complexity decision is invalid")

        if (self.level, self.schema_top_k) != expected:
            raise ValueError("complexity decision is invalid")
        return self


class FinalStatus(str, Enum):
    SUCCEEDED_FIRST_PASS = "SUCCEEDED_FIRST_PASS"
    SUCCEEDED_REPAIRED = "SUCCEEDED_REPAIRED"
    CLARIFICATION_REQUIRED = "CLARIFICATION_REQUIRED"
    REJECTED_SECURITY = "REJECTED_SECURITY"
    FAILED_REPAIR_EXHAUSTED = "FAILED_REPAIR_EXHAUSTED"
    FAILED_DUPLICATE_LOOP = "FAILED_DUPLICATE_LOOP"
    FAILED_TIMEOUT = "FAILED_TIMEOUT"
    FAILED_CONNECTION = "FAILED_CONNECTION"
    FAILED_RESOURCE_RISK = "FAILED_RESOURCE_RISK"
    FAILED_INTERNAL = "FAILED_INTERNAL"


class Clarification(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str = Field(min_length=1)
    question: str = Field(min_length=1)


class WorkflowPublicError(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    error_type: ErrorType
    code: str = Field(min_length=1)
    public_message: str = Field(min_length=1)


class TokenUsage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)

    def add(
        self,
        *,
        input_tokens: int,
        output_tokens: int,
    ) -> TokenUsage:
        return TokenUsage(
            input_tokens=self.input_tokens + input_tokens,
            output_tokens=self.output_tokens + output_tokens,
        )


class NodeTiming(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    node: str = Field(min_length=1)
    duration_ms: float = Field(ge=0)
    attempt_number: int | None = Field(default=None, ge=0)
    route: str | None = Field(default=None, min_length=1)


class GenerationObservation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    call_number: int = Field(ge=1)
    attempt_number: int = Field(ge=0, le=3)
    model_config_id: str = Field(min_length=1)
    provider_prompt_version: str = Field(min_length=1)
    effective_prompt_version: str = Field(min_length=1)
    repair_strategy: RepairStrategy | None = None
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)

    @field_validator(
        "model_config_id",
        "provider_prompt_version",
        "effective_prompt_version",
    )
    @classmethod
    def strip_observation_identifier(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("generation observation is invalid")
        return stripped

    @model_validator(mode="after")
    def validate_prompt_version(self) -> Self:
        expected = self.provider_prompt_version
        if self.repair_strategy is not None:
            expected = f"{expected}+{REPAIR_PROMPT_VERSION}"
        if self.effective_prompt_version != expected:
            raise ValueError("generation observation is invalid")
        return self


class ContextSelectionObservation(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
    )

    call_number: int = Field(ge=1)
    attempt_number: int = Field(ge=0, le=3)
    estimator_version: Literal[
        "utf8-bytes-div-3-v1"
    ] = CONTEXT_ESTIMATOR_VERSION
    candidate_field_count: int = Field(ge=0)
    required_field_count: int = Field(ge=0)
    selected_field_count: int = Field(ge=0)
    pruned_field_count: int = Field(ge=0)
    estimated_tokens: int = Field(ge=0)
    usable_input_tokens: int
    outcome: Literal["selected", "required_overflow"]

    @field_validator(
        "call_number",
        "attempt_number",
        "candidate_field_count",
        "required_field_count",
        "selected_field_count",
        "pruned_field_count",
        "estimated_tokens",
        "usable_input_tokens",
        mode="before",
    )
    @classmethod
    def reject_coerced_integer(cls, value: object) -> int:
        if type(value) is not int:
            raise ValueError(
                "context selection observation is invalid"
            )
        return value

    @model_validator(mode="after")
    def validate_selection(self) -> Self:
        if (
            self.required_field_count
            > self.selected_field_count
            or self.selected_field_count
            + self.pruned_field_count
            != self.candidate_field_count
            or (
                self.outcome == "selected"
                and (
                    self.estimated_tokens
                    > self.usable_input_tokens
                    or self.usable_input_tokens < 0
                )
            )
            or (
                self.outcome == "required_overflow"
                and self.estimated_tokens
                <= self.usable_input_tokens
            )
        ):
            raise ValueError(
                "context selection observation is invalid"
            )
        return self


_MODEL_ROUTING_ERROR_CODES = frozenset(
    {
        "LLM_TIMEOUT",
        "LLM_CONNECTION_ERROR",
        "LLM_RATE_LIMITED",
        "LLM_CAPACITY_ERROR",
        "LLM_HTTP_ERROR",
        "LLM_INVALID_RESPONSE",
        "LLM_INVALID_OUTPUT",
        "LLM_INTERNAL_ERROR",
        "WORKFLOW_CONTEXT_REQUIRED_OVERFLOW",
    }
)
_MODEL_ROUTING_FALLBACK_CODES = frozenset(
    {
        "LLM_TIMEOUT",
        "LLM_CONNECTION_ERROR",
        "LLM_RATE_LIMITED",
        "LLM_CAPACITY_ERROR",
    }
)


class ModelRoutingObservation(BaseModel):
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
    route_table_version: Literal[
        "model-routes-v1"
    ] = MODEL_ROUTE_TABLE_VERSION
    primary_model_config_sha256: str = Field(
        pattern=r"^[0-9a-f]{64}$"
    )
    model_config_sha256: str = Field(
        pattern=r"^[0-9a-f]{64}$"
    )
    data_boundary_sha256: str = Field(
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

    @field_validator(
        "call_number",
        "attempt_number",
        "provider_call_count",
        mode="before",
    )
    @classmethod
    def reject_coerced_integer(cls, value: object) -> int:
        if type(value) is not int:
            raise ValueError(
                "model routing observation is invalid"
            )
        return value

    @model_validator(mode="after")
    def validate_routing(self) -> Self:
        if (
            type(self.fallback_used) is not bool
            or (
                self.error_code is not None
                and self.error_code
                not in _MODEL_ROUTING_ERROR_CODES
            )
            or (
                self.outcome == "succeeded"
                and (
                    self.provider_call_count not in {1, 2}
                    or self.error_code is not None
                    or self.failure_stage is not None
                    or (
                        self.fallback_used
                        and self.primary_error_code
                        not in _MODEL_ROUTING_FALLBACK_CODES
                    )
                    or (
                        not self.fallback_used
                        and self.primary_error_code is not None
                    )
                )
            )
            or (
                self.outcome == "failed"
                and (
                    self.provider_call_count not in {0, 1, 2}
                    or self.error_code is None
                    or self.failure_stage is None
                )
            )
            or (
                self.outcome == "context_rejected"
                and (
                    self.provider_call_count != 0
                    or self.fallback_used
                    or self.error_code
                    != "WORKFLOW_CONTEXT_REQUIRED_OVERFLOW"
                    or self.primary_error_code is not None
                    or self.failure_stage is not None
                    or self.primary_model_config_sha256
                    != self.model_config_sha256
                )
            )
            or (
                self.fallback_used
                != (self.provider_call_count == 2)
            )
            or (
                self.failure_stage == "provider"
                and (
                    self.primary_error_code is None
                    or (
                        not self.fallback_used
                        and self.primary_error_code
                        != self.error_code
                    )
                    or (
                        self.fallback_used
                        and self.primary_error_code
                        not in _MODEL_ROUTING_FALLBACK_CODES
                    )
                    or (
                        self.provider_call_count == 0
                        and self.error_code != "LLM_TIMEOUT"
                    )
                )
            )
            or (
                self.failure_stage == "normalization"
                and (
                    self.provider_call_count not in {1, 2}
                    or self.error_code != "LLM_INTERNAL_ERROR"
                    or (
                        self.fallback_used
                        and self.primary_error_code
                        not in _MODEL_ROUTING_FALLBACK_CODES
                    )
                    or (
                        not self.fallback_used
                        and self.primary_error_code is not None
                    )
                )
            )
        ):
            raise ValueError(
                "model routing observation is invalid"
            )
        return self


class WorkflowConnector(Protocol):
    def read_metadata(
        self,
        allowed_schemas: tuple[str, ...],
        allowed_tables: tuple[str, ...],
        *,
        timeout_seconds: float | None = None,
    ) -> SchemaSnapshot: ...

    def execute(
        self,
        sql: str,
        *,
        timeout_seconds: float | None = None,
    ) -> ExecutionResult: ...


@dataclass(frozen=True, slots=True)
class WorkflowContext:
    connector: WorkflowConnector = field(repr=False)
    model_routing: ModelRoutingRuntime = field(repr=False)
    datasource_id: str
    allowed_schemas: tuple[str, ...]
    allowed_tables: tuple[str, ...]
    retrieval_runtime: RetrievalRuntime | None = field(
        default=None,
        repr=False,
    )
    now: datetime | None = None
    clock: Callable[[], float] = field(
        default=time.monotonic,
        repr=False,
    )

    def __post_init__(self) -> None:
        schemas = tuple(sorted(set(self.allowed_schemas)))
        tables = tuple(sorted(set(self.allowed_tables)))
        if (
            not self.datasource_id.strip()
            or not schemas
            or not tables
            or any(not schema.strip() for schema in schemas)
            or any(
                "." not in table or not table.strip()
                for table in tables
            )
            or any(
                table.split(".", 1)[0] not in schemas
                for table in tables
            )
            or (
                self.retrieval_runtime is not None
                and not isinstance(
                    self.retrieval_runtime,
                    RetrievalRuntime,
                )
            )
            or not isinstance(
                self.model_routing,
                ModelRoutingRuntime,
            )
            or not callable(self.clock)
            or (
                self.now is not None
                and self.now.tzinfo is None
            )
        ):
            raise ValueError("workflow context is invalid")
        object.__setattr__(self, "datasource_id", self.datasource_id.strip())
        object.__setattr__(self, "allowed_schemas", schemas)
        object.__setattr__(self, "allowed_tables", tables)


class SQLTaskState(BaseModel):
    model_config = ConfigDict(
        arbitrary_types_allowed=True,
        extra="forbid",
        frozen=True,
    )

    request_id: str = Field(min_length=1)
    trace_id: str = Field(min_length=1)
    question: str
    normalized_question: str | None = None
    normalized_time: str | None = None
    datasource_id: str = Field(min_length=1)
    dialect: str = "postgres"
    requested_schemas: tuple[str, ...] = ()

    allowed_schemas: tuple[str, ...] = ()
    allowed_tables: tuple[str, ...] = ()

    candidate_tables: tuple[CandidateTable, ...] = ()
    candidate_fields: tuple[CandidateField, ...] = ()
    join_paths: tuple[JoinPath, ...] = ()
    schema_version: str | None = None
    schema_snapshot: SchemaSnapshot | None = None
    retrieval_version_id: str | None = None
    schema_retrieval_pool: SchemaRetrievalPool | None = None
    retrieval_failure: RetrievalFailureEvidence | None = Field(
        default=None,
        repr=False,
    )
    probe_candidate_table_count: int | None = Field(
        default=None,
        ge=0,
    )
    probe_candidate_field_count: int | None = Field(
        default=None,
        ge=0,
    )
    complexity_decision: ComplexityDecision | None = None

    current_sql: str | None = None
    # SQLAttempt and ExecutionResult include the recursive JsonValue alias
    # from Stage 1. Keep their schema opaque here, then enforce the concrete
    # runtime types in the model invariant below.
    sql_attempts: tuple[object, ...] = ()
    seen_sql_fingerprints: frozenset[str] = frozenset()

    validation_result: ValidationResult | None = None
    execution_result: object | None = None
    database_error: DatabaseError | None = None

    error_type: ErrorType | None = None
    repair_strategy: RepairStrategy | None = None
    repair_count: int = Field(default=0, ge=0, le=3)
    infrastructure_retry_count: int = Field(default=0, ge=0)

    clarification: Clarification | None = None
    final_status: FinalStatus | None = None
    public_error: WorkflowPublicError | None = None

    token_usage: TokenUsage = Field(default_factory=TokenUsage)
    generation_observations: tuple[GenerationObservation, ...] = ()
    context_selection_observations: tuple[
        ContextSelectionObservation,
        ...,
    ] = ()
    selected_generation_field_ids: tuple[str, ...] = ()
    model_routing_observations: tuple[
        ModelRoutingObservation,
        ...,
    ] = ()
    node_timings: tuple[NodeTiming, ...] = ()
    step_count: int = Field(default=0, ge=0, le=MAX_WORKFLOW_STEPS)
    workflow_started_at: float | None = Field(default=None, ge=0)

    @field_validator(
        "requested_schemas",
        "allowed_schemas",
        "allowed_tables",
    )
    @classmethod
    def validate_string_tuple(
        cls,
        value: tuple[str, ...],
    ) -> tuple[str, ...]:
        if any(not isinstance(item, str) or not item.strip() for item in value):
            raise ValueError("workflow scope is invalid")
        return value

    @model_validator(mode="after")
    def validate_workflow_invariants(self) -> Self:
        if self.dialect != "postgres":
            raise ValueError("workflow dialect is invalid")
        if (
            (self.retrieval_version_id is None)
            != (self.schema_retrieval_pool is None)
            or (
                self.retrieval_failure is not None
                and self.schema_retrieval_pool is not None
            )
            or (
                self.probe_candidate_table_count is None
            )
            != (
                self.probe_candidate_field_count is None
            )
            or (
                self.schema_retrieval_pool is not None
                and (
                    self.retrieval_version_id
                    != self.schema_retrieval_pool.retrieval_version_id
                    or self.schema_version
                    != self.schema_retrieval_pool.schema_version
                )
            )
            or (
                self.retrieval_failure is not None
                and self.schema_version
                != (
                    self.retrieval_failure
                    .retrieval_version.schema_version
                )
            )
        ):
            raise ValueError("workflow retrieval state is invalid")
        if any(
            not isinstance(attempt, SQLAttempt)
            for attempt in self.sql_attempts
        ) or (
            self.execution_result is not None
            and not isinstance(self.execution_result, ExecutionResult)
        ):
            raise ValueError("workflow attempt state is invalid")
        if self.sql_attempts:
            try:
                history = AttemptHistory(
                    attempts=self.sql_attempts,  # type: ignore[arg-type]
                    seen_sql_fingerprints=self.seen_sql_fingerprints,
                    repair_count=self.repair_count,
                )
            except ValueError as error:
                raise ValueError(
                    "workflow attempt state is invalid"
                ) from error
            current = history.current_attempt
            if (
                self.current_sql != current.sql
                or self.validation_result
                != current.validation_result
                or self.execution_result
                != current.execution_result
                or self.database_error != current.database_error
            ):
                raise ValueError("workflow attempt state is invalid")
        elif (
            self.seen_sql_fingerprints
            or self.repair_count
            or self.current_sql is not None
            or self.validation_result is not None
            or self.execution_result is not None
            or self.database_error is not None
        ):
            raise ValueError("workflow attempt state is invalid")

        if len(self.node_timings) != self.step_count:
            raise ValueError("workflow timing state is invalid")
        expected_calls = tuple(
            range(1, len(self.generation_observations) + 1)
        )
        expected_route_calls = tuple(
            range(
                1,
                len(self.model_routing_observations) + 1,
            )
        )
        if (
            tuple(
                observation.call_number
                for observation in self.generation_observations
            )
            != expected_calls
            or self.token_usage.input_tokens
            != sum(
                observation.input_tokens
                for observation in self.generation_observations
            )
            or self.token_usage.output_tokens
            != sum(
                observation.output_tokens
                for observation in self.generation_observations
            )
            or tuple(
                observation.call_number
                for observation
                in self.context_selection_observations
            )
            != expected_route_calls
            or tuple(
                observation.call_number
                for observation
                in self.model_routing_observations
            )
            != expected_route_calls
            or len(self.context_selection_observations)
            != len(self.model_routing_observations)
            or len(set(self.selected_generation_field_ids))
            != len(self.selected_generation_field_ids)
            or not set(
                self.selected_generation_field_ids
            ).issubset(
                {
                    field.object_id
                    for field in self.candidate_fields
                }
            )
        ):
            raise ValueError(
                "workflow generation observation is invalid"
            )

        if self.final_status is None:
            return self
        success = self.final_status in {
            FinalStatus.SUCCEEDED_FIRST_PASS,
            FinalStatus.SUCCEEDED_REPAIRED,
        }
        clarification = (
            self.final_status == FinalStatus.CLARIFICATION_REQUIRED
        )
        if success:
            count_matches = (
                (
                    self.final_status
                    == FinalStatus.SUCCEEDED_FIRST_PASS
                    and self.repair_count == 0
                )
                or (
                    self.final_status
                    == FinalStatus.SUCCEEDED_REPAIRED
                    and self.repair_count > 0
                )
            )
            valid = (
                count_matches
                and self.current_sql is not None
                and self.execution_result is not None
                and self.database_error is None
                and self.error_type is None
                and self.clarification is None
                and self.public_error is None
            )
        elif clarification:
            valid = (
                self.clarification is not None
                and self.error_type
                in {
                    ErrorType.AMBIGUOUS_SEMANTICS,
                    ErrorType.BUSINESS_KNOWLEDGE_MISSING,
                }
                and self.execution_result is None
                and self.public_error is None
            )
        else:
            expected_errors = {
                FinalStatus.REJECTED_SECURITY: {
                    ErrorType.PERMISSION_DENIED,
                },
                FinalStatus.FAILED_DUPLICATE_LOOP: {
                    ErrorType.DUPLICATE_SQL,
                },
                FinalStatus.FAILED_TIMEOUT: {
                    ErrorType.TIMEOUT,
                },
                FinalStatus.FAILED_CONNECTION: {
                    ErrorType.CONNECTION_ERROR,
                },
                FinalStatus.FAILED_RESOURCE_RISK: {
                    ErrorType.RESOURCE_RISK,
                },
            }
            if (
                self.final_status
                == FinalStatus.FAILED_REPAIR_EXHAUSTED
            ):
                status_matches = (
                    self.error_type
                    in {
                        ErrorType.SYNTAX_ERROR,
                        ErrorType.SCHEMA_ERROR,
                        ErrorType.DIALECT_ERROR,
                    }
                    and self.repair_count == 3
                )
            elif self.final_status == FinalStatus.FAILED_INTERNAL:
                status_matches = (
                    self.error_type
                    not in {
                        ErrorType.PERMISSION_DENIED,
                        ErrorType.DUPLICATE_SQL,
                        ErrorType.TIMEOUT,
                        ErrorType.CONNECTION_ERROR,
                        ErrorType.RESOURCE_RISK,
                    }
                    and not (
                        self.error_type
                        in {
                            ErrorType.SYNTAX_ERROR,
                            ErrorType.SCHEMA_ERROR,
                            ErrorType.DIALECT_ERROR,
                        }
                        and self.repair_count == 3
                    )
                )
            else:
                status_matches = (
                    self.error_type
                    in expected_errors.get(self.final_status, set())
                )
            valid = (
                status_matches
                and self.public_error is not None
                and self.public_error.error_type == self.error_type
                and self.execution_result is None
                and self.clarification is None
            )
        if not valid:
            raise ValueError("workflow terminal state is invalid")
        return self


def new_task_state(
    *,
    request_id: str,
    trace_id: str,
    question: str,
    datasource_id: str,
    requested_schemas: tuple[str, ...] = (),
) -> SQLTaskState:
    return SQLTaskState(
        request_id=request_id,
        trace_id=trace_id,
        question=question,
        datasource_id=datasource_id,
        requested_schemas=requested_schemas,
    )


@dataclass(frozen=True, slots=True)
class PermissionScope:
    allowed_schemas: tuple[str, ...]
    allowed_tables: tuple[str, ...]


class WorkflowPermissionError(RuntimeError):
    def __init__(self, details: WorkflowPublicError) -> None:
        super().__init__(details.public_message)
        self.details = details
