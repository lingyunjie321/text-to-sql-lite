from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from typing import Protocol

from app.observability.models import (
    TraceAttempt,
    TraceGeneration,
    TraceNode,
    TraceRecord,
)
from app.reflection import SQLAttempt
from app.workflow import SQLTaskState, WorkflowContext, run_workflow

_LOGGER = logging.getLogger(__name__)


class TraceSink(Protocol):
    def emit(self, record: TraceRecord) -> None: ...


class WorkflowRunner(Protocol):
    def __call__(
        self,
        state: SQLTaskState,
        *,
        context: WorkflowContext,
    ) -> SQLTaskState: ...


class SafeLoggingTraceSink:
    def __init__(self, logger: logging.Logger | None = None) -> None:
        self._logger = logger or _LOGGER

    def emit(self, record: TraceRecord) -> None:
        self._logger.info(
            "text_to_sql_trace %s",
            record.model_dump_json(),
        )


def _identifier_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _attempt_trace(attempt: SQLAttempt) -> TraceAttempt:
    validation = attempt.validation_result
    execution = attempt.execution_result
    return TraceAttempt(
        attempt_number=attempt.attempt_number,
        fingerprint=attempt.fingerprint,
        validation_passed=(
            validation.is_valid
            if validation is not None
            else None
        ),
        execution_succeeded=execution is not None,
        error_type=attempt.current_error_type,
        database_duration_ms=(
            execution.execution_time_ms
            if execution is not None
            else None
        ),
    )


def build_trace_record(state: SQLTaskState) -> TraceRecord:
    if state.final_status is None:
        raise ValueError("workflow state is not terminal")
    attempts = tuple(
        _attempt_trace(attempt)
        for attempt in state.sql_attempts
        if isinstance(attempt, SQLAttempt)
    )
    execution = state.execution_result
    return TraceRecord(
        request_id=state.request_id,
        trace_id=state.trace_id,
        final_status=state.final_status,
        error_type=state.error_type,
        error_code=(
            state.public_error.code
            if state.public_error is not None
            else None
        ),
        schema_version=state.schema_version,
        repair_count=state.repair_count,
        infrastructure_retry_count=state.infrastructure_retry_count,
        input_tokens=state.token_usage.input_tokens,
        output_tokens=state.token_usage.output_tokens,
        database_duration_ms=(
            execution.execution_time_ms
            if execution is not None
            else None
        ),
        returned_row_count=(
            execution.returned_row_count
            if execution is not None
            else 0
        ),
        truncated=(
            execution.truncated
            if execution is not None
            else False
        ),
        nodes=tuple(
            TraceNode(
                node=timing.node,
                duration_ms=timing.duration_ms,
                attempt_number=timing.attempt_number,
                route=timing.route,
            )
            for timing in state.node_timings
        ),
        attempts=attempts,
        generations=tuple(
            TraceGeneration(
                call_number=observation.call_number,
                attempt_number=observation.attempt_number,
                model_config_hash=_identifier_hash(
                    observation.model_config_id
                ),
                provider_contract_version=(
                    observation.provider_prompt_version
                ),
                effective_contract_version=(
                    observation.effective_prompt_version
                ),
                repair_strategy=observation.repair_strategy,
                input_tokens=observation.input_tokens,
                output_tokens=observation.output_tokens,
            )
            for observation in state.generation_observations
        ),
    )


@dataclass(frozen=True, slots=True)
class TracedWorkflowRunner:
    base_runner: WorkflowRunner
    sink: TraceSink
    logger: logging.Logger = _LOGGER

    def __post_init__(self) -> None:
        if (
            not callable(self.base_runner)
            or not callable(getattr(self.sink, "emit", None))
            or not isinstance(self.logger, logging.Logger)
        ):
            raise ValueError("traced workflow runner is invalid")

    def __call__(
        self,
        state: SQLTaskState,
        *,
        context: WorkflowContext,
    ) -> SQLTaskState:
        terminal = self.base_runner(state, context=context)
        try:
            self.sink.emit(build_trace_record(terminal))
        except Exception:
            self.logger.warning(
                "text_to_sql_trace_sink_degraded"
            )
        return terminal


def default_traced_runner() -> TracedWorkflowRunner:
    return TracedWorkflowRunner(
        run_workflow,
        SafeLoggingTraceSink(),
    )
