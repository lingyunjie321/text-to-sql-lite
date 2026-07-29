import json
from pathlib import Path

from evaluation import (
    CASES_INITIAL_SHA256,
    CASES_STATUS_NEUTRAL_SHA256,
    load_case_suite,
)

CASES_PATH = Path("evaluation/cases/pagila_mvp.jsonl")


def test_gold_suite_preserves_locked_non_status_content() -> None:
    suite = load_case_suite(CASES_PATH)

    assert suite.status_neutral_sha256 == CASES_STATUS_NEUTRAL_SHA256
    statuses = {case.status.value for case in suite.cases}
    assert statuses <= {"draft", "verified"}
    if statuses == {"draft"}:
        assert suite.file_sha256 == CASES_INITIAL_SHA256


def test_gold_sql_and_questions_are_not_reused_as_fixtures() -> None:
    cases = [
        json.loads(line)
        for line in CASES_PATH.read_text(encoding="utf-8").splitlines()
    ]

    for case in cases:
        fixture = case.get("fixture", {})
        assert case["question"] not in fixture.values()
        if case["gold_sql"]:
            assert case["gold_sql"] not in fixture.values()
