from __future__ import annotations

import json
import os
import re
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from app.workflow import FinalStatus
from evaluation.code_freeze import (
    evaluation_baseline_id as compute_evaluation_baseline_id,
)
from evaluation.models import (
    AuditStatus,
    CaseEvaluation,
    ExpectedBehavior,
)
from evaluation.runner import (
    case_evidence_sha256,
    review_evidence_sha256,
)

BASELINE_VERSION = "stage10-freeze-v3"
REPORT_VERSION = "stage10-report-v3"


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
