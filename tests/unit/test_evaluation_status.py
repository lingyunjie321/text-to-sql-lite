import hashlib
import json
from pathlib import Path

import pytest

from app.workflow import FinalStatus
from evaluation import (
    AuditStatus,
    CaseEvaluation,
    CaseStatus,
    ComparisonResult,
    ExpectedBehavior,
)
from evaluation.code_freeze import evaluation_baseline_id
from evaluation.report import (
    EvaluationBaseline,
    build_evaluation_report,
    load_baseline,
    load_report,
    review_case,
    write_report_atomic,
)
from evaluation.runner import case_evidence_sha256
from evaluation.runner import review_evidence_sha256
from evaluation import status as evaluation_status
from evaluation.status import mark_case_verified

BASELINE_PATH = Path("evaluation/pagila_baseline.json")


def _evaluation(
    *,
    passed: bool = True,
    audit_status: AuditStatus = AuditStatus.PENDING,
) -> CaseEvaluation:
    fields: dict[str, object] = {
        "case_id": "PG-MVP-001",
        "evaluation_baseline_id": "0" * 64,
        "initial_status": CaseStatus.DRAFT,
        "expected_behavior": ExpectedBehavior.EXECUTE,
        "expected_final_status": FinalStatus.SUCCEEDED_FIRST_PASS,
        "actual_final_status": FinalStatus.SUCCEEDED_FIRST_PASS,
        "gold_validation_passed": True,
        "gold_executed": True,
        "prediction_validation_passed": True,
        "prediction_execute_count": 1,
        "comparison": ComparisonResult(
            passed=True,
            code="RESULT_MATCH",
            message="results match",
            predicted_row_count=1,
            gold_row_count=1,
        ),
        "table_recall_passed": True,
        "field_recall_passed": True,
        "join_recall_passed": True,
        "attempt_count": 1,
        "repair_count": 0,
        "trace_sha256": "a" * 64,
        "passed": passed,
        "code": (
            "EVALUATION_PASS"
            if passed
            else "EVALUATION_FINAL_STATUS_MISMATCH"
        ),
    }
    evidence_sha256 = case_evidence_sha256(fields)
    return CaseEvaluation(
        **fields,
        evidence_sha256=evidence_sha256,
        audit_status=audit_status,
        review_evidence_sha256=(
            review_evidence_sha256(evidence_sha256)
            if audit_status is AuditStatus.APPROVED
            else None
        ),
    )


def _case_line(status: str = "draft") -> str:
    return (
        '{"case_id":"PG-MVP-001","status":"'
        + status
        + '","question":"unchanged","gold_sql":"SELECT 1"}\n'
    )


def _neutral_hash(path: Path) -> str:
    item = json.loads(path.read_text(encoding="utf-8"))
    item.pop("status")
    payload = (
        json.dumps(
            item,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _report(
    path: Path,
    evaluation: CaseEvaluation,
    *,
    neutral_hash: str,
) -> None:
    original = load_baseline(BASELINE_PATH)
    payload = original.model_dump(
        mode="json",
        exclude={"evaluation_baseline_id"},
    )
    payload["gold_cases"]["status_neutral_sha256"] = neutral_hash
    baseline = EvaluationBaseline.model_validate(
        {
            **payload,
            "evaluation_baseline_id": evaluation_baseline_id(
                payload
            ),
        }
    )
    fields = evaluation.model_dump(
        exclude={
            "evidence_sha256",
            "audit_status",
            "review_evidence_sha256",
        }
    )
    fields["evaluation_baseline_id"] = (
        baseline.evaluation_baseline_id
    )
    evidence_sha256 = case_evidence_sha256(fields)
    rebound = CaseEvaluation(
        **fields,
        evidence_sha256=evidence_sha256,
        audit_status=evaluation.audit_status,
        review_evidence_sha256=(
            review_evidence_sha256(evidence_sha256)
            if evaluation.audit_status is AuditStatus.APPROVED
            else None
        ),
    )
    report = build_evaluation_report(
        (rebound,),
        baseline=baseline,
        model_config_hash=(
            baseline.model_configuration.config_sha256
        ),
        cases_file_sha256="c" * 64,
        status_neutral_sha256=neutral_hash,
        verified_case_count=0,
        require_full_suite=False,
    )
    write_report_atomic(path, report)


def _current_baseline(path: Path) -> EvaluationBaseline:
    return load_report(path).baseline


def test_review_case_approves_only_automated_pass(
    tmp_path: Path,
) -> None:
    report_path = tmp_path / "report.json"
    _report(
        report_path,
        _evaluation(),
        neutral_hash="d" * 64,
    )

    review_case(
        report_path,
        current_baseline=_current_baseline(report_path),
        case_id="PG-MVP-001",
        approved=True,
    )

    reviewed = load_report(report_path).evaluations[0]
    assert reviewed.audit_status is AuditStatus.APPROVED
    assert case_evidence_sha256(reviewed) == reviewed.evidence_sha256
    assert reviewed.review_evidence_sha256 == review_evidence_sha256(
        reviewed.evidence_sha256
    )


def test_review_case_cannot_approve_failed_evidence(
    tmp_path: Path,
) -> None:
    report_path = tmp_path / "report.json"
    _report(
        report_path,
        _evaluation(passed=False),
        neutral_hash="d" * 64,
    )

    with pytest.raises(ValueError, match="cannot be approved"):
        review_case(
            report_path,
            current_baseline=_current_baseline(report_path),
            case_id="PG-MVP-001",
            approved=True,
        )


def test_report_loader_rejects_derived_metric_tampering(
    tmp_path: Path,
) -> None:
    report_path = tmp_path / "report.json"
    _report(
        report_path,
        _evaluation(),
        neutral_hash="d" * 64,
    )
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    payload["metrics"]["automated_passed"] = 0
    report_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="report"):
        load_report(report_path)


def test_single_case_update_changes_only_status_token(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cases_path = tmp_path / "cases.jsonl"
    cases_path.write_text(_case_line(), encoding="utf-8")
    before = cases_path.read_bytes()
    report_path = tmp_path / "report.json"
    _report(
        report_path,
        _evaluation(audit_status=AuditStatus.APPROVED),
        neutral_hash=_neutral_hash(cases_path),
    )
    monkeypatch.setattr(
        evaluation_status,
        "CASES_STATUS_NEUTRAL_SHA256",
        _neutral_hash(cases_path),
    )

    mark_case_verified(
        cases_path,
        report_path,
        current_baseline=_current_baseline(report_path),
        case_id="PG-MVP-001",
        expected_status_neutral_sha256=_neutral_hash(cases_path),
    )

    after = cases_path.read_bytes()
    assert after == before.replace(
        b'"status":"draft"',
        b'"status":"verified"',
        1,
    )
    assert _neutral_hash(cases_path) == load_report(
        report_path
    ).status_neutral_sha256


@pytest.mark.parametrize(
    ("evaluation", "expected_message"),
    [
        (_evaluation(), "reviewed"),
        (_evaluation(passed=False), "passed"),
    ],
)
def test_status_update_refuses_insufficient_evidence(
    tmp_path: Path,
    evaluation: CaseEvaluation,
    expected_message: str,
) -> None:
    cases_path = tmp_path / "cases.jsonl"
    cases_path.write_text(_case_line(), encoding="utf-8")
    report_path = tmp_path / "report.json"
    _report(
        report_path,
        evaluation,
        neutral_hash=_neutral_hash(cases_path),
    )

    with pytest.raises(ValueError, match=expected_message):
        mark_case_verified(
            cases_path,
            report_path,
            current_baseline=_current_baseline(report_path),
            case_id="PG-MVP-001",
            expected_status_neutral_sha256=_neutral_hash(cases_path),
        )

    assert cases_path.read_text(encoding="utf-8") == _case_line()


def test_status_update_refuses_neutral_hash_drift(
    tmp_path: Path,
) -> None:
    cases_path = tmp_path / "cases.jsonl"
    cases_path.write_text(_case_line(), encoding="utf-8")
    report_path = tmp_path / "report.json"
    _report(
        report_path,
        _evaluation(audit_status=AuditStatus.APPROVED),
        neutral_hash=_neutral_hash(cases_path),
    )

    with pytest.raises(ValueError, match="locked Gold baseline"):
        mark_case_verified(
            cases_path,
            report_path,
            current_baseline=_current_baseline(report_path),
            case_id="PG-MVP-001",
            expected_status_neutral_sha256="0" * 64,
        )

    assert cases_path.read_text(encoding="utf-8") == _case_line()


def test_status_update_refuses_tampered_evidence_digest(
    tmp_path: Path,
) -> None:
    cases_path = tmp_path / "cases.jsonl"
    cases_path.write_text(_case_line(), encoding="utf-8")
    report_path = tmp_path / "report.json"
    _report(
        report_path,
        _evaluation(audit_status=AuditStatus.APPROVED),
        neutral_hash=_neutral_hash(cases_path),
    )
    report_data = json.loads(report_path.read_text(encoding="utf-8"))
    report_data["evaluations"][0]["attempt_count"] = 2
    report_path.write_text(
        json.dumps(report_data),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="report"):
        mark_case_verified(
            cases_path,
            report_path,
            current_baseline=_current_baseline(report_path),
            case_id="PG-MVP-001",
            expected_status_neutral_sha256=_neutral_hash(cases_path),
        )

    assert cases_path.read_text(encoding="utf-8") == _case_line()


def test_status_update_refuses_forged_audit_status(
    tmp_path: Path,
) -> None:
    cases_path = tmp_path / "cases.jsonl"
    cases_path.write_text(_case_line(), encoding="utf-8")
    report_path = tmp_path / "report.json"
    _report(
        report_path,
        _evaluation(),
        neutral_hash=_neutral_hash(cases_path),
    )
    report_data = json.loads(report_path.read_text(encoding="utf-8"))
    report_data["evaluations"][0]["audit_status"] = "approved"
    report_path.write_text(
        json.dumps(report_data),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="report"):
        mark_case_verified(
            cases_path,
            report_path,
            current_baseline=_current_baseline(report_path),
            case_id="PG-MVP-001",
            expected_status_neutral_sha256=_neutral_hash(cases_path),
        )

    assert cases_path.read_text(encoding="utf-8") == _case_line()


def test_status_update_does_not_trust_a_tampered_report_baseline(
    tmp_path: Path,
) -> None:
    cases_path = tmp_path / "cases.jsonl"
    cases_path.write_text(
        _case_line().replace("unchanged", "tampered"),
        encoding="utf-8",
    )
    report_path = tmp_path / "report.json"
    neutral_hash = _neutral_hash(cases_path)
    _report(
        report_path,
        _evaluation(audit_status=AuditStatus.APPROVED),
        neutral_hash=neutral_hash,
    )
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    payload["baseline"]["gold_cases"][
        "status_neutral_sha256"
    ] = "0" * 64
    report_path.write_text(
        json.dumps(payload),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="report"):
        mark_case_verified(
            cases_path,
            report_path,
            current_baseline=_current_baseline(report_path),
            case_id="PG-MVP-001",
            expected_status_neutral_sha256=neutral_hash,
        )

    assert '"status":"draft"' in cases_path.read_text(
        encoding="utf-8"
    )


def _rebound_baseline(
    baseline: EvaluationBaseline,
) -> EvaluationBaseline:
    payload = baseline.model_dump(
        mode="json",
        exclude={"evaluation_baseline_id"},
    )
    payload["model_configuration"]["config_sha256"] = "f" * 64
    return EvaluationBaseline.model_validate(
        {
            **payload,
            "evaluation_baseline_id": evaluation_baseline_id(payload),
        }
    )


def test_review_case_refuses_report_from_previous_baseline(
    tmp_path: Path,
) -> None:
    report_path = tmp_path / "report.json"
    _report(
        report_path,
        _evaluation(),
        neutral_hash="d" * 64,
    )
    before = report_path.read_bytes()
    previous = _current_baseline(report_path)

    with pytest.raises(ValueError, match="current baseline"):
        review_case(
            report_path,
            current_baseline=_rebound_baseline(previous),
            case_id="PG-MVP-001",
            approved=True,
        )

    assert report_path.read_bytes() == before


def test_status_update_refuses_report_from_previous_baseline(
    tmp_path: Path,
) -> None:
    cases_path = tmp_path / "cases.jsonl"
    cases_path.write_text(_case_line(), encoding="utf-8")
    report_path = tmp_path / "report.json"
    _report(
        report_path,
        _evaluation(audit_status=AuditStatus.APPROVED),
        neutral_hash=_neutral_hash(cases_path),
    )
    before = cases_path.read_bytes()
    previous = _current_baseline(report_path)

    with pytest.raises(ValueError, match="current baseline"):
        mark_case_verified(
            cases_path,
            report_path,
            current_baseline=_rebound_baseline(previous),
            case_id="PG-MVP-001",
            expected_status_neutral_sha256=_neutral_hash(cases_path),
        )

    assert cases_path.read_bytes() == before
