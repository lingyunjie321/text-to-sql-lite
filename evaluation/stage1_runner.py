from __future__ import annotations

import math
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from app.generation import ModelRoutingRuntime
from app.observability import (
    TraceRecord,
    TracedWorkflowRunner,
)
from app.schema_linking import RetrievalRuntime
from app.workflow import (
    WorkflowContext,
    new_task_state,
    run_workflow,
)
from evaluation.code_freeze import (
    Stage1CalibrationFreeze,
    controlled_code_sha256,
    load_stage1_selected_configuration,
    verify_stage1_calibration_freeze,
)
from evaluation.loader import (
    LoadedRetrievalRoutingSuite,
    load_retrieval_routing_suites,
)
from evaluation.models import (
    RetrievalRoutingCaseEvidence,
    RetrievalRoutingSuiteRole,
)
from evaluation.report import (
    Stage1RetrievalMetrics,
    Stage1RetrievalQualityGate,
    aggregate_stage1_retrieval_metrics,
    qualify_stage1_retrieval,
)
from evaluation.runner import collect_retrieval_routing_evidence
from evaluation.stage1_synthetic import (
    Stage1SyntheticConnector,
    validate_stage1_synthetic_suite,
)

_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_SELECTED_CONFIGURATION_PATH = (
    _REPOSITORY_ROOT
    / "evaluation"
    / "stage1_selected_configuration.json"
)


@dataclass(frozen=True, slots=True)
class Stage1SyntheticRunResult:
    evidence: tuple[RetrievalRoutingCaseEvidence, ...]
    metrics: Stage1RetrievalMetrics
    quality_gate: Stage1RetrievalQualityGate | None


@dataclass(slots=True)
class _RecordingTraceSink:
    records: list[TraceRecord]

    def emit(self, record: TraceRecord) -> None:
        self.records.append(record)


def _validate_run_inputs(
    *,
    suite: LoadedRetrievalRoutingSuite,
    freeze: Stage1CalibrationFreeze,
    retrieval_runtime: RetrievalRuntime,
    model_routing: ModelRoutingRuntime,
    wall_clock: Callable[[], float],
) -> None:
    if (
        not isinstance(suite, LoadedRetrievalRoutingSuite)
        or not isinstance(freeze, Stage1CalibrationFreeze)
        or not isinstance(retrieval_runtime, RetrievalRuntime)
        or not isinstance(model_routing, ModelRoutingRuntime)
        or not callable(wall_clock)
    ):
        raise ValueError("stage1 synthetic run is invalid")
    expected_hashes = (
        (
            freeze.development_file_sha256,
            freeze.development_normalized_sha256,
        )
        if suite.role is RetrievalRoutingSuiteRole.DEVELOPMENT
        else (
            freeze.calibration_file_sha256,
            freeze.calibration_normalized_sha256,
        )
    )
    if (
        (suite.raw_sha256, suite.normalized_sha256)
        != expected_hashes
    ):
        raise ValueError("stage1 synthetic run is invalid")
    selected = load_stage1_selected_configuration(
        _SELECTED_CONFIGURATION_PATH
    )
    suites = load_retrieval_routing_suites(
        _REPOSITORY_ROOT
        / "evaluation"
        / "cases"
        / "retrieval_routing_development.jsonl",
        _REPOSITORY_ROOT
        / "evaluation"
        / "cases"
        / "retrieval_routing_calibration.jsonl",
    )
    verify_stage1_calibration_freeze(
        freeze,
        development_file_sha256=(
            suites.development.raw_sha256
        ),
        development_normalized_sha256=(
            suites.development.normalized_sha256
        ),
        calibration_file_sha256=(
            suites.calibration.raw_sha256
        ),
        calibration_normalized_sha256=(
            suites.calibration.normalized_sha256
        ),
        public_configuration=selected.public_configuration,
        controlled_code_sha256_value=(
            controlled_code_sha256(_REPOSITORY_ROOT)
        ),
    )
    if selected.stage1_config_sha256 != freeze.stage1_config_sha256:
        raise ValueError("stage1 synthetic run is invalid")
    validate_stage1_synthetic_suite(suite)


def run_stage1_synthetic_suite(
    suite: LoadedRetrievalRoutingSuite,
    *,
    freeze: Stage1CalibrationFreeze,
    retrieval_runtime: RetrievalRuntime,
    model_routing: ModelRoutingRuntime,
    wall_clock: Callable[[], float] = time.monotonic,
) -> Stage1SyntheticRunResult:
    _validate_run_inputs(
        suite=suite,
        freeze=freeze,
        retrieval_runtime=retrieval_runtime,
        model_routing=model_routing,
        wall_clock=wall_clock,
    )
    evidence: list[RetrievalRoutingCaseEvidence] = []
    for case in suite.cases:
        sink = _RecordingTraceSink(records=[])
        started_at = wall_clock()
        if (
            type(started_at) not in (int, float)
            or not math.isfinite(float(started_at))
        ):
            raise ValueError("stage1 synthetic run is invalid")
        terminal = TracedWorkflowRunner(
            run_workflow,
            sink,
        )(
            new_task_state(
                request_id=f"stage1-{case.case_id.casefold()}",
                trace_id=f"trace-{case.case_id.casefold()}",
                question=case.question,
                datasource_id="synthetic",
                requested_schemas=(case.namespace,),
            ),
            context=WorkflowContext(
                connector=Stage1SyntheticConnector(),
                model_routing=model_routing,
                retrieval_runtime=retrieval_runtime,
                datasource_id="synthetic",
                allowed_schemas=(case.namespace,),
                allowed_tables=case.allowed_tables,
                now=datetime(
                    2026,
                    1,
                    1,
                    tzinfo=timezone.utc,
                ),
            ),
        )
        finished_at = wall_clock()
        if (
            type(finished_at) not in (int, float)
            or not math.isfinite(float(finished_at))
            or finished_at < started_at
            or len(sink.records) != 1
        ):
            raise ValueError("stage1 synthetic run is invalid")
        evidence.append(
            collect_retrieval_routing_evidence(
                case,
                terminal,
                sink.records[0],
                suite=suite,
                freeze=freeze,
                workflow_wall_clock_duration_ms=(
                    round(
                        (
                            float(finished_at)
                            - float(started_at)
                        )
                        * 1000,
                        9,
                    )
                ),
            )
        )

    metrics = aggregate_stage1_retrieval_metrics(
        tuple(evidence),
        suite=suite,
        freeze=freeze,
    )
    quality_gate = (
        qualify_stage1_retrieval(metrics)
        if suite.role is RetrievalRoutingSuiteRole.CALIBRATION
        else None
    )
    return Stage1SyntheticRunResult(
        evidence=tuple(evidence),
        metrics=metrics,
        quality_gate=quality_gate,
    )
