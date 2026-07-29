import json
from pathlib import Path

from app.workflow import FinalStatus
from evaluation import (
    AuditStatus,
    CaseEvaluation,
    CaseStatus,
    ExpectedBehavior,
)
from evaluation.report import (
    build_evaluation_report,
    load_baseline,
    write_report_atomic,
)
from evaluation.runner import case_evidence_sha256


def test_report_serialization_contains_no_sensitive_payloads(
    tmp_path: Path,
) -> None:
    baseline = load_baseline(
        Path("evaluation/pagila_baseline.json")
    )
    fields: dict[str, object] = {
        "case_id": "PG-MVP-001",
        "evaluation_baseline_id": (
            baseline.evaluation_baseline_id
        ),
        "initial_status": CaseStatus.DRAFT,
        "expected_behavior": ExpectedBehavior.EXECUTE,
        "expected_final_status": FinalStatus.SUCCEEDED_FIRST_PASS,
        "actual_final_status": FinalStatus.FAILED_INTERNAL,
        "gold_validation_passed": True,
        "gold_executed": True,
        "prediction_execute_count": 0,
        "passed": False,
        "code": "EVALUATION_INTERNAL_ERROR",
    }
    evaluation = CaseEvaluation(
        **fields,
        evidence_sha256=case_evidence_sha256(fields),
        audit_status=AuditStatus.REJECTED,
    )
    report = build_evaluation_report(
        (evaluation,),
        baseline=baseline,
        model_config_hash=(
            baseline.model_configuration.config_sha256
        ),
        cases_file_sha256="b" * 64,
        status_neutral_sha256="c" * 64,
        verified_case_count=0,
        require_full_suite=False,
    )
    path = tmp_path / "report.json"

    write_report_atomic(path, report)

    rendered = path.read_text(encoding="utf-8")
    assert json.loads(rendered)["evaluations"][0]["code"] == (
        "EVALUATION_INTERNAL_ERROR"
    )
    for forbidden in (
        "question",
            "gold_sql",
            '"sql"',
            '"rows"',
            "postgresql://",
        "api_key",
        "secret",
        "raw_error",
        ):
            assert forbidden.casefold() not in rendered.casefold()
    assert '"prompt_version"' in rendered
