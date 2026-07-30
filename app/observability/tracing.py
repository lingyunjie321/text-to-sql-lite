from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from typing import Protocol

from app.observability.models import (
    TraceAttempt,
    TraceComplexity,
    TraceContextSelection,
    TraceGeneration,
    TraceModelRouting,
    TraceNode,
    TraceRecord,
    TraceRetrieval,
)
from app.schema_linking import RerankReason
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
    retrieval_pool = state.schema_retrieval_pool
    retrieval_failure = state.retrieval_failure
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
        complexity=(
            TraceComplexity(
                level=state.complexity_decision.level,
                schema_top_k=(
                    state.complexity_decision.schema_top_k
                ),
                reason_codes=(
                    state.complexity_decision.reason_codes
                ),
                policy_version=(
                    state.complexity_decision.policy_version
                ),
            )
            if state.complexity_decision is not None
            else None
        ),
        retrieval=(
            TraceRetrieval(
                retrieval_version_id=(
                    retrieval_pool.retrieval_version_id
                ),
                retrieval_version_contract=(
                    retrieval_pool.retrieval_version_contract
                ),
                bm25_version=retrieval_pool.bm25_version,
                embedding_provider_contract_version=(
                    retrieval_pool
                    .embedding_provider_contract_version
                ),
                embedding_provider_config_hash=(
                    retrieval_pool
                    .embedding_provider_config_sha256
                ),
                document_version=(
                    retrieval_pool.document_version
                ),
                fusion_version=retrieval_pool.fusion_version,
                rrf_k=retrieval_pool.rrf_k,
                rerank_version=(
                    retrieval_pool.rerank_version
                ),
                mode=retrieval_pool.mode,
                embedding_degradation=(
                    retrieval_pool.embedding_degradation
                ),
                candidate_table_count=len(
                    retrieval_pool.ranked_table_ids
                ),
                candidate_field_count=len(
                    retrieval_pool.ranked_field_ids
                ),
                probe_table_count=(
                    state.probe_candidate_table_count
                ),
                probe_field_count=(
                    state.probe_candidate_field_count
                ),
                final_table_count=len(
                    state.candidate_tables
                ),
                final_field_count=len(
                    state.candidate_fields
                ),
                embedding_table_count=sum(
                    item.embedding_rank is not None
                    for item in retrieval_pool.table_evidence
                ),
                embedding_field_count=sum(
                    item.embedding_rank is not None
                    for item in retrieval_pool.field_evidence
                ),
                fusion_table_count=sum(
                    item.fusion_rank is not None
                    for item in retrieval_pool.table_evidence
                ),
                fusion_field_count=sum(
                    item.fusion_rank is not None
                    for item in retrieval_pool.field_evidence
                ),
                rerank_changed_count=sum(
                    item.fusion_rank != item.rerank_rank
                    for item in retrieval_pool.rerank_evidence
                ),
                rerank_reason_codes=tuple(
                    reason
                    for reason in RerankReason
                    if any(
                        reason in item.reason_codes
                        for item
                        in retrieval_pool.rerank_evidence
                    )
                ),
                rerank_degraded=(
                    retrieval_pool.rerank_degraded
                ),
                bm25_duration_ms=(
                    retrieval_pool.bm25_duration_ms
                ),
                embedding_duration_ms=(
                    retrieval_pool.embedding_duration_ms
                ),
                rrf_duration_ms=(
                    retrieval_pool.rrf_duration_ms
                ),
                rerank_duration_ms=(
                    retrieval_pool.rerank_duration_ms
                ),
            )
            if retrieval_pool is not None
            else (
                TraceRetrieval(
                    retrieval_version_id=(
                        retrieval_failure.retrieval_version
                        .retrieval_version_id
                    ),
                    retrieval_version_contract=(
                        "retrieval-version-v1"
                    ),
                    bm25_version=(
                        retrieval_failure.retrieval_version
                        .bm25_version
                    ),
                    embedding_provider_contract_version=(
                        retrieval_failure.retrieval_version
                        .embedding_provider_contract_version
                    ),
                    embedding_provider_config_hash=(
                        retrieval_failure.retrieval_version
                        .embedding_provider_config_sha256
                    ),
                    document_version=(
                        retrieval_failure.retrieval_version
                        .document_version
                    ),
                    fusion_version=(
                        retrieval_failure.retrieval_version
                        .fusion_version
                    ),
                    rrf_k=(
                        retrieval_failure.retrieval_version.rrf_k
                    ),
                    rerank_version=(
                        retrieval_failure.retrieval_version
                        .rerank_version
                    ),
                    outcome="failed",
                    mode="hybrid",
                    failure_code=(
                        retrieval_failure.failure_code
                    ),
                    candidate_table_count=0,
                    candidate_field_count=0,
                    bm25_duration_ms=(
                        retrieval_failure.bm25_duration_ms
                    ),
                    embedding_duration_ms=(
                        retrieval_failure.embedding_duration_ms
                    ),
                )
                if retrieval_failure is not None
                else None
            )
        ),
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
        context_selections=tuple(
            TraceContextSelection(
                **observation.model_dump()
            )
            for observation
            in state.context_selection_observations
        ),
        model_routes=tuple(
            TraceModelRouting(
                call_number=observation.call_number,
                attempt_number=observation.attempt_number,
                route_id=observation.route_id,
                route_table_version=(
                    observation.route_table_version
                ),
                primary_model_config_hash=(
                    observation.primary_model_config_sha256
                ),
                model_config_hash=(
                    observation.model_config_sha256
                ),
                data_boundary_hash=(
                    observation.data_boundary_sha256
                ),
                provider_call_count=(
                    observation.provider_call_count
                ),
                fallback_used=observation.fallback_used,
                outcome=observation.outcome,
                error_code=observation.error_code,
                primary_error_code=(
                    observation.primary_error_code
                ),
                failure_stage=observation.failure_stage,
            )
            for observation
            in state.model_routing_observations
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
