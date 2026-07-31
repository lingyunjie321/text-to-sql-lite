from __future__ import annotations

import json
import math
import os
import re
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from app.workflow import FinalStatus, QueryComplexity
from evaluation.code_freeze import (
    Stage1CalibrationFreeze,
    evaluation_baseline_id as compute_evaluation_baseline_id,
)
from evaluation.loader import LoadedRetrievalRoutingSuite
from evaluation.models import (
    AuditStatus,
    CaseEvaluation,
    ExpectedBehavior,
    RetrievalLatencyStage,
    RetrievalObjectKind,
    RetrievalRoutingCaseEvidence,
    RetrievalRoutingSuiteRole,
    RetrievalStage,
)
from evaluation.runner import (
    case_evidence_sha256,
    review_evidence_sha256,
)

BASELINE_VERSION = "stage1-freeze-v1"
REPORT_VERSION = "stage1-report-v1"

_STAGE1_OBJECT_STAGES: tuple[
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
_STAGE1_LATENCY_STAGES: tuple[
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
_STAGE1_KS = (5, 10, 20)


class PagilaBaseline(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source: str = Field(min_length=1)
    tag: str = Field(min_length=1)
    commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    archive_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    schema_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    data_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class PostgreSQLBaseline(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    image: str = Field(min_length=1)
    server_version: str = Field(min_length=1)


class RuntimeSnapshotBaseline(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    checksum_algorithm: str = Field(min_length=1)
    database_dump_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    database_schema_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    film_row_count: int = Field(ge=0)


class GoldCasesBaseline(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    initial_file_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    status_neutral_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class SemanticBaseline(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    manifest_version: str = Field(min_length=1)
    extractor_version: str = Field(min_length=1)
    policy_version: str = Field(min_length=1)
    database_schema_sha256: str = Field(
        pattern=r"^[0-9a-f]{64}$"
    )
    base_schema_version: str = Field(pattern=r"^[0-9a-f]{64}$")
    enriched_schema_version: str = Field(
        pattern=r"^[0-9a-f]{64}$"
    )
    allowed_scope_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    view_definitions_sha256: str = Field(
        pattern=r"^[0-9a-f]{64}$"
    )
    candidate_ledger_sha256: str = Field(
        pattern=r"^[0-9a-f]{64}$"
    )
    review_file_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class SoftwareBaseline(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    controlled_code_sha256: str = Field(
        pattern=r"^[0-9a-f]{64}$"
    )
    python_implementation: str = Field(min_length=1)
    python_version: str = Field(min_length=1)
    installed_distributions: tuple[str, ...]
    prompt_version: str = Field(min_length=1)
    provider_contract_version: str = Field(min_length=1)
    comparator_version: str = Field(min_length=1)
    evidence_version: str = Field(min_length=1)
    report_version: str = Field(min_length=1)

    @field_validator("installed_distributions")
    @classmethod
    def validate_installed_distributions(
        cls,
        value: tuple[str, ...],
    ) -> tuple[str, ...]:
        if (
            not value
            or value != tuple(sorted(value))
            or len(value) != len(set(value))
            or any(
                re.fullmatch(
                    r"[a-z0-9]+(?:-[a-z0-9]+)*"
                    r"==[A-Za-z0-9][A-Za-z0-9.+!_-]*",
                    item,
                )
                is None
                for item in value
            )
        ):
            raise ValueError(
                "installed distribution fingerprint is invalid"
            )
        return value


class DatabaseExecutionBaseline(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    datasource_id: str = Field(min_length=1)
    host: str = Field(min_length=1)
    port: int = Field(ge=1, le=65535)
    dbname: str = Field(min_length=1)
    user: str = Field(min_length=1)
    min_pool_size: int = Field(ge=1)
    max_pool_size: int = Field(ge=1)
    pool_timeout_seconds: float = Field(gt=0)
    statement_timeout_seconds: int = Field(ge=1, le=30)
    max_result_rows: int = Field(ge=1, le=1000)
    connection_retry_count: int = Field(ge=0, le=3)

    @model_validator(mode="after")
    def validate_execution_settings(self) -> Self:
        if (
            self.datasource_id != "pagila"
            or self.dbname != "pagila"
            or self.user != "text_to_sql_reader"
            or self.min_pool_size > self.max_pool_size
        ):
            raise ValueError(
                "database execution baseline is invalid"
            )
        return self


class ModelConfigurationBaseline(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    config_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class EvaluationBaseline(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    baseline_version: str
    pagila: PagilaBaseline
    postgresql: PostgreSQLBaseline
    runtime_snapshot: RuntimeSnapshotBaseline
    gold_cases: GoldCasesBaseline
    semantic: SemanticBaseline
    software: SoftwareBaseline
    database_execution: DatabaseExecutionBaseline
    model_configuration: ModelConfigurationBaseline
    evaluation_baseline_id: str = Field(
        pattern=r"^[0-9a-f]{64}$"
    )

    @model_validator(mode="after")
    def validate_baseline(self) -> Self:
        payload = self.model_dump(
            mode="json",
            exclude={"evaluation_baseline_id"},
        )
        if (
            self.baseline_version != BASELINE_VERSION
            or self.software.report_version != REPORT_VERSION
            or self.semantic.database_schema_sha256
            != self.runtime_snapshot.database_schema_sha256
            or self.evaluation_baseline_id
            != compute_evaluation_baseline_id(payload)
        ):
            raise ValueError("evaluation baseline is invalid")
        return self


class EvaluationBaselineSource(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    pagila: PagilaBaseline
    postgresql: PostgreSQLBaseline
    runtime_snapshot: RuntimeSnapshotBaseline
    gold_cases: GoldCasesBaseline


class EvaluationMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    total_cases: int = Field(ge=0)
    executable_cases: int = Field(ge=0)
    security_cases: int = Field(ge=0)
    automated_passed: int = Field(ge=0)
    audit_approved: int = Field(ge=0)
    audit_rejected: int = Field(ge=0)
    verified_case_count: int = Field(ge=0)
    first_pass_passed: int = Field(ge=0)
    repaired_passed: int = Field(ge=0)
    gold_result_passed: int = Field(ge=0)
    security_passed: int = Field(ge=0)
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    workflow_duration_ms: float = Field(ge=0)
    database_duration_ms: float = Field(ge=0)


class Stage1RetrievalMetricBucket(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
    )

    complexity: QueryComplexity
    object_kind: RetrievalObjectKind
    stage: RetrievalStage
    k: Literal[5, 10, 20]
    case_count: int = Field(ge=0)
    hit_count: int = Field(ge=0)
    expected_count: int = Field(ge=0)
    candidate_count: int = Field(ge=0)
    recall: float = Field(ge=0, le=1)
    precision: float = Field(ge=0, le=1)
    mean_candidates: float = Field(ge=0)

    @model_validator(mode="after")
    def validate_bucket_formula(self) -> Self:
        expected_recall = (
            self.hit_count / self.expected_count
            if self.expected_count
            else 0.0
        )
        expected_precision = (
            self.hit_count / self.candidate_count
            if self.candidate_count
            else 0.0
        )
        expected_mean = (
            self.candidate_count / self.case_count
            if self.case_count
            else 0.0
        )
        if (
            self.hit_count > self.expected_count
            or self.hit_count > self.candidate_count
            or (
                self.case_count == 0
                and (
                    self.hit_count != 0
                    or self.expected_count != 0
                    or self.candidate_count != 0
                )
            )
            or any(
                not math.isfinite(value)
                for value in (
                    self.recall,
                    self.precision,
                    self.mean_candidates,
                )
            )
            or not math.isclose(
                self.recall,
                expected_recall,
                rel_tol=1e-12,
                abs_tol=1e-12,
            )
            or not math.isclose(
                self.precision,
                expected_precision,
                rel_tol=1e-12,
                abs_tol=1e-12,
            )
            or not math.isclose(
                self.mean_candidates,
                expected_mean,
                rel_tol=1e-12,
                abs_tol=1e-12,
            )
        ):
            raise ValueError(
                "stage1 retrieval metric bucket is invalid"
            )
        return self


class Stage1RouteDistribution(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
    )

    complexity: QueryComplexity
    count: int = Field(ge=0)


class Stage1LatencyMetric(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
    )

    stage: RetrievalLatencyStage
    sample_count: int = Field(ge=1)
    p50_ms: float = Field(ge=0)
    p95_ms: float = Field(ge=0)

    @model_validator(mode="after")
    def validate_percentiles(self) -> Self:
        if (
            not math.isfinite(self.p50_ms)
            or not math.isfinite(self.p95_ms)
            or self.p50_ms > self.p95_ms
        ):
            raise ValueError("stage1 latency metric is invalid")
        return self


class Stage1RetrievalMetrics(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
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
    case_count: int = Field(ge=1)
    retrieval_buckets: tuple[
        Stage1RetrievalMetricBucket,
        ...,
    ]
    complexity_match_count: int = Field(ge=0)
    route_distribution: tuple[
        Stage1RouteDistribution,
        ...,
    ]
    embedding_degraded_count: int = Field(ge=0)
    rerank_degraded_count: int = Field(ge=0)
    expected_field_selection_pass_count: int = Field(ge=0)
    join_recall_pass_count: int = Field(ge=0)
    probe_table_mean: float = Field(ge=0)
    final_table_mean: float = Field(ge=0)
    probe_field_mean: float = Field(ge=0)
    final_field_mean: float = Field(ge=0)
    pruned_field_count: int = Field(ge=0)
    candidate_field_count: int = Field(ge=0)
    pruning_ratio: float = Field(ge=0, le=1)
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    latencies: tuple[Stage1LatencyMetric, ...]

    @model_validator(mode="after")
    def validate_stage1_metrics(self) -> Self:
        expected_bucket_keys = tuple(
            (complexity, object_kind, stage, k)
            for complexity in QueryComplexity
            for object_kind, stage in _STAGE1_OBJECT_STAGES
            for k in _STAGE1_KS
        )
        if (
            tuple(
                (
                    bucket.complexity,
                    bucket.object_kind,
                    bucket.stage,
                    bucket.k,
                )
                for bucket in self.retrieval_buckets
            )
            != expected_bucket_keys
            or tuple(
                item.complexity
                for item in self.route_distribution
            )
            != tuple(QueryComplexity)
            or tuple(
                item.stage for item in self.latencies
            )
            != _STAGE1_LATENCY_STAGES
            or self.complexity_match_count > self.case_count
            or self.embedding_degraded_count > self.case_count
            or self.rerank_degraded_count > self.case_count
            or self.expected_field_selection_pass_count
            > self.case_count
            or self.join_recall_pass_count > self.case_count
            or self.pruned_field_count
            > self.candidate_field_count
            or sum(
                item.count for item in self.route_distribution
            )
            != self.case_count
        ):
            raise ValueError("stage1 retrieval metrics are invalid")
        return self


class Stage1RetrievalQualityGate(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
    )

    contract_version: Literal[
        "stage1-retrieval-quality-gate-v1"
    ] = "stage1-retrieval-quality-gate-v1"
    stage1_calibration_baseline_id: str = Field(
        pattern=r"^[0-9a-f]{64}$"
    )
    compared_bucket_count: int = Field(ge=1)
    non_regressed_bucket_count: int = Field(ge=1)
    improved_bucket_count: int = Field(ge=1)
    passed: Literal[True] = True

    @model_validator(mode="after")
    def validate_quality_gate(self) -> Self:
        if (
            self.non_regressed_bucket_count
            != self.compared_bucket_count
            or self.improved_bucket_count
            > self.compared_bucket_count
        ):
            raise ValueError(
                "stage1 retrieval quality gate is invalid"
            )
        return self


class EvaluationReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    report_version: str = REPORT_VERSION
    baseline: EvaluationBaseline
    evaluation_baseline_id: str = Field(
        pattern=r"^[0-9a-f]{64}$"
    )
    model_config_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    cases_file_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    status_neutral_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    verified_case_count: int = Field(ge=0)
    evaluations: tuple[CaseEvaluation, ...]
    metrics: EvaluationMetrics

    @model_validator(mode="after")
    def validate_report(self) -> Self:
        expected_metrics = _metrics(
            self.evaluations,
            verified_case_count=self.verified_case_count,
        )
        if (
            self.report_version != REPORT_VERSION
            or self.evaluation_baseline_id
            != self.baseline.evaluation_baseline_id
            or self.model_config_hash
            != self.baseline.model_configuration.config_sha256
            or any(
                item.evaluation_baseline_id
                != self.evaluation_baseline_id
                for item in self.evaluations
            )
            or len({item.case_id for item in self.evaluations})
            != len(self.evaluations)
            or self.metrics != expected_metrics
            or any(
                case_evidence_sha256(item) != item.evidence_sha256
                or (
                    item.audit_status is AuditStatus.APPROVED
                    and item.review_evidence_sha256
                    != review_evidence_sha256(item.evidence_sha256)
                )
                or (
                    item.audit_status is not AuditStatus.APPROVED
                    and item.review_evidence_sha256 is not None
                )
                for item in self.evaluations
            )
        ):
            raise ValueError("evaluation report is invalid")
        return self


def _percentile(
    values: Sequence[float],
    percentile: float,
) -> float:
    ordered = tuple(sorted(values))
    if not ordered:
        raise ValueError("stage1 retrieval evidence is invalid")
    position = (len(ordered) - 1) * percentile
    lower_index = int(position)
    upper_index = min(lower_index + 1, len(ordered) - 1)
    fraction = position - lower_index
    return (
        ordered[lower_index]
        + (ordered[upper_index] - ordered[lower_index])
        * fraction
    )


def aggregate_stage1_retrieval_metrics(
    evidence: Sequence[RetrievalRoutingCaseEvidence],
    *,
    suite: LoadedRetrievalRoutingSuite,
    freeze: Stage1CalibrationFreeze,
) -> Stage1RetrievalMetrics:
    if (
        isinstance(evidence, (str, bytes, bytearray))
        or not isinstance(evidence, Sequence)
        or not evidence
        or any(
            not isinstance(
                item,
                RetrievalRoutingCaseEvidence,
            )
            for item in evidence
        )
        or len({item.case_id for item in evidence})
        != len(evidence)
        or not isinstance(suite, LoadedRetrievalRoutingSuite)
        or not isinstance(freeze, Stage1CalibrationFreeze)
    ):
        raise ValueError("stage1 retrieval evidence is invalid")
    items = tuple(evidence)
    if suite.role.value == "development":
        expected_dataset_hashes = (
            freeze.development_file_sha256,
            freeze.development_normalized_sha256,
        )
    else:
        expected_dataset_hashes = (
            freeze.calibration_file_sha256,
            freeze.calibration_normalized_sha256,
        )
    if (
        tuple(item.case_id for item in items)
        != tuple(case.case_id for case in suite.cases)
        or (
            suite.raw_sha256,
            suite.normalized_sha256,
        )
        != expected_dataset_hashes
        or any(
            item.suite_role is not suite.role
            or item.expected_complexity.value
            != case.expected_complexity.value
            or item.dataset_file_sha256
            != suite.raw_sha256
            or item.dataset_normalized_sha256
            != suite.normalized_sha256
            or item.stage1_config_sha256
            != freeze.stage1_config_sha256
            or item.controlled_code_sha256
            != freeze.controlled_code_sha256
            or item.stage1_calibration_baseline_id
            != freeze.stage1_calibration_baseline_id
            for item, case in zip(
                items,
                suite.cases,
                strict=True,
            )
        )
    ):
        raise ValueError("stage1 retrieval evidence is invalid")
    buckets: list[Stage1RetrievalMetricBucket] = []
    for complexity in QueryComplexity:
        complexity_cases = tuple(
            item
            for item in items
            if item.expected_complexity.value
            == complexity.value
        )
        stage_by_case = {
            item.case_id: {
                (
                    stage.object_kind,
                    stage.stage,
                ): stage
                for stage in item.stage_evidence
            }
            for item in complexity_cases
        }
        for object_kind, stage in _STAGE1_OBJECT_STAGES:
            for k in _STAGE1_KS:
                selected = tuple(
                    stage_by_case[item.case_id][
                        (object_kind, stage)
                    ]
                    for item in complexity_cases
                )
                hit_count = sum(
                    getattr(item, f"hit_count_at_{k}")
                    for item in selected
                )
                expected_count = sum(
                    item.expected_count for item in selected
                )
                candidate_count = sum(
                    getattr(item, f"candidate_count_at_{k}")
                    for item in selected
                )
                case_count = len(complexity_cases)
                buckets.append(
                    Stage1RetrievalMetricBucket(
                        complexity=complexity,
                        object_kind=object_kind,
                        stage=stage,
                        k=k,
                        case_count=case_count,
                        hit_count=hit_count,
                        expected_count=expected_count,
                        candidate_count=candidate_count,
                        recall=(
                            hit_count / expected_count
                            if expected_count
                            else 0.0
                        ),
                        precision=(
                            hit_count / candidate_count
                            if candidate_count
                            else 0.0
                        ),
                        mean_candidates=(
                            candidate_count / case_count
                            if case_count
                            else 0.0
                        ),
                    )
                )

    latency_by_case = {
        item.case_id: {
            latency.stage: latency.duration_ms
            for latency in item.latency_evidence
        }
        for item in items
    }
    case_count = len(items)
    candidate_field_count = sum(
        item.candidate_field_count for item in items
    )
    pruned_field_count = sum(
        item.pruned_field_count for item in items
    )
    return Stage1RetrievalMetrics(
        suite_role=suite.role,
        dataset_file_sha256=suite.raw_sha256,
        dataset_normalized_sha256=suite.normalized_sha256,
        stage1_config_sha256=freeze.stage1_config_sha256,
        controlled_code_sha256=freeze.controlled_code_sha256,
        stage1_calibration_baseline_id=(
            freeze.stage1_calibration_baseline_id
        ),
        case_count=case_count,
        retrieval_buckets=tuple(buckets),
        complexity_match_count=sum(
            item.expected_complexity.value
            == item.observed_complexity.value
            for item in items
        ),
        route_distribution=tuple(
            Stage1RouteDistribution(
                complexity=complexity,
                count=sum(
                    item.observed_complexity is complexity
                    for item in items
                ),
            )
            for complexity in QueryComplexity
        ),
        embedding_degraded_count=sum(
            item.embedding_degraded for item in items
        ),
        rerank_degraded_count=sum(
            item.rerank_degraded for item in items
        ),
        expected_field_selection_pass_count=sum(
            item.expected_fields_selected for item in items
        ),
        join_recall_pass_count=sum(
            item.join_recall_passed for item in items
        ),
        probe_table_mean=sum(
            item.probe_table_count for item in items
        )
        / case_count,
        final_table_mean=sum(
            item.final_table_count for item in items
        )
        / case_count,
        probe_field_mean=sum(
            item.probe_field_count for item in items
        )
        / case_count,
        final_field_mean=sum(
            item.final_field_count for item in items
        )
        / case_count,
        pruned_field_count=pruned_field_count,
        candidate_field_count=candidate_field_count,
        pruning_ratio=(
            pruned_field_count / candidate_field_count
            if candidate_field_count
            else 0.0
        ),
        input_tokens=sum(item.input_tokens for item in items),
        output_tokens=sum(item.output_tokens for item in items),
        latencies=tuple(
            Stage1LatencyMetric(
                stage=stage,
                sample_count=case_count,
                p50_ms=_percentile(
                    tuple(
                        latency_by_case[item.case_id][stage]
                        for item in items
                    ),
                    0.5,
                ),
                p95_ms=_percentile(
                    tuple(
                        latency_by_case[item.case_id][stage]
                        for item in items
                    ),
                    0.95,
                ),
            )
            for stage in _STAGE1_LATENCY_STAGES
        ),
    )


def qualify_stage1_retrieval(
    metrics: Stage1RetrievalMetrics,
) -> Stage1RetrievalQualityGate:
    if (
        not isinstance(metrics, Stage1RetrievalMetrics)
        or metrics.suite_role
        is not RetrievalRoutingSuiteRole.CALIBRATION
        or metrics.complexity_match_count != metrics.case_count
        or metrics.embedding_degraded_count != 0
        or metrics.rerank_degraded_count != 0
        or metrics.expected_field_selection_pass_count
        != metrics.case_count
        or metrics.join_recall_pass_count
        != metrics.case_count
    ):
        raise ValueError(
            "stage1 retrieval quality gate failed"
        )
    by_key = {
        (
            bucket.complexity,
            bucket.object_kind,
            bucket.stage,
            bucket.k,
        ): bucket
        for bucket in metrics.retrieval_buckets
    }
    comparisons: list[tuple[float, float]] = []
    for complexity in QueryComplexity:
        for object_kind in ("table", "field"):
            for k in _STAGE1_KS:
                baseline = by_key[
                    (complexity, object_kind, "bm25", k)
                ]
                combined = by_key[
                    (complexity, object_kind, "final", k)
                ]
                if baseline.case_count:
                    comparisons.append(
                        (baseline.recall, combined.recall)
                    )
    non_regressed = sum(
        combined + 1e-12 >= baseline
        for baseline, combined in comparisons
    )
    improved = sum(
        combined > baseline + 1e-12
        for baseline, combined in comparisons
    )
    if (
        not comparisons
        or non_regressed != len(comparisons)
        or improved < 1
    ):
        raise ValueError(
            "stage1 retrieval quality gate failed"
        )
    return Stage1RetrievalQualityGate(
        stage1_calibration_baseline_id=(
            metrics.stage1_calibration_baseline_id
        ),
        compared_bucket_count=len(comparisons),
        non_regressed_bucket_count=non_regressed,
        improved_bucket_count=improved,
    )


def load_baseline(path: Path) -> EvaluationBaseline:
    try:
        return EvaluationBaseline.model_validate_json(
            path.read_text(encoding="utf-8")
        )
    except (OSError, UnicodeDecodeError, ValidationError):
        raise ValueError("evaluation baseline is invalid") from None


def load_baseline_source(path: Path) -> EvaluationBaselineSource:
    try:
        return EvaluationBaselineSource.model_validate_json(
            path.read_text(encoding="utf-8")
        )
    except (OSError, UnicodeDecodeError, ValidationError):
        raise ValueError(
            "evaluation baseline source is invalid"
        ) from None


def _metrics(
    evaluations: tuple[CaseEvaluation, ...],
    *,
    verified_case_count: int,
) -> EvaluationMetrics:
    executable = tuple(
        item
        for item in evaluations
        if item.expected_behavior is ExpectedBehavior.EXECUTE
    )
    security = tuple(
        item
        for item in evaluations
        if item.expected_behavior is ExpectedBehavior.REJECT
    )
    return EvaluationMetrics(
        total_cases=len(evaluations),
        executable_cases=len(executable),
        security_cases=len(security),
        automated_passed=sum(item.passed for item in evaluations),
        audit_approved=sum(
            item.audit_status is AuditStatus.APPROVED
            for item in evaluations
        ),
        audit_rejected=sum(
            item.audit_status is AuditStatus.REJECTED
            for item in evaluations
        ),
        verified_case_count=verified_case_count,
        first_pass_passed=sum(
            item.passed
            and item.actual_final_status
            is FinalStatus.SUCCEEDED_FIRST_PASS
            for item in executable
        ),
        repaired_passed=sum(
            item.passed
            and item.actual_final_status
            is FinalStatus.SUCCEEDED_REPAIRED
            for item in executable
        ),
        gold_result_passed=sum(
            item.passed
            and item.comparison is not None
            and item.comparison.passed
            for item in executable
        ),
        security_passed=sum(item.passed for item in security),
        input_tokens=sum(item.input_tokens for item in evaluations),
        output_tokens=sum(item.output_tokens for item in evaluations),
        workflow_duration_ms=sum(
            item.workflow_duration_ms for item in evaluations
        ),
        database_duration_ms=sum(
            item.database_duration_ms for item in evaluations
        ),
    )


def build_evaluation_report(
    evaluations: Sequence[CaseEvaluation],
    *,
    baseline: EvaluationBaseline,
    model_config_hash: str,
    cases_file_sha256: str,
    status_neutral_sha256: str,
    verified_case_count: int,
    require_full_suite: bool = True,
) -> EvaluationReport:
    try:
        baseline = EvaluationBaseline.model_validate_json(
            baseline.model_dump_json()
        )
    except ValidationError:
        raise ValueError("evaluation report is invalid") from None
    items = tuple(evaluations)
    if (
        not items
        or len({item.case_id for item in items}) != len(items)
        or (
            require_full_suite
            and tuple(item.case_id for item in items)
            != tuple(
                f"PG-MVP-{number:03d}"
                for number in range(1, 19)
            )
        )
        or (
            require_full_suite
            and status_neutral_sha256
            != baseline.gold_cases.status_neutral_sha256
        )
    ):
        raise ValueError("evaluation report is invalid")
    return EvaluationReport(
        baseline=baseline,
        evaluation_baseline_id=baseline.evaluation_baseline_id,
        model_config_hash=model_config_hash,
        cases_file_sha256=cases_file_sha256,
        status_neutral_sha256=status_neutral_sha256,
        verified_case_count=verified_case_count,
        evaluations=items,
        metrics=_metrics(
            items,
            verified_case_count=verified_case_count,
        ),
    )


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary.write(payload)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_path = Path(temporary.name)
        temporary_path.replace(path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def write_report_atomic(
    path: Path,
    report: EvaluationReport,
) -> None:
    payload = (
        report.model_dump_json(indent=2) + "\n"
    ).encode("utf-8")
    _atomic_write(path, payload)


def write_baseline_atomic(
    path: Path,
    baseline: EvaluationBaseline,
) -> None:
    payload = (
        baseline.model_dump_json(indent=2) + "\n"
    ).encode("utf-8")
    _atomic_write(path, payload)


def load_report(path: Path) -> EvaluationReport:
    try:
        return EvaluationReport.model_validate_json(
            path.read_text(encoding="utf-8")
        )
    except (OSError, UnicodeDecodeError, ValidationError):
        raise ValueError("evaluation report is invalid") from None


def require_report_baseline(
    report: EvaluationReport,
    current_baseline: EvaluationBaseline,
) -> None:
    if (
        report.evaluation_baseline_id
        != current_baseline.evaluation_baseline_id
        or report.baseline != current_baseline
    ):
        raise ValueError(
            "evaluation report does not match current baseline"
        )


def review_case(
    report_path: Path,
    *,
    current_baseline: EvaluationBaseline,
    case_id: str,
    approved: bool,
) -> None:
    report = load_report(report_path)
    require_report_baseline(report, current_baseline)
    matches = tuple(
        item
        for item in report.evaluations
        if item.case_id == case_id
    )
    if len(matches) != 1:
        raise ValueError("evaluation case review is invalid")
    target = matches[0]
    if case_evidence_sha256(target) != target.evidence_sha256:
        raise ValueError("evaluation evidence digest is invalid")
    if approved and not target.passed:
        raise ValueError("failed evidence cannot be approved")
    status = (
        AuditStatus.APPROVED
        if approved
        else AuditStatus.REJECTED
    )
    review_digest = (
        review_evidence_sha256(target.evidence_sha256)
        if approved
        else None
    )
    updated = tuple(
        (
            item.model_copy(
                update={
                    "audit_status": status,
                    "review_evidence_sha256": review_digest,
                }
            )
            if item.case_id == case_id
            else item
        )
        for item in report.evaluations
    )
    revised = build_evaluation_report(
        updated,
        baseline=current_baseline,
        model_config_hash=report.model_config_hash,
        cases_file_sha256=report.cases_file_sha256,
        status_neutral_sha256=report.status_neutral_sha256,
        verified_case_count=report.verified_case_count,
        require_full_suite=len(updated) == 18,
    )
    write_report_atomic(report_path, revised)
