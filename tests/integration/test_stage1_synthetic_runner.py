from collections.abc import Iterator
from pathlib import Path

import pytest

from evaluation.code_freeze import (
    Stage1CalibrationFreeze,
    load_stage1_calibration_freeze,
)
from evaluation.loader import load_retrieval_routing_suites
from evaluation.models import RetrievalRoutingSuiteRole


DEVELOPMENT_PATH = Path(
    "evaluation/cases/retrieval_routing_development.jsonl"
)
CALIBRATION_PATH = Path(
    "evaluation/cases/retrieval_routing_calibration.jsonl"
)


def _suites():
    return load_retrieval_routing_suites(
        DEVELOPMENT_PATH,
        CALIBRATION_PATH,
    )


def _freeze() -> Stage1CalibrationFreeze:
    return load_stage1_calibration_freeze(
        Path("evaluation/stage1_calibration_freeze.json")
    )


class StepWallClock:
    def __init__(self, values: tuple[float, ...]) -> None:
        self._values: Iterator[float] = iter(values)

    def __call__(self) -> float:
        return next(self._values)


def _wall_clock(case_count: int) -> StepWallClock:
    return StepWallClock(
        tuple(
            value
            for index in range(case_count)
            for value in (
                100.0 + index,
                100.025 + index,
            )
        )
    )


@pytest.mark.integration
def test_development_suite_runs_full_workflow_and_aggregates() -> None:
    from evaluation.stage1_runner import (
        run_stage1_synthetic_suite,
    )
    from evaluation.stage1_synthetic import (
        build_stage1_synthetic_model_routing_runtime,
        build_stage1_synthetic_retrieval_runtime,
    )

    suite = _suites().development
    result = run_stage1_synthetic_suite(
        suite,
        freeze=_freeze(),
        retrieval_runtime=(
            build_stage1_synthetic_retrieval_runtime()
        ),
        model_routing=(
            build_stage1_synthetic_model_routing_runtime()
        ),
        wall_clock=_wall_clock(len(suite.cases)),
    )

    assert tuple(item.case_id for item in result.evidence) == tuple(
        case.case_id for case in suite.cases
    )
    assert result.metrics.suite_role is (
        RetrievalRoutingSuiteRole.DEVELOPMENT
    )
    assert result.metrics.case_count == len(suite.cases)
    assert result.metrics.complexity_match_count == len(
        suite.cases
    )
    assert (
        result.metrics.expected_field_selection_pass_count
        == len(suite.cases)
    )
    assert result.metrics.join_recall_pass_count == len(
        suite.cases
    )
    assert result.metrics.embedding_degraded_count == 0
    assert result.metrics.rerank_degraded_count == 0
    assert result.quality_gate is None
    assert {
        item.latency_evidence[-1].duration_ms
        for item in result.evidence
    } == {25.0}


@pytest.mark.integration
def test_calibration_suite_runs_quality_gate() -> None:
    from evaluation.stage1_runner import (
        run_stage1_synthetic_suite,
    )
    from evaluation.stage1_synthetic import (
        build_stage1_synthetic_model_routing_runtime,
        build_stage1_synthetic_retrieval_runtime,
    )

    suite = _suites().calibration
    result = run_stage1_synthetic_suite(
        suite,
        freeze=_freeze(),
        retrieval_runtime=(
            build_stage1_synthetic_retrieval_runtime()
        ),
        model_routing=(
            build_stage1_synthetic_model_routing_runtime()
        ),
        wall_clock=_wall_clock(len(suite.cases)),
    )

    assert result.metrics.suite_role is (
        RetrievalRoutingSuiteRole.CALIBRATION
    )
    assert result.quality_gate is not None
    assert result.quality_gate.passed is True
    assert result.quality_gate.improved_bucket_count >= 1


def test_runner_rejects_suite_freeze_mismatch_before_workflow() -> None:
    from evaluation.stage1_runner import (
        run_stage1_synthetic_suite,
    )
    from evaluation.stage1_synthetic import (
        build_stage1_synthetic_model_routing_runtime,
        build_stage1_synthetic_retrieval_runtime,
    )

    suite = _suites().development
    mismatched = _freeze().model_copy(
        update={"development_file_sha256": "f" * 64}
    )

    with pytest.raises(
        ValueError,
        match=r"^stage1 synthetic run is invalid$",
    ):
        run_stage1_synthetic_suite(
            suite,
            freeze=mismatched,
            retrieval_runtime=(
                build_stage1_synthetic_retrieval_runtime()
            ),
            model_routing=(
                build_stage1_synthetic_model_routing_runtime()
            ),
            wall_clock=_wall_clock(len(suite.cases)),
        )
