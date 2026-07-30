from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from evaluation import loader as evaluation_loader
from evaluation import models as evaluation_models


DEVELOPMENT_PATH = Path(
    "evaluation/cases/retrieval_routing_development.jsonl"
)
CALIBRATION_PATH = Path(
    "evaluation/cases/retrieval_routing_calibration.jsonl"
)


def _read_lines(path: Path) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
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


def _valid_case() -> dict[str, object]:
    return {
        "case_id": "RRDEV-901",
        "suite_role": "development",
        "namespace": "synthetic/rrdev",
        "question": "定位需要校准的空气探头。",
        "allowed_tables": [
            "synthetic/rrdev.air_probe",
            "synthetic/rrdev.calibration_ticket",
        ],
        "expected_tables": [
            "synthetic/rrdev.air_probe",
            "synthetic/rrdev.calibration_ticket",
        ],
        "expected_fields": [
            "synthetic/rrdev.air_probe.probe_key",
            "synthetic/rrdev.calibration_ticket.probe_key",
        ],
        "expected_join_edges": [
            "synthetic/rrdev.air_probe.probe_key="
            "synthetic/rrdev.calibration_ticket.probe_key"
        ],
        "expected_complexity": "medium",
        "expected_top_k": 10,
    }


def test_loads_independent_development_and_calibration_suites() -> None:
    suites = evaluation_loader.load_retrieval_routing_suites(
        DEVELOPMENT_PATH,
        CALIBRATION_PATH,
    )

    assert (
        suites.development.role
        is evaluation_models.RetrievalRoutingSuiteRole.DEVELOPMENT
    )
    assert suites.development.namespace == "synthetic/rrdev"
    assert (
        suites.calibration.role
        is evaluation_models.RetrievalRoutingSuiteRole.CALIBRATION
    )
    assert suites.calibration.namespace == "synthetic/rrcal"
    for suite in (suites.development, suites.calibration):
        assert len(suite.cases) >= 6
        assert {case.expected_complexity for case in suite.cases} == {
            evaluation_models.Difficulty.SIMPLE,
            evaluation_models.Difficulty.MEDIUM,
            evaluation_models.Difficulty.COMPLEX,
        }
        assert {case.expected_top_k for case in suite.cases} == {
            5,
            10,
            20,
        }
        assert len(suite.raw_sha256) == 64
        assert len(suite.normalized_sha256) == 64

    development_ids = {
        case.case_id for case in suites.development.cases
    }
    calibration_ids = {
        case.case_id for case in suites.calibration.cases
    }
    development_questions = {
        case.question for case in suites.development.cases
    }
    calibration_questions = {
        case.question for case in suites.calibration.cases
    }
    assert development_ids.isdisjoint(calibration_ids)
    assert development_questions.isdisjoint(calibration_questions)


def test_normalized_hash_ignores_json_format_but_raw_hash_does_not(
    tmp_path: Path,
) -> None:
    original = evaluation_loader.load_retrieval_routing_suite(
        DEVELOPMENT_PATH,
        expected_role=(
            evaluation_models.RetrievalRoutingSuiteRole.DEVELOPMENT
        ),
    )
    lines = _read_lines(DEVELOPMENT_PATH)
    reformatted_path = tmp_path / "reformatted.jsonl"
    reformatted_path.write_text(
        "".join(
                json.dumps(
                    dict(reversed(tuple(line.items()))),
                    ensure_ascii=False,
                )
            + "\n"
            for line in lines
        ),
        encoding="utf-8",
    )

    reformatted = evaluation_loader.load_retrieval_routing_suite(
        reformatted_path,
        expected_role=(
            evaluation_models.RetrievalRoutingSuiteRole.DEVELOPMENT
        ),
    )

    assert reformatted.raw_sha256 != original.raw_sha256
    assert reformatted.normalized_sha256 == original.normalized_sha256


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("case_id", "RRCAL-901"),
        ("suite_role", "calibration"),
        ("namespace", "synthetic/rrcal"),
    ],
)
def test_case_rejects_mixed_role_id_or_namespace(
    field: str,
    value: object,
) -> None:
    item = _valid_case()
    item[field] = value

    with pytest.raises(ValidationError):
        evaluation_models.RetrievalRoutingCase.model_validate(item)


@pytest.mark.parametrize(
    "forbidden_field",
    ["sql", "result", "fixture", "gold_sql", "gold_tables"],
)
def test_case_forbids_sql_result_fixture_and_gold_control_fields(
    forbidden_field: str,
) -> None:
    item = _valid_case()
    item[forbidden_field] = "forbidden"

    with pytest.raises(ValidationError):
        evaluation_models.RetrievalRoutingCase.model_validate(item)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        (
            "expected_tables",
            ["synthetic/rrdev.not_allowed"],
        ),
        (
            "expected_fields",
            ["synthetic/rrdev.not_allowed.object_key"],
        ),
        (
            "expected_join_edges",
            [
                "synthetic/rrdev.air_probe.probe_key="
                "synthetic/rrdev.not_allowed.probe_key"
            ],
        ),
    ],
)
def test_case_rejects_expectations_outside_owned_tables(
    field: str,
    value: object,
) -> None:
    item = _valid_case()
    item[field] = value

    with pytest.raises(ValidationError):
        evaluation_models.RetrievalRoutingCase.model_validate(item)


def test_case_requires_join_endpoints_to_be_labeled_fields() -> None:
    item = _valid_case()
    item["expected_join_edges"] = [
        "synthetic/rrdev.air_probe.unlabeled_key="
        "synthetic/rrdev.calibration_ticket.probe_key"
    ]

    with pytest.raises(ValidationError):
        evaluation_models.RetrievalRoutingCase.model_validate(item)


def test_case_requires_complexity_top_k_contract() -> None:
    item = _valid_case()
    item["expected_top_k"] = 20

    with pytest.raises(ValidationError):
        evaluation_models.RetrievalRoutingCase.model_validate(item)


def test_loader_rejects_wrong_role_duplicate_id_and_incomplete_coverage(
    tmp_path: Path,
) -> None:
    lines = _read_lines(DEVELOPMENT_PATH)
    mutations = (
        (
            "wrong-role.jsonl",
            lines,
            evaluation_models.RetrievalRoutingSuiteRole.CALIBRATION,
        ),
        (
            "duplicate.jsonl",
            [*lines[:-1], dict(lines[0])],
            evaluation_models.RetrievalRoutingSuiteRole.DEVELOPMENT,
        ),
        (
            "too-small.jsonl",
            lines[:5],
            evaluation_models.RetrievalRoutingSuiteRole.DEVELOPMENT,
        ),
        (
            "missing-complexity.jsonl",
            [
                line
                for line in lines
                if line["expected_complexity"] != "complex"
            ],
            evaluation_models.RetrievalRoutingSuiteRole.DEVELOPMENT,
        ),
    )

    for filename, items, role in mutations:
        path = tmp_path / filename
        _write(path, items)
        with pytest.raises(ValueError, match="retrieval routing suite"):
            evaluation_loader.load_retrieval_routing_suite(
                path,
                expected_role=role,
            )


def test_pair_loader_rejects_overlapping_question_or_expectation(
    tmp_path: Path,
) -> None:
    development_lines = _read_lines(DEVELOPMENT_PATH)
    calibration_lines = _read_lines(CALIBRATION_PATH)

    same_question = [dict(line) for line in calibration_lines]
    same_question[0]["question"] = development_lines[0]["question"]
    same_question_path = tmp_path / "same-question.jsonl"
    _write(same_question_path, same_question)

    with pytest.raises(ValueError, match="not independent"):
        evaluation_loader.load_retrieval_routing_suites(
            DEVELOPMENT_PATH,
            same_question_path,
        )

    same_expectation = [dict(line) for line in calibration_lines]
    same_expectation[0].update(
        {
            "allowed_tables": [
                "synthetic/rrcal.weather_beacon",
            ],
            "expected_tables": [
                "synthetic/rrcal.weather_beacon",
            ],
            "expected_fields": [
                "synthetic/rrcal.weather_beacon.beacon_key",
            ],
            "expected_join_edges": [],
        }
    )
    same_expectation_path = tmp_path / "same-expectation.jsonl"
    _write(same_expectation_path, same_expectation)

    with pytest.raises(ValueError, match="not independent"):
        evaluation_loader.load_retrieval_routing_suites(
            DEVELOPMENT_PATH,
            same_expectation_path,
        )
