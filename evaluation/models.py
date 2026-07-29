from __future__ import annotations

from decimal import Decimal
from enum import Enum
from typing import Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from app.connectors.errors import ErrorType
from app.workflow import FinalStatus

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
