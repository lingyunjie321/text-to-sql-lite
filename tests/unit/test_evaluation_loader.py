import json
from pathlib import Path

import pytest

from evaluation import (
    CASES_STATUS_NEUTRAL_SHA256,
    load_case_suite,
    status_neutral_sha256,
)

CASES_PATH = Path("evaluation/cases/pagila_mvp_all_draft.jsonl")


def _lines() -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in CASES_PATH.read_text(encoding="utf-8").splitlines()
    ]


def _write(path: Path, lines: list[dict[str, object]]) -> None:
    path.write_text(
        "".join(
            json.dumps(
                line,
                ensure_ascii=False,
                separators=(",", ":"),
            )
            + "\n"
            for line in lines
        ),
        encoding="utf-8",
    )


def test_loads_locked_18_case_suite_with_expected_denominators() -> None:
    suite = load_case_suite(CASES_PATH)

    assert len(suite.cases) == 18
    assert tuple(case.case_id for case in suite.cases) == tuple(
        f"PG-MVP-{number:03d}" for number in range(1, 19)
    )
    assert len(suite.executable_cases) == 15
    assert len(suite.security_cases) == 3
    assert suite.status_neutral_sha256 == CASES_STATUS_NEUTRAL_SHA256


def test_loader_rejects_duplicate_case_id(tmp_path: Path) -> None:
    lines = _lines()
    lines[-1]["case_id"] = "PG-MVP-001"
    path = tmp_path / "duplicate.jsonl"
    _write(path, lines)

    with pytest.raises(ValueError, match="case suite"):
        load_case_suite(path)


def test_loader_rejects_category_count_drift(tmp_path: Path) -> None:
    lines = _lines()
    lines[0]["category"] = "aggregation"
    path = tmp_path / "category-drift.jsonl"
    _write(path, lines)

    with pytest.raises(ValueError, match="case suite"):
        load_case_suite(path)


def test_loader_rejects_blank_or_malformed_jsonl(tmp_path: Path) -> None:
    for content in ("", "{}\n\n", "{not-json}\n"):
        path = tmp_path / "invalid.jsonl"
        path.write_text(content, encoding="utf-8")

        with pytest.raises(ValueError, match="case suite"):
            load_case_suite(path)


def test_status_neutral_hash_ignores_only_status(tmp_path: Path) -> None:
    lines = _lines()
    path = tmp_path / "status-only.jsonl"
    _write(path, lines)
    initial = status_neutral_sha256(path)
    lines[0]["status"] = "verified"
    _write(path, lines)

    assert status_neutral_sha256(path) == initial

    lines[0]["question"] = "changed"
    _write(path, lines)
    assert status_neutral_sha256(path) != initial


def test_partial_suite_is_allowed_only_when_explicit(
    tmp_path: Path,
) -> None:
    path = tmp_path / "one.jsonl"
    _write(path, [_lines()[0]])

    with pytest.raises(ValueError, match="case suite"):
        load_case_suite(path)

    suite = load_case_suite(path, require_full_suite=False)
    assert len(suite.cases) == 1
