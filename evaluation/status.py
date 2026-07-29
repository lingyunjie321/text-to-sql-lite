from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from evaluation.loader import (
    CASES_STATUS_NEUTRAL_SHA256,
    status_neutral_sha256,
)
from evaluation.models import AuditStatus
from evaluation.report import (
    EvaluationBaseline,
    load_report,
    require_report_baseline,
)
from evaluation.runner import (
    case_evidence_sha256,
    review_evidence_sha256,
)


def _atomic_write(path: Path, payload: bytes) -> None:
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


def mark_case_verified(
    case_path: Path,
    report_path: Path,
    *,
    current_baseline: EvaluationBaseline,
    case_id: str,
    expected_status_neutral_sha256: str,
) -> None:
    report = load_report(report_path)
    require_report_baseline(report, current_baseline)
    matches = tuple(
        item
        for item in report.evaluations
        if item.case_id == case_id
    )
    if len(matches) != 1:
        raise ValueError("evaluation case evidence is missing")
    evidence = matches[0]
    if not evidence.passed:
        raise ValueError("evaluation case has not passed")
    if evidence.audit_status is not AuditStatus.APPROVED:
        raise ValueError("evaluation case has not been reviewed")
    if case_evidence_sha256(evidence) != evidence.evidence_sha256:
        raise ValueError("evaluation evidence digest is invalid")
    if evidence.review_evidence_sha256 != review_evidence_sha256(
        evidence.evidence_sha256
    ):
        raise ValueError("evaluation review digest is invalid")

    current_neutral_hash = status_neutral_sha256(case_path)
    if (
        expected_status_neutral_sha256
        != CASES_STATUS_NEUTRAL_SHA256
        or report.status_neutral_sha256
        != CASES_STATUS_NEUTRAL_SHA256
        or report.baseline.gold_cases.status_neutral_sha256
        != CASES_STATUS_NEUTRAL_SHA256
    ):
        raise ValueError("Gold content does not match locked Gold baseline")
    if (
        current_neutral_hash != expected_status_neutral_sha256
        or current_neutral_hash != report.status_neutral_sha256
    ):
        raise ValueError("Gold content hash does not match")

    try:
        payload = case_path.read_bytes()
        lines = payload.splitlines(keepends=True)
        matches_by_line: list[tuple[int, dict[str, object]]] = []
        for index, line in enumerate(lines):
            item = json.loads(line.decode("utf-8"))
            if (
                isinstance(item, dict)
                and item.get("case_id") == case_id
            ):
                matches_by_line.append((index, item))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        raise ValueError("Gold status update is invalid") from None
    if len(matches_by_line) != 1:
        raise ValueError("Gold status update is invalid")
    index, original = matches_by_line[0]
    if original.get("status") == "verified":
        return
    token = b'"status":"draft"'
    if original.get("status") != "draft" or lines[index].count(token) != 1:
        raise ValueError("Gold status update is invalid")
    updated_line = lines[index].replace(
        token,
        b'"status":"verified"',
        1,
    )
    try:
        updated = json.loads(updated_line.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ValueError("Gold status update is invalid") from None
    expected = dict(original)
    expected["status"] = "verified"
    if updated != expected:
        raise ValueError("Gold status update is invalid")
    lines[index] = updated_line
    _atomic_write(case_path, b"".join(lines))
    if status_neutral_sha256(case_path) != current_neutral_hash:
        raise ValueError("Gold content hash does not match")
