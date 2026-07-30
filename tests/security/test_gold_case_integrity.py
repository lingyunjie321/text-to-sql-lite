import base64
import json
from dataclasses import replace
from pathlib import Path
from urllib.parse import quote

import pytest

from evaluation import (
    CASES_INITIAL_SHA256,
    CASES_STATUS_NEUTRAL_SHA256,
    load_case_suite,
)
from evaluation.loader import (
    load_retrieval_routing_suites,
    validate_retrieval_routing_gold_isolation,
)
from evaluation.models import RetrievalRoutingCase

CASES_PATH = Path("evaluation/cases/pagila_mvp.jsonl")
DEVELOPMENT_PATH = Path(
    "evaluation/cases/retrieval_routing_development.jsonl"
)
CALIBRATION_PATH = Path(
    "evaluation/cases/retrieval_routing_calibration.jsonl"
)


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


def test_stage1_suites_do_not_copy_gold_domains() -> None:
    validate_retrieval_routing_gold_isolation(
        load_retrieval_routing_suites(
            DEVELOPMENT_PATH,
            CALIBRATION_PATH,
        ),
        load_case_suite(CASES_PATH),
    )


@pytest.mark.parametrize(
    "transform",
    (
        lambda value: value,
        lambda value: f"隔离前缀 {value} 隔离后缀",
        lambda value: value[:1] + "\u200b" + value[1:],
        lambda value: quote(value, safe=""),
        lambda value: base64.b64encode(
            value.encode("utf-8")
        ).decode("ascii"),
        lambda value: value.encode("utf-8").hex(),
    ),
)
def test_stage1_gold_question_reversible_copies_fail_closed(
    transform,
) -> None:
    suites = load_retrieval_routing_suites(
        DEVELOPMENT_PATH,
        CALIBRATION_PATH,
    )
    gold = load_case_suite(CASES_PATH)
    original = suites.development.cases[0]
    polluted = RetrievalRoutingCase.model_validate(
        {
            **original.model_dump(),
            "question": transform(gold.cases[0].question),
        }
    )
    changed = replace(
        suites,
        development=replace(
            suites.development,
            cases=(polluted, *suites.development.cases[1:]),
        ),
    )

    with pytest.raises(
        ValueError,
        match=r"^retrieval routing suite contains Gold contamination",
    ) as captured:
        validate_retrieval_routing_gold_isolation(
            changed,
            gold,
        )

    rendered = str(captured.value)
    assert gold.cases[0].question not in rendered
    assert gold.cases[0].gold_sql not in rendered


@pytest.mark.parametrize(
    "gold_text",
    (
        "gold_sql",
        "expected_final_status",
        "category",
        "tag",
    ),
)
def test_stage1_gold_sql_and_labels_cannot_enter_questions(
    gold_text: str,
) -> None:
    suites = load_retrieval_routing_suites(
        DEVELOPMENT_PATH,
        CALIBRATION_PATH,
    )
    gold = load_case_suite(CASES_PATH)
    gold_case = gold.cases[0]
    values = {
        "gold_sql": gold_case.gold_sql,
        "expected_final_status": (
            gold_case.expected_final_status.value
        ),
        "category": gold_case.category.value,
        "tag": gold_case.tags[0],
    }
    original = suites.development.cases[0]
    polluted = RetrievalRoutingCase.model_validate(
        {
            **original.model_dump(),
            "question": f"隔离前缀 {values[gold_text]} 隔离后缀",
        }
    )
    changed = replace(
        suites,
        development=replace(
            suites.development,
            cases=(polluted, *suites.development.cases[1:]),
        ),
    )

    with pytest.raises(
        ValueError,
        match=r"^retrieval routing suite contains Gold contamination",
    ):
        validate_retrieval_routing_gold_isolation(
            changed,
            gold,
        )


def test_stage1_gold_object_copy_fails_after_namespace_removal() -> None:
    suites = load_retrieval_routing_suites(
        DEVELOPMENT_PATH,
        CALIBRATION_PATH,
    )
    gold = load_case_suite(CASES_PATH)
    original = suites.development.cases[0]
    polluted_table = "synthetic/rrdev.film"
    polluted_field = f"{polluted_table}.film_id"
    polluted = RetrievalRoutingCase.model_validate(
        {
            **original.model_dump(),
            "allowed_tables": (polluted_table,),
            "expected_tables": (polluted_table,),
            "expected_fields": (polluted_field,),
            "expected_join_edges": (),
        }
    )
    changed = replace(
        suites,
        development=replace(
            suites.development,
            cases=(polluted, *suites.development.cases[1:]),
        ),
    )

    with pytest.raises(
        ValueError,
        match=r"^retrieval routing suite contains Gold contamination",
    ):
        validate_retrieval_routing_gold_isolation(
            changed,
            gold,
        )
