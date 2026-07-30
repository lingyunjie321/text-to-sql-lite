from __future__ import annotations

import math
import re
from decimal import Decimal
from enum import Enum
from typing import Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from app.connectors.errors import ErrorType
from app.workflow import FinalStatus, QueryComplexity

type JsonValue = (
    None
    | bool
    | int
    | float
    | str
    | list[JsonValue]
    | dict[str, JsonValue]
)


class CaseStatus(str, Enum):
    DRAFT = "draft"
    VERIFIED = "verified"


class CaseCategory(str, Enum):
    SINGLE_TABLE = "single_table"
    MULTI_JOIN = "multi_join"
    AGGREGATION = "aggregation"
    TIME = "time"
    ANTI_JOIN = "anti_join"
    PERMISSION = "permission"
    DANGEROUS_SQL = "dangerous_sql"
    REFLECTION = "reflection"


class ExpectedBehavior(str, Enum):
    EXECUTE = "EXECUTE"
    CLARIFY = "CLARIFY"
    REJECT = "REJECT"
    FAIL_INFRA = "FAIL_INFRA"


class GoldResultSource(str, Enum):
    EXECUTE_GOLD_SQL = "execute_gold_sql"
    NOT_APPLICABLE = "not_applicable"


class ComparisonMode(str, Enum):
    EXACT = "exact"
    MULTISET = "multiset"
    KEYED = "keyed"
    NONE = "none"


class Difficulty(str, Enum):
    SIMPLE = "simple"
    MEDIUM = "medium"
    COMPLEX = "complex"


class RetrievalRoutingSuiteRole(str, Enum):
    DEVELOPMENT = "development"
    CALIBRATION = "calibration"


_RETRIEVAL_ROUTE_CONTRACT = {
    RetrievalRoutingSuiteRole.DEVELOPMENT: (
        "RRDEV-",
        "synthetic/rrdev",
    ),
    RetrievalRoutingSuiteRole.CALIBRATION: (
        "RRCAL-",
        "synthetic/rrcal",
    ),
}
_EXPECTED_TOP_K = {
    Difficulty.SIMPLE: 5,
    Difficulty.MEDIUM: 10,
    Difficulty.COMPLEX: 20,
}
_OBJECT_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")


class RetrievalRoutingCase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: str = Field(
        pattern=(
            r"^RR(?:DEV|CAL)-"
            r"(?:00[1-9]|0[1-9]\d|[1-9]\d{2})$"
        )
    )
    suite_role: RetrievalRoutingSuiteRole
    namespace: str
    question: str = Field(min_length=1)
    allowed_tables: tuple[str, ...]
    expected_tables: tuple[str, ...]
    expected_fields: tuple[str, ...]
    expected_join_edges: tuple[str, ...] = ()
    expected_complexity: Difficulty
    expected_top_k: Literal[5, 10, 20]

    @field_validator("namespace", "question", mode="before")
    @classmethod
    def strip_retrieval_string(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator(
        "allowed_tables",
        "expected_tables",
        "expected_fields",
        "expected_join_edges",
    )
    @classmethod
    def validate_retrieval_string_tuple(
        cls,
        value: tuple[str, ...],
    ) -> tuple[str, ...]:
        if (
            any(not item.strip() or item != item.strip() for item in value)
            or len(value) != len(set(value))
        ):
            raise ValueError("retrieval routing string list is invalid")
        return value

    @model_validator(mode="after")
    def validate_retrieval_routing_contract(self) -> Self:
        expected_prefix, expected_namespace = (
            _RETRIEVAL_ROUTE_CONTRACT[self.suite_role]
        )
        if (
            not self.case_id.startswith(expected_prefix)
            or self.namespace != expected_namespace
            or not self.allowed_tables
            or not self.expected_tables
            or not self.expected_fields
            or not set(self.expected_tables).issubset(self.allowed_tables)
            or self.expected_top_k
            != _EXPECTED_TOP_K[self.expected_complexity]
        ):
            raise ValueError("retrieval routing case scope is invalid")

        table_prefix = f"{self.namespace}."
        for table_id in self.allowed_tables:
            local_name = table_id.removeprefix(table_prefix)
            if (
                not table_id.startswith(table_prefix)
                or not _OBJECT_NAME_PATTERN.fullmatch(local_name)
            ):
                raise ValueError("retrieval routing table is invalid")

        expected_fields = set(self.expected_fields)
        for field_id in self.expected_fields:
            owner, separator, local_name = field_id.rpartition(".")
            if (
                not separator
                or owner not in self.expected_tables
                or not _OBJECT_NAME_PATTERN.fullmatch(local_name)
            ):
                raise ValueError("retrieval routing field is invalid")

        for edge in self.expected_join_edges:
            if edge.count("=") != 1:
                raise ValueError("retrieval routing join edge is invalid")
            left, right = edge.split("=")
            if (
                left not in expected_fields
                or right not in expected_fields
                or left == right
            ):
                raise ValueError("retrieval routing join edge is invalid")
        return self


class NumericTolerance(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    absolute: Decimal = Field(default=Decimal("0"), ge=0)
    relative: Decimal = Field(default=Decimal("0"), ge=0)


class ComparisonResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    passed: bool
    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    predicted_row_count: int = Field(ge=0)
    gold_row_count: int = Field(ge=0)


class EvaluationCase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: str = Field(pattern=r"^PG-MVP-\d{3}$")
    status: CaseStatus
    category: CaseCategory
    question: str = Field(min_length=1)
    datasource_id: str = "pagila"
    dialect: str = "postgres"
    allowed_tables: tuple[str, ...] = ()

    expected_behavior: ExpectedBehavior
    expected_final_status: FinalStatus
    expected_error_type: ErrorType | None = None

    gold_tables: tuple[str, ...] = ()
    gold_fields: tuple[str, ...] = ()
    gold_join_edges: tuple[str, ...] = ()
    gold_sql: str = ""
    gold_result_source: GoldResultSource

    comparison_mode: ComparisonMode
    order_sensitive: bool = False
    numeric_tolerances: dict[str, NumericTolerance] = Field(
        default_factory=dict
    )

    tags: tuple[str, ...] = ()
    difficulty: Difficulty
    fixture: dict[str, JsonValue] = Field(default_factory=dict)

    @field_validator(
        "question",
        "datasource_id",
        "dialect",
        "gold_sql",
        mode="before",
    )
    @classmethod
    def strip_string(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator(
        "allowed_tables",
        "gold_tables",
        "gold_fields",
        "gold_join_edges",
        "tags",
    )
    @classmethod
    def validate_string_tuple(
        cls,
        value: tuple[str, ...],
    ) -> tuple[str, ...]:
        if (
            any(not item.strip() or item != item.strip() for item in value)
            or len(value) != len(set(value))
        ):
            raise ValueError("evaluation case string list is invalid")
        return value

    @model_validator(mode="after")
    def validate_case_contract(self) -> Self:
        if (
            self.datasource_id != "pagila"
            or self.dialect != "postgres"
            or not self.allowed_tables
        ):
            raise ValueError("evaluation case scope is invalid")

        if self.expected_behavior is ExpectedBehavior.EXECUTE:
            valid = (
                bool(self.gold_tables)
                and bool(self.gold_fields)
                and bool(self.gold_sql)
                and self.gold_result_source
                is GoldResultSource.EXECUTE_GOLD_SQL
                and self.comparison_mode is not ComparisonMode.NONE
                and self.expected_error_type is None
                and self.expected_final_status
                in {
                    FinalStatus.SUCCEEDED_FIRST_PASS,
                    FinalStatus.SUCCEEDED_REPAIRED,
                }
            )
        elif self.expected_behavior is ExpectedBehavior.REJECT:
            valid = (
                not self.gold_sql
                and self.gold_result_source
                is GoldResultSource.NOT_APPLICABLE
                and self.comparison_mode is ComparisonMode.NONE
                and self.expected_error_type is not None
                and self.expected_final_status
                is FinalStatus.REJECTED_SECURITY
                and "excluded_from_executable_rate" in self.tags
            )
        elif self.expected_behavior is ExpectedBehavior.CLARIFY:
            valid = (
                not self.gold_sql
                and self.gold_result_source
                is GoldResultSource.NOT_APPLICABLE
                and self.comparison_mode is ComparisonMode.NONE
                and self.expected_final_status
                is FinalStatus.CLARIFICATION_REQUIRED
            )
        else:
            valid = (
                not self.gold_sql
                and self.gold_result_source
                is GoldResultSource.NOT_APPLICABLE
                and self.comparison_mode is ComparisonMode.NONE
                and self.expected_error_type is not None
                and self.expected_final_status
                in {
                    FinalStatus.FAILED_CONNECTION,
                    FinalStatus.FAILED_TIMEOUT,
                    FinalStatus.FAILED_RESOURCE_RISK,
                    FinalStatus.FAILED_INTERNAL,
                }
            )
        if not valid:
            raise ValueError("evaluation case behavior is invalid")
        return self


class AuditStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class CaseEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: str = Field(pattern=r"^PG-MVP-\d{3}$")
    evaluation_baseline_id: str = Field(
        pattern=r"^[0-9a-f]{64}$"
    )
    initial_status: CaseStatus
    expected_behavior: ExpectedBehavior
    expected_final_status: FinalStatus
    actual_final_status: FinalStatus | None = None
    expected_error_type: ErrorType | None = None
    actual_error_type: ErrorType | None = None
    gold_validation_passed: bool = False
    gold_executed: bool = False
    prediction_validation_passed: bool = False
    prediction_execute_count: int = Field(default=0, ge=0)
    comparison: ComparisonResult | None = None
    table_recall_passed: bool = False
    field_recall_passed: bool = False
    join_recall_passed: bool = False
    attempt_count: int = Field(default=0, ge=0, le=4)
    repair_count: int = Field(default=0, ge=0, le=3)
    trace_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    workflow_duration_ms: float = Field(default=0, ge=0)
    database_duration_ms: float = Field(default=0, ge=0)
    passed: bool
    code: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_evidence_outcome(self) -> Self:
        invalid = (
            self.passed != (self.code == "EVALUATION_PASS")
        )
        if not self.passed:
            if invalid:
                raise ValueError("case evidence outcome is invalid")
            return self

        common_pass = (
            self.initial_status is CaseStatus.DRAFT
            and self.actual_final_status is self.expected_final_status
            and self.actual_error_type is self.expected_error_type
            and self.trace_sha256 is not None
        )
        execute_pass = (
            self.gold_validation_passed
            and self.gold_executed
            and self.prediction_validation_passed
            and self.prediction_execute_count > 0
            and self.comparison is not None
            and self.comparison.passed
            and self.table_recall_passed
            and self.field_recall_passed
            and self.attempt_count > 0
            and (
                (
                    self.actual_final_status
                    is FinalStatus.SUCCEEDED_FIRST_PASS
                    and self.repair_count == 0
                )
                or (
                    self.actual_final_status
                    is FinalStatus.SUCCEEDED_REPAIRED
                    and self.repair_count >= 1
                    and self.attempt_count >= 2
                )
            )
        )
        reject_or_clarify_pass = (
            not self.gold_validation_passed
            and not self.gold_executed
            and self.comparison is None
            and self.prediction_execute_count == 0
            and (
                self.expected_behavior is not ExpectedBehavior.REJECT
                or self.repair_count == 0
            )
        )
        behavior_pass = (
            execute_pass
            if self.expected_behavior is ExpectedBehavior.EXECUTE
            else (
                reject_or_clarify_pass
                if self.expected_behavior
                in {
                    ExpectedBehavior.REJECT,
                    ExpectedBehavior.CLARIFY,
                }
                else (
                    not self.gold_validation_passed
                    and not self.gold_executed
                    and self.comparison is None
                )
            )
        )
        if invalid or not common_pass or not behavior_pass:
            raise ValueError("case evidence outcome is invalid")
        return self


class CaseEvaluation(CaseEvidence):
    evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    audit_status: AuditStatus = AuditStatus.PENDING
    review_evidence_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )

    @model_validator(mode="after")
    def validate_evaluation_outcome(self) -> Self:
        if self.audit_status is AuditStatus.APPROVED and not self.passed:
            raise ValueError("case evaluation outcome is invalid")
        return self


RetrievalObjectKind = Literal["table", "field"]
RetrievalStage = Literal[
    "bm25",
    "embedding",
    "rrf",
    "rerank",
    "final",
]
RetrievalLatencyStage = Literal[
    "bm25",
    "embedding",
    "rrf",
    "rerank",
    "retrieval_total",
    "generation",
    "wall_clock",
]

_RETRIEVAL_STAGE_ORDER: tuple[
    tuple[RetrievalObjectKind, RetrievalStage],
    ...,
] = (
    ("table", "bm25"),
    ("table", "embedding"),
    ("table", "rrf"),
    ("table", "rerank"),
    ("table", "final"),
    ("field", "bm25"),
    ("field", "embedding"),
    ("field", "rrf"),
    ("field", "final"),
)
_RETRIEVAL_LATENCY_ORDER: tuple[
    RetrievalLatencyStage,
    ...,
] = (
    "bm25",
    "embedding",
    "rrf",
    "rerank",
    "retrieval_total",
    "generation",
    "wall_clock",
)


class RetrievalStageEvidence(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
    )

    object_kind: RetrievalObjectKind
    stage: RetrievalStage
    expected_count: int = Field(ge=1)
    candidate_count_at_5: int = Field(ge=0, le=5)
    candidate_count_at_10: int = Field(ge=0, le=10)
    candidate_count_at_20: int = Field(ge=0, le=20)
    hit_count_at_5: int = Field(ge=0)
    hit_count_at_10: int = Field(ge=0)
    hit_count_at_20: int = Field(ge=0)

    @field_validator(
        "expected_count",
        "candidate_count_at_5",
        "candidate_count_at_10",
        "candidate_count_at_20",
        "hit_count_at_5",
        "hit_count_at_10",
        "hit_count_at_20",
        mode="before",
    )
    @classmethod
    def reject_coerced_count(cls, value: object) -> int:
        if type(value) is not int:
            raise ValueError(
                "retrieval stage evidence is invalid"
            )
        return value

    @model_validator(mode="after")
    def validate_counts(self) -> Self:
        candidates = (
            self.candidate_count_at_5,
            self.candidate_count_at_10,
            self.candidate_count_at_20,
        )
        hits = (
            self.hit_count_at_5,
            self.hit_count_at_10,
            self.hit_count_at_20,
        )
        if (
            self.object_kind == "field"
            and self.stage == "rerank"
        ) or candidates != tuple(sorted(candidates)) or hits != tuple(
            sorted(hits)
        ) or any(
            hit > candidate or hit > self.expected_count
            for hit, candidate in zip(
                hits,
                candidates,
                strict=True,
            )
        ):
            raise ValueError(
                "retrieval stage evidence is invalid"
            )
        return self


class RetrievalLatencyEvidence(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
    )

    stage: RetrievalLatencyStage
    duration_ms: float = Field(ge=0)

    @field_validator("duration_ms", mode="before")
    @classmethod
    def validate_duration(cls, value: object) -> float:
        if (
            type(value) not in (int, float)
            or not math.isfinite(float(value))
            or value < 0
        ):
            raise ValueError(
                "retrieval latency evidence is invalid"
            )
        return float(value)


class RetrievalRoutingCaseEvidence(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
    )

    case_id: str = Field(
        pattern=r"^RR(?:DEV|CAL)-\d{3}$"
    )
    suite_role: RetrievalRoutingSuiteRole
    dataset_file_sha256: str = Field(
        pattern=r"^[0-9a-f]{64}$"
    )
    dataset_normalized_sha256: str = Field(
        pattern=r"^[0-9a-f]{64}$"
    )
    stage1_config_sha256: str = Field(
        pattern=r"^[0-9a-f]{64}$"
    )
    controlled_code_sha256: str = Field(
        pattern=r"^[0-9a-f]{64}$"
    )
    stage1_calibration_baseline_id: str = Field(
        pattern=r"^[0-9a-f]{64}$"
    )
    trace_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    query_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    authorization_scope_sha256: str = Field(
        pattern=r"^[0-9a-f]{64}$"
    )
    schema_version: str = Field(pattern=r"^[0-9a-f]{64}$")
    retrieval_version_id: str = Field(
        pattern=r"^[0-9a-f]{64}$"
    )
    expected_complexity: Difficulty
    observed_complexity: QueryComplexity
    route_id: Literal[
        "simple_route",
        "standard_route",
        "complex_route",
    ]
    stage_evidence: tuple[RetrievalStageEvidence, ...]
    probe_table_count: int = Field(ge=0)
    final_table_count: int = Field(ge=0, le=20)
    probe_field_count: int = Field(ge=0)
    final_field_count: int = Field(ge=0)
    embedding_degraded: bool
    rerank_degraded: bool
    expected_fields_selected: bool
    join_recall_passed: bool
    candidate_field_count: int = Field(ge=0)
    pruned_field_count: int = Field(ge=0)
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    latency_evidence: tuple[RetrievalLatencyEvidence, ...]
    unauthorized_hit_count: Literal[0]

    @field_validator(
        "probe_table_count",
        "final_table_count",
        "probe_field_count",
        "final_field_count",
        "candidate_field_count",
        "pruned_field_count",
        "input_tokens",
        "output_tokens",
        "unauthorized_hit_count",
        mode="before",
    )
    @classmethod
    def reject_coerced_case_count(cls, value: object) -> int:
        if type(value) is not int:
            raise ValueError(
                "retrieval routing case evidence is invalid"
            )
        return value

    @model_validator(mode="after")
    def validate_case_evidence(self) -> Self:
        route_by_complexity = {
            QueryComplexity.SIMPLE: "simple_route",
            QueryComplexity.MEDIUM: "standard_route",
            QueryComplexity.COMPLEX: "complex_route",
        }
        expected_prefix = (
            "RRDEV-"
            if self.suite_role
            is RetrievalRoutingSuiteRole.DEVELOPMENT
            else "RRCAL-"
        )
        pairs = tuple(
            (item.object_kind, item.stage)
            for item in self.stage_evidence
        )
        table_expected_counts = {
            item.expected_count
            for item in self.stage_evidence
            if item.object_kind == "table"
        }
        field_expected_counts = {
            item.expected_count
            for item in self.stage_evidence
            if item.object_kind == "field"
        }
        final_table_stage = next(
            (
                item
                for item in self.stage_evidence
                if item.object_kind == "table"
                and item.stage == "final"
            ),
            None,
        )
        final_field_stage = next(
            (
                item
                for item in self.stage_evidence
                if item.object_kind == "field"
                and item.stage == "final"
            ),
            None,
        )
        if (
            not self.case_id.startswith(expected_prefix)
            or pairs != _RETRIEVAL_STAGE_ORDER
            or tuple(
                item.stage for item in self.latency_evidence
            )
            != _RETRIEVAL_LATENCY_ORDER
            or len(table_expected_counts) != 1
            or len(field_expected_counts) != 1
            or self.final_table_count > self.probe_table_count
            or self.final_field_count > self.probe_field_count
            or self.candidate_field_count
            != self.final_field_count
            or self.pruned_field_count
            > self.candidate_field_count
            or final_table_stage is None
            or final_field_stage is None
            or (
                final_table_stage.candidate_count_at_5,
                final_table_stage.candidate_count_at_10,
                final_table_stage.candidate_count_at_20,
            )
            != tuple(
                min(self.final_table_count, k)
                for k in (5, 10, 20)
            )
            or (
                final_field_stage.candidate_count_at_5,
                final_field_stage.candidate_count_at_10,
                final_field_stage.candidate_count_at_20,
            )
            != tuple(
                min(self.final_field_count, k)
                for k in (5, 10, 20)
            )
            or self.route_id
            != route_by_complexity[self.observed_complexity]
            or type(self.embedding_degraded) is not bool
            or type(self.rerank_degraded) is not bool
            or type(self.expected_fields_selected) is not bool
            or type(self.join_recall_passed) is not bool
        ):
            raise ValueError(
                "retrieval routing case evidence is invalid"
            )
        return self
