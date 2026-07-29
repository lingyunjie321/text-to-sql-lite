from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from evaluation.models import (
    CaseCategory,
    EvaluationCase,
    ExpectedBehavior,
)

CASES_INITIAL_SHA256 = (
    "049e048b821e949936c1793d441f7adcda4660f10f8d0acf63e4f766a9726c22"
)
CASES_STATUS_NEUTRAL_SHA256 = (
    "a00a8ec7496fc4e1533b2773e0267d555357a80be435a02dd70981d76ddb40d7"
)
_EXPECTED_CATEGORY_COUNTS = {
    CaseCategory.SINGLE_TABLE: 5,
    CaseCategory.MULTI_JOIN: 4,
    CaseCategory.AGGREGATION: 3,
    CaseCategory.TIME: 1,
    CaseCategory.ANTI_JOIN: 1,
    CaseCategory.PERMISSION: 1,
    CaseCategory.DANGEROUS_SQL: 2,
    CaseCategory.REFLECTION: 1,
}


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _read_lines(path: Path) -> tuple[bytes, list[dict[str, object]]]:
    try:
        payload = path.read_bytes()
        text = payload.decode("utf-8")
        raw_lines = text.splitlines()
        if (
            not payload
            or not text.endswith("\n")
            or any(not line.strip() for line in raw_lines)
        ):
            raise ValueError
        items = [json.loads(line) for line in raw_lines]
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
        raise ValueError("evaluation case suite is invalid") from None
    if not all(isinstance(item, dict) for item in items):
        raise ValueError("evaluation case suite is invalid")
    return payload, items


def _status_neutral_payload(items: list[dict[str, object]]) -> bytes:
    neutral_lines: list[str] = []
    for source in items:
        item = dict(source)
        if "status" not in item:
            raise ValueError("evaluation case suite is invalid")
        item.pop("status")
        neutral_lines.append(
            json.dumps(
                item,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        )
    return ("\n".join(neutral_lines) + "\n").encode("utf-8")


def status_neutral_sha256(path: Path) -> str:
    _, items = _read_lines(path)
    return _sha256_bytes(_status_neutral_payload(items))


@dataclass(frozen=True, slots=True)
class LoadedCaseSuite:
    cases: tuple[EvaluationCase, ...]
    file_sha256: str
    status_neutral_sha256: str

    @property
    def executable_cases(self) -> tuple[EvaluationCase, ...]:
        return tuple(
            case
            for case in self.cases
            if case.expected_behavior is ExpectedBehavior.EXECUTE
        )

    @property
    def security_cases(self) -> tuple[EvaluationCase, ...]:
        return tuple(
            case
            for case in self.cases
            if case.expected_behavior is ExpectedBehavior.REJECT
        )


def _validate_full_suite(cases: tuple[EvaluationCase, ...]) -> None:
    expected_ids = tuple(
        f"PG-MVP-{number:03d}" for number in range(1, 19)
    )
    counts = Counter(case.category for case in cases)
    if (
        tuple(case.case_id for case in cases) != expected_ids
        or counts != Counter(_EXPECTED_CATEGORY_COUNTS)
        or len(
            {
                case.case_id
                for case in cases
            }
        )
        != len(cases)
        or len(
            [
                case
                for case in cases
                if case.expected_behavior is ExpectedBehavior.EXECUTE
            ]
        )
        != 15
        or len(
            [
                case
                for case in cases
                if case.expected_behavior is ExpectedBehavior.REJECT
            ]
        )
        != 3
    ):
        raise ValueError("evaluation case suite is invalid")


def load_case_suite(
    path: Path,
    *,
    require_full_suite: bool = True,
) -> LoadedCaseSuite:
    payload, items = _read_lines(path)
    try:
        cases = tuple(
            EvaluationCase.model_validate(item)
            for item in items
        )
    except ValidationError:
        raise ValueError("evaluation case suite is invalid") from None
    if (
        not cases
        or len({case.case_id for case in cases}) != len(cases)
    ):
        raise ValueError("evaluation case suite is invalid")
    if require_full_suite:
        _validate_full_suite(cases)
    return LoadedCaseSuite(
        cases=cases,
        file_sha256=_sha256_bytes(payload),
        status_neutral_sha256=_sha256_bytes(
            _status_neutral_payload(items)
        ),
    )
