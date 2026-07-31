from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from pydantic import BaseModel

from app.connectors.errors import ErrorType
from app.connectors.metadata import SchemaSnapshot
from app.connectors.models import ExecutionResult
from app.generation import (
    GenerationResult,
    GeneratedSQL,
    LLMMessage,
    LLMProvider,
    ModelRoutingRuntime,
    ProviderRegistry,
    RegisteredProvider,
)
from app.observability import (
    TraceRecord,
    TraceSink,
    TracedWorkflowRunner,
)
from app.schema_linking import (
    RerankReason,
    RetrievalRuntime,
    authorization_scope_sha256,
    retrieval_query_sha256,
)
from app.workflow import (
    SQLTaskState,
    WorkflowContext,
    new_task_state,
    run_workflow,
)
from app.validation import validate_sql
from evaluation.comparator import compare_results
from evaluation.code_freeze import Stage1CalibrationFreeze
from evaluation.loader import LoadedRetrievalRoutingSuite
from evaluation.models import (
    CaseEvidence,
    CaseEvaluation,
    ComparisonResult,
    EvaluationCase,
    ExpectedBehavior,
    RetrievalLatencyEvidence,
    RetrievalRoutingCase,
    RetrievalRoutingCaseEvidence,
    RetrievalStageEvidence,
)

EVIDENCE_VERSION = "stage1-evidence-v1"
_FIXTURE_PROMPT_VERSION = "evaluation-fixture-v1"

_RETRIEVAL_STAGE_KS = (5, 10, 20)


class EvaluationConnector(Protocol):
    def read_metadata(
        self,
        allowed_schemas: tuple[str, ...],
        allowed_tables: tuple[str, ...],
        *,
        timeout_seconds: float | None = None,
    ) -> SchemaSnapshot: ...

    def execute(
        self,
        sql: str,
        *,
        timeout_seconds: float | None = None,
    ) -> ExecutionResult: ...


def _retrieval_evidence_dataset_hashes(
    *,
    case: RetrievalRoutingCase,
    suite: LoadedRetrievalRoutingSuite,
    freeze: Stage1CalibrationFreeze,
) -> tuple[str, str]:
    if (
        not isinstance(suite, LoadedRetrievalRoutingSuite)
        or not isinstance(freeze, Stage1CalibrationFreeze)
        or suite.role is not case.suite_role
        or suite.namespace != case.namespace
        or sum(item == case for item in suite.cases) != 1
    ):
        raise ValueError(
            "retrieval routing evidence is invalid"
        )
    if case.suite_role.value == "development":
        expected_hashes = (
            freeze.development_file_sha256,
            freeze.development_normalized_sha256,
        )
    else:
        expected_hashes = (
            freeze.calibration_file_sha256,
            freeze.calibration_normalized_sha256,
        )
    observed_hashes = (
        suite.raw_sha256,
        suite.normalized_sha256,
    )
    if observed_hashes != expected_hashes:
        raise ValueError(
            "retrieval routing evidence is invalid"
        )
    return observed_hashes


def _ordered_retrieval_ids(
    evidence: Sequence[object],
    *,
    rank_attribute: str,
) -> tuple[str, ...]:
    ranked: list[tuple[int, str]] = []
    for item in evidence:
        rank = getattr(item, rank_attribute, None)
        object_id = getattr(item, "object_id", None)
        if rank is None:
            continue
        if (
            type(rank) is not int
            or rank <= 0
            or not isinstance(object_id, str)
            or not object_id
        ):
            raise ValueError(
                "retrieval routing evidence is invalid"
            )
        ranked.append((rank, object_id))
    ranked.sort()
    if (
        tuple(rank for rank, _ in ranked)
        != tuple(range(1, len(ranked) + 1))
        or len({object_id for _, object_id in ranked})
        != len(ranked)
    ):
        raise ValueError(
            "retrieval routing evidence is invalid"
        )
    return tuple(object_id for _, object_id in ranked)


def _retrieval_stage_evidence(
    *,
    object_kind: str,
    stage: str,
    ranked_ids: tuple[str, ...],
    expected_ids: frozenset[str],
) -> RetrievalStageEvidence:
    values: dict[str, object] = {
        "object_kind": object_kind,
        "stage": stage,
        "expected_count": len(expected_ids),
    }
    for k in _RETRIEVAL_STAGE_KS:
        prefix = ranked_ids[:k]
        values[f"candidate_count_at_{k}"] = len(prefix)
        values[f"hit_count_at_{k}"] = len(
            set(prefix) & expected_ids
        )
    return RetrievalStageEvidence.model_validate(values)


def _canonical_retrieval_join_edge(
    left: str,
    right: str,
) -> tuple[str, str]:
    return tuple(sorted((left, right)))  # type: ignore[return-value]


def collect_retrieval_routing_evidence(
    case: RetrievalRoutingCase,
    state: SQLTaskState,
    trace: TraceRecord,
    *,
    suite: LoadedRetrievalRoutingSuite,
    freeze: Stage1CalibrationFreeze,
    workflow_wall_clock_duration_ms: float,
) -> RetrievalRoutingCaseEvidence:
    if (
        not isinstance(case, RetrievalRoutingCase)
        or not isinstance(state, SQLTaskState)
        or not isinstance(trace, TraceRecord)
        or type(workflow_wall_clock_duration_ms)
        not in (int, float)
        or not math.isfinite(
            float(workflow_wall_clock_duration_ms)
        )
        or workflow_wall_clock_duration_ms < 0
    ):
        raise ValueError(
            "retrieval routing evidence is invalid"
        )
    (
        dataset_file_sha256,
        dataset_normalized_sha256,
    ) = _retrieval_evidence_dataset_hashes(
        case=case,
        suite=suite,
        freeze=freeze,
    )
    pool = state.schema_retrieval_pool
    complexity = state.complexity_decision
    trace_retrieval = trace.retrieval
    trace_complexity = trace.complexity
    if (
        state.final_status is None
        or pool is None
        or complexity is None
        or trace_retrieval is None
        or trace_complexity is None
        or trace.request_id != state.request_id
        or trace.trace_id != state.trace_id
        or trace.final_status is not state.final_status
        or trace.error_type is not state.error_type
        or trace.schema_version != state.schema_version
        or state.datasource_id != "synthetic"
        or state.question != case.question
        or state.normalized_question
        != " ".join(
            unicodedata.normalize(
                "NFKC",
                case.question,
            ).split()
        )
        or state.allowed_schemas != (case.namespace,)
        or trace_retrieval.retrieval_version_id
        != pool.retrieval_version_id
        or pool.query_sha256
        != retrieval_query_sha256(state.normalized_question)
        or pool.authorization_scope_sha256
        != authorization_scope_sha256(
            allowed_schemas=(case.namespace,),
            allowed_tables=case.allowed_tables,
        )
        or trace_complexity.level is not complexity.level
        or trace_complexity.schema_top_k
        != complexity.schema_top_k
        or trace_complexity.reason_codes
        != complexity.reason_codes
        or trace_complexity.policy_version
        != complexity.policy_version
        or state.retrieval_version_id
        != pool.retrieval_version_id
        or frozenset(state.allowed_tables)
        != frozenset(case.allowed_tables)
        or len(state.context_selection_observations) != 1
        or len(state.model_routing_observations) != 1
        or len(trace.context_selections) != 1
        or len(trace.model_routes) != 1
        or trace.input_tokens != state.token_usage.input_tokens
        or trace.output_tokens != state.token_usage.output_tokens
        or state.probe_candidate_table_count is None
        or state.probe_candidate_field_count is None
    ):
        raise ValueError(
            "retrieval routing evidence is invalid"
        )

    context_observation = state.context_selection_observations[0]
    trace_context = trace.context_selections[0]
    route_observation = state.model_routing_observations[0]
    trace_route = trace.model_routes[0]
    expected_retrieval_trace = {
        "retrieval_version_contract": (
            pool.retrieval_version_contract
        ),
        "bm25_version": pool.bm25_version,
        "embedding_provider_contract_version": (
            pool.embedding_provider_contract_version
        ),
        "embedding_provider_config_hash": (
            pool.embedding_provider_config_sha256
        ),
        "document_version": pool.document_version,
        "fusion_version": pool.fusion_version,
        "rrf_k": pool.rrf_k,
        "rerank_version": pool.rerank_version,
        "mode": pool.mode,
        "embedding_degradation": pool.embedding_degradation,
        "candidate_table_count": len(pool.ranked_table_ids),
        "candidate_field_count": len(pool.ranked_field_ids),
        "probe_table_count": (
            state.probe_candidate_table_count
        ),
        "probe_field_count": (
            state.probe_candidate_field_count
        ),
        "final_table_count": len(state.candidate_tables),
        "final_field_count": len(state.candidate_fields),
        "embedding_table_count": sum(
            item.embedding_rank is not None
            for item in pool.table_evidence
        ),
        "embedding_field_count": sum(
            item.embedding_rank is not None
            for item in pool.field_evidence
        ),
        "fusion_table_count": sum(
            item.fusion_rank is not None
            for item in pool.table_evidence
        ),
        "fusion_field_count": sum(
            item.fusion_rank is not None
            for item in pool.field_evidence
        ),
        "rerank_changed_count": sum(
            item.fusion_rank != item.rerank_rank
            for item in pool.rerank_evidence
        ),
        "rerank_reason_codes": tuple(
            reason
            for reason in RerankReason
            if any(
                reason in item.reason_codes
                for item in pool.rerank_evidence
            )
        ),
        "rerank_degraded": pool.rerank_degraded,
        "bm25_duration_ms": pool.bm25_duration_ms,
        "embedding_duration_ms": pool.embedding_duration_ms,
        "rrf_duration_ms": pool.rrf_duration_ms,
        "rerank_duration_ms": pool.rerank_duration_ms,
    }
    observed_retrieval_trace = {
        key: getattr(trace_retrieval, key)
        for key in expected_retrieval_trace
    }
    expected_route_trace = (
        route_observation.call_number,
        route_observation.attempt_number,
        route_observation.route_id,
        route_observation.route_table_version,
        route_observation.primary_model_config_sha256,
        route_observation.model_config_sha256,
        route_observation.data_boundary_sha256,
        route_observation.provider_call_count,
        route_observation.fallback_used,
        route_observation.outcome,
        route_observation.error_code,
        route_observation.primary_error_code,
        route_observation.failure_stage,
    )
    observed_route_trace = (
        trace_route.call_number,
        trace_route.attempt_number,
        trace_route.route_id,
        trace_route.route_table_version,
        trace_route.primary_model_config_hash,
        trace_route.model_config_hash,
        trace_route.data_boundary_hash,
        trace_route.provider_call_count,
        trace_route.fallback_used,
        trace_route.outcome,
        trace_route.error_code,
        trace_route.primary_error_code,
        trace_route.failure_stage,
    )
    expected_generations = tuple(
        (
            item.call_number,
            item.attempt_number,
            hashlib.sha256(
                item.model_config_id.encode("utf-8")
            ).hexdigest(),
            item.provider_prompt_version,
            item.effective_prompt_version,
            item.repair_strategy,
            item.input_tokens,
            item.output_tokens,
        )
        for item in state.generation_observations
    )
    observed_generations = tuple(
        (
            item.call_number,
            item.attempt_number,
            item.model_config_hash,
            item.provider_contract_version,
            item.effective_contract_version,
            item.repair_strategy,
            item.input_tokens,
            item.output_tokens,
        )
        for item in trace.generations
    )
    expected_nodes = tuple(
        (
            item.node,
            item.duration_ms,
            item.attempt_number,
            item.route,
        )
        for item in state.node_timings
    )
    observed_nodes = tuple(
        (
            item.node,
            item.duration_ms,
            item.attempt_number,
            item.route,
        )
        for item in trace.nodes
    )
    final_table_ids = tuple(
        candidate.object_id
        for candidate in state.candidate_tables
    )
    final_field_ids = tuple(
        candidate.object_id
        for candidate in state.candidate_fields
    )
    if (
        trace_context.model_dump()
        != context_observation.model_dump()
        or observed_route_trace != expected_route_trace
        or observed_generations != expected_generations
        or observed_retrieval_trace
        != expected_retrieval_trace
        or observed_nodes != expected_nodes
        or len(state.selected_generation_field_ids)
        != context_observation.selected_field_count
        or len(final_table_ids) != len(set(final_table_ids))
        or len(final_field_ids) != len(set(final_field_ids))
        or len(final_table_ids) > complexity.schema_top_k
        or not set(final_table_ids).issubset(
            pool.reranked_table_ids
        )
        or not set(final_field_ids).issubset(
            pool.ranked_field_ids
        )
    ):
        raise ValueError(
            "retrieval routing evidence is invalid"
        )

    table_rankings = {
        "bm25": _ordered_retrieval_ids(
            pool.table_evidence,
            rank_attribute="bm25_rank",
        ),
        "embedding": _ordered_retrieval_ids(
            pool.table_evidence,
            rank_attribute="embedding_rank",
        ),
        "rrf": _ordered_retrieval_ids(
            pool.table_evidence,
            rank_attribute="fusion_rank",
        ),
        "rerank": _ordered_retrieval_ids(
            pool.rerank_evidence,
            rank_attribute="rerank_rank",
        ),
        "final": tuple(
            candidate.object_id
            for candidate in state.candidate_tables
        ),
    }
    field_rankings = {
        "bm25": _ordered_retrieval_ids(
            pool.field_evidence,
            rank_attribute="bm25_rank",
        ),
        "embedding": _ordered_retrieval_ids(
            pool.field_evidence,
            rank_attribute="embedding_rank",
        ),
        "rrf": _ordered_retrieval_ids(
            pool.field_evidence,
            rank_attribute="fusion_rank",
        ),
        "final": tuple(
            candidate.object_id
            for candidate in state.candidate_fields
        ),
    }
    all_rankings = (
        *table_rankings.values(),
        *field_rankings.values(),
    )
    if any(
        len(ranking) != len(set(ranking))
        for ranking in all_rankings
    ):
        raise ValueError(
            "retrieval routing evidence is invalid"
        )

    allowed_tables = frozenset(case.allowed_tables)
    all_table_ids = {
        *pool.ranked_table_ids,
        *pool.reranked_table_ids,
        *(
            item.object_id
            for item in pool.table_evidence
        ),
        *(
            item.object_id
            for item in pool.rerank_evidence
        ),
        *final_table_ids,
    }
    all_field_ids = {
        *pool.ranked_field_ids,
        *(
            item.object_id
            for item in pool.field_evidence
        ),
        *final_field_ids,
    }
    unauthorized_ids = {
        object_id
        for object_id in all_table_ids
        if object_id not in allowed_tables
    }
    unauthorized_ids.update(
        object_id
        for object_id in all_field_ids
        if object_id.rsplit(".", 1)[0]
        not in allowed_tables
    )
    if unauthorized_ids:
        raise ValueError(
            "retrieval routing evidence is invalid"
        )
    expected_tables = frozenset(case.expected_tables)
    expected_fields = frozenset(case.expected_fields)
    expected_join_edges = {
        _canonical_retrieval_join_edge(
            *edge.split("=", 1)
        )
        for edge in case.expected_join_edges
    }
    observed_join_edges = {
        _canonical_retrieval_join_edge(
            f"{edge.source_table}.{source}",
            f"{edge.target_table}.{target}",
        )
        for path in state.join_paths
        for edge in path.edges
        for source, target in zip(
            edge.source_columns,
            edge.target_columns,
            strict=True,
        )
    }
    return RetrievalRoutingCaseEvidence(
        case_id=case.case_id,
        suite_role=case.suite_role,
        dataset_file_sha256=dataset_file_sha256,
        dataset_normalized_sha256=(
            dataset_normalized_sha256
        ),
        stage1_config_sha256=freeze.stage1_config_sha256,
        controlled_code_sha256=(
            freeze.controlled_code_sha256
        ),
        stage1_calibration_baseline_id=(
            freeze.stage1_calibration_baseline_id
        ),
        trace_sha256=hashlib.sha256(
            trace.model_dump_json().encode("utf-8")
        ).hexdigest(),
        query_sha256=pool.query_sha256,
        authorization_scope_sha256=(
            pool.authorization_scope_sha256
        ),
        schema_version=pool.schema_version,
        retrieval_version_id=pool.retrieval_version_id,
        expected_complexity=case.expected_complexity,
        observed_complexity=complexity.level,
        route_id=route_observation.route_id,
        stage_evidence=tuple(
            _retrieval_stage_evidence(
                object_kind="table",
                stage=stage,
                ranked_ids=table_rankings[stage],
                expected_ids=expected_tables,
            )
            for stage in (
                "bm25",
                "embedding",
                "rrf",
                "rerank",
                "final",
            )
        )
        + tuple(
            _retrieval_stage_evidence(
                object_kind="field",
                stage=stage,
                ranked_ids=field_rankings[stage],
                expected_ids=expected_fields,
            )
            for stage in (
                "bm25",
                "embedding",
                "rrf",
                "final",
            )
        ),
        probe_table_count=state.probe_candidate_table_count,
        final_table_count=len(state.candidate_tables),
        probe_field_count=state.probe_candidate_field_count,
        final_field_count=len(state.candidate_fields),
        embedding_degraded=(
            pool.embedding_degradation is not None
        ),
        rerank_degraded=pool.rerank_degraded,
        expected_fields_selected=expected_fields.issubset(
            state.selected_generation_field_ids
        ),
        join_recall_passed=expected_join_edges.issubset(
            observed_join_edges
        ),
        candidate_field_count=(
            context_observation.candidate_field_count
        ),
        pruned_field_count=(
            context_observation.pruned_field_count
        ),
        input_tokens=state.token_usage.input_tokens,
        output_tokens=state.token_usage.output_tokens,
        latency_evidence=(
            RetrievalLatencyEvidence(
                stage="bm25",
                duration_ms=(
                    trace_retrieval.bm25_duration_ms
                ),
            ),
            RetrievalLatencyEvidence(
                stage="embedding",
                duration_ms=(
                    trace_retrieval.embedding_duration_ms
                ),
            ),
            RetrievalLatencyEvidence(
                stage="rrf",
                duration_ms=trace_retrieval.rrf_duration_ms,
            ),
            RetrievalLatencyEvidence(
                stage="rerank",
                duration_ms=(
                    trace_retrieval.rerank_duration_ms
                ),
            ),
            RetrievalLatencyEvidence(
                stage="retrieval_total",
                duration_ms=sum(
                    (
                        trace_retrieval.bm25_duration_ms,
                        trace_retrieval.embedding_duration_ms,
                        trace_retrieval.rrf_duration_ms,
                        trace_retrieval.rerank_duration_ms,
                    )
                ),
            ),
            RetrievalLatencyEvidence(
                stage="generation",
                duration_ms=sum(
                    node.duration_ms
                    for node in trace.nodes
                    if node.node == "generate_sql"
                ),
            ),
            RetrievalLatencyEvidence(
                stage="wall_clock",
                duration_ms=float(
                    workflow_wall_clock_duration_ms
                ),
            ),
        ),
        unauthorized_hit_count=len(unauthorized_ids),
    )


@dataclass(slots=True)
class _CountingConnector:
    connector: EvaluationConnector
    execute_count: int = 0
    metadata_snapshot: SchemaSnapshot | None = None

    def read_metadata(
        self,
        allowed_schemas: tuple[str, ...],
        allowed_tables: tuple[str, ...],
        *,
        timeout_seconds: float | None = None,
    ) -> SchemaSnapshot:
        if self.metadata_snapshot is not None:
            return self.metadata_snapshot
        self.metadata_snapshot = (
            self.connector.read_metadata(
                allowed_schemas,
                allowed_tables,
            )
            if timeout_seconds is None
            else self.connector.read_metadata(
                allowed_schemas,
                allowed_tables,
                timeout_seconds=timeout_seconds,
            )
        )
        return self.metadata_snapshot

    def execute(
        self,
        sql: str,
        *,
        timeout_seconds: float | None = None,
    ) -> ExecutionResult:
        self.execute_count += 1
        return (
            self.connector.execute(sql)
            if timeout_seconds is None
            else self.connector.execute(
                sql,
                timeout_seconds=timeout_seconds,
            )
        )

    def _consume_retry_count(self) -> int:
        consume = getattr(
            self.connector,
            "_consume_retry_count",
            None,
        )
        if not callable(consume):
            return 0
        count = consume()
        return count if type(count) is int and count >= 0 else 0


class _CaseProvider:
    def __init__(
        self,
        case: EvaluationCase,
        delegate: LLMProvider,
        call_state: list[int],
    ) -> None:
        self._case = case
        self._delegate = delegate
        self._call_state = call_state

    def _fixture_sql(self) -> str | None:
        fixture_key = None
        if self._case.category.value == "dangerous_sql":
            fixture_key = "model_sql"
        elif self._case.category.value == "permission":
            unauthorized_tables = tuple(
                table
                for table in self._case.gold_tables
                if table not in self._case.allowed_tables
            )
            if (
                len(unauthorized_tables) == 1
                and re.fullmatch(
                    r"[a-z_][a-z0-9_]*",
                    unauthorized_tables[0],
                )
            ):
                return (
                    f'SELECT 1 FROM "{unauthorized_tables[0]}"'
                )
        elif (
            self._case.category.value == "reflection"
            and self._call_state[0] == 0
        ):
            fixture_key = "initial_model_sql"
        value = (
            self._case.fixture.get(fixture_key)
            if fixture_key is not None
            else None
        )
        return value if isinstance(value, str) and value.strip() else None

    def generate(
        self,
        messages: Sequence[LLMMessage],
        *,
        timeout_seconds: float | None = None,
    ) -> GenerationResult:
        fixture_sql = self._fixture_sql()
        self._call_state[0] += 1
        if fixture_sql is None:
            return self._delegate.generate(
                messages,
                timeout_seconds=timeout_seconds,
            )
        return GenerationResult(
            output=GeneratedSQL(sql=fixture_sql),
            input_tokens=0,
            output_tokens=0,
            model="evaluation-fixture",
            prompt_version=_FIXTURE_PROMPT_VERSION,
        )


def _case_model_routing(
    case: EvaluationCase,
    runtime: ModelRoutingRuntime,
) -> ModelRoutingRuntime:
    call_state = [0]
    providers = {
        provider_key: RegisteredProvider(
            provider=_CaseProvider(
                case,
                registration.provider,
                call_state,
            ),
            model_config_sha256=(
                registration.model_config_sha256
            ),
            timeout_seconds=registration.timeout_seconds,
            output_contract_version=(
                registration.output_contract_version
            ),
        )
        for provider_key in sorted(
            runtime.provider_registry.provider_keys
        )
        for registration in (
            runtime.provider_registry.resolve(provider_key),
        )
    }
    return ModelRoutingRuntime(
        provider_registry=ProviderRegistry(providers),
        route_table=runtime.route_table,
    )


class _EvidenceSink:
    def __init__(self, delegate: TraceSink) -> None:
        self._delegate = delegate
        self.record: TraceRecord | None = None
        self.sha256: str | None = None

    def emit(self, record: TraceRecord) -> None:
        self._delegate.emit(record)
        payload = record.model_dump_json().encode("utf-8")
        self.record = record
        self.sha256 = hashlib.sha256(payload).hexdigest()


def _qualified_tables(case: EvaluationCase) -> tuple[str, ...]:
    return tuple(
        sorted(f"public.{table}" for table in case.allowed_tables)
    )


def _gold_table_reference(value: str) -> str:
    return value.removeprefix("public.")


def _gold_field_reference(value: str) -> str:
    return value.removeprefix("public.")


def _canonical(value: object) -> object:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {
            str(key): _canonical(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    return value


def case_evidence_sha256(
    evidence: CaseEvaluation | dict[str, object],
) -> str:
    if isinstance(evidence, CaseEvaluation):
        source: object = evidence.model_dump(
            exclude={
                "evidence_sha256",
                "audit_status",
                "review_evidence_sha256",
            }
        )
    else:
        source = evidence
    fields = CaseEvidence.model_validate(source).model_dump(mode="json")
    payload = json.dumps(
        _canonical(fields),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(
        EVIDENCE_VERSION.encode("ascii") + b"\0" + payload
    ).hexdigest()


def review_evidence_sha256(evidence_sha256: str) -> str:
    if re.fullmatch(r"[0-9a-f]{64}", evidence_sha256) is None:
        raise ValueError("evaluation evidence digest is invalid")
    return hashlib.sha256(
        b"stage1-review-v1\0" + evidence_sha256.encode("ascii")
    ).hexdigest()


def _evaluation(
    case: EvaluationCase,
    *,
    evaluation_baseline_id: str,
    code: str,
    actual_state: SQLTaskState | None = None,
    gold_validation_passed: bool = False,
    gold_executed: bool = False,
    prediction_execute_count: int = 0,
    comparison: ComparisonResult | None = None,
    table_recall_passed: bool = False,
    field_recall_passed: bool = False,
    join_recall_passed: bool = False,
    trace_sha256: str | None = None,
) -> CaseEvaluation:
    execution = (
        actual_state.execution_result
        if actual_state is not None
        else None
    )
    fields: dict[str, object] = {
        "case_id": case.case_id,
        "evaluation_baseline_id": evaluation_baseline_id,
        "initial_status": case.status,
        "expected_behavior": case.expected_behavior,
        "expected_final_status": case.expected_final_status,
        "actual_final_status": (
            actual_state.final_status
            if actual_state is not None
            else None
        ),
        "expected_error_type": case.expected_error_type,
        "actual_error_type": (
            actual_state.error_type
            if actual_state is not None
            else None
        ),
        "gold_validation_passed": gold_validation_passed,
        "gold_executed": gold_executed,
        "prediction_validation_passed": (
            actual_state is not None
            and actual_state.validation_result is not None
            and actual_state.validation_result.is_valid
        ),
        "prediction_execute_count": prediction_execute_count,
        "comparison": comparison,
        "table_recall_passed": table_recall_passed,
        "field_recall_passed": field_recall_passed,
        "join_recall_passed": join_recall_passed,
        "attempt_count": (
            len(actual_state.sql_attempts)
            if actual_state is not None
            else 0
        ),
        "repair_count": (
            actual_state.repair_count
            if actual_state is not None
            else 0
        ),
        "trace_sha256": trace_sha256,
        "input_tokens": (
            actual_state.token_usage.input_tokens
            if actual_state is not None
            else 0
        ),
        "output_tokens": (
            actual_state.token_usage.output_tokens
            if actual_state is not None
            else 0
        ),
        "workflow_duration_ms": (
            sum(
                timing.duration_ms
                for timing in actual_state.node_timings
            )
            if actual_state is not None
            else 0
        ),
        "database_duration_ms": (
            execution.execution_time_ms
            if execution is not None
            else 0
        ),
        "passed": code == "EVALUATION_PASS",
        "code": code,
    }
    return CaseEvaluation(
        **fields,
        evidence_sha256=case_evidence_sha256(fields),
    )


def _normalized_join_edge(edge: str) -> tuple[str, str] | None:
    if edge.count("=") != 1:
        return None
    left, right = edge.split("=", 1)

    def normalize(value: str) -> str:
        stripped = value.strip()
        return (
            stripped.removeprefix("public.")
            if stripped.count(".") >= 2
            else stripped
        )

    left = normalize(left)
    right = normalize(right)
    if not left or not right:
        return None
    return tuple(sorted((left, right)))  # type: ignore[return-value]


def _join_recall(state: SQLTaskState, case: EvaluationCase) -> bool:
    expected = {
        normalized
        for edge in case.gold_join_edges
        if (normalized := _normalized_join_edge(edge)) is not None
    }
    observed: set[tuple[str, str]] = set()
    for path in state.join_paths:
        for edge in path.edges:
            for source, target in zip(
                edge.source_columns,
                edge.target_columns,
                strict=True,
            ):
                normalized = _normalized_join_edge(
                    f"{edge.source_table}.{source}="
                    f"{edge.target_table}.{target}"
                )
                if normalized is not None:
                    observed.add(normalized)
    return expected <= observed


def _result_code(
    case: EvaluationCase,
    state: SQLTaskState,
    *,
    gold_validation_passed: bool,
    gold_executed: bool,
    prediction_execute_count: int,
    comparison: ComparisonResult | None,
    table_recall_passed: bool,
    field_recall_passed: bool,
    trace_sha256: str | None,
) -> str:
    if trace_sha256 is None:
        return "EVALUATION_TRACE_MISSING"
    if state.final_status is not case.expected_final_status:
        return "EVALUATION_FINAL_STATUS_MISMATCH"
    if state.error_type is not case.expected_error_type:
        return "EVALUATION_ERROR_TYPE_MISMATCH"
    if case.expected_behavior is ExpectedBehavior.EXECUTE:
        if not gold_validation_passed:
            return "EVALUATION_GOLD_VALIDATION_FAILED"
        if not gold_executed:
            return "EVALUATION_GOLD_EXECUTION_FAILED"
        if not table_recall_passed:
            return "EVALUATION_TABLE_RECALL_FAILED"
        if not field_recall_passed:
            return "EVALUATION_FIELD_RECALL_FAILED"
        if (
            state.validation_result is None
            or not state.validation_result.is_valid
        ):
            return "EVALUATION_PREDICTION_VALIDATION_FAILED"
        expected_execute_count = sum(
            attempt.execution_result is not None
            or attempt.database_error is not None
            for attempt in state.sql_attempts
        )
        if (
            state.execution_result is None
            or prediction_execute_count != expected_execute_count
        ):
            return "EVALUATION_PREDICTION_EXECUTION_FAILED"
        if comparison is None:
            return "EVALUATION_COMPARISON_MISSING"
        if not comparison.passed:
            return comparison.code
    elif prediction_execute_count != 0:
        return "EVALUATION_SECURITY_EXECUTION_OCCURRED"
    elif (
        case.expected_behavior is ExpectedBehavior.REJECT
        and state.repair_count != 0
    ):
        return "EVALUATION_SECURITY_REPAIR_OCCURRED"
    return "EVALUATION_PASS"


def _evaluate_case_in_snapshot(
    case: EvaluationCase,
    *,
    evaluation_baseline_id: str,
    connector: EvaluationConnector,
    model_routing: ModelRoutingRuntime,
    retrieval_runtime: RetrievalRuntime | None,
    trace_sink: TraceSink,
) -> CaseEvaluation:
    allowed_tables = _qualified_tables(case)
    gold_validation_passed = False
    gold_executed = False
    gold_result: ExecutionResult | None = None
    shared_snapshot: SchemaSnapshot | None = None
    try:
        if case.expected_behavior is ExpectedBehavior.EXECUTE:
            shared_snapshot = connector.read_metadata(
                ("public",),
                allowed_tables,
            )
            validation = validate_sql(
                case.gold_sql,
                allowed_schemas=("public",),
                allowed_tables=allowed_tables,
                snapshot=shared_snapshot,
            )
            gold_validation_passed = validation.is_valid
            if not validation.is_valid or validation.normalized_sql is None:
                return _evaluation(
                    case,
                    evaluation_baseline_id=evaluation_baseline_id,
                    code="EVALUATION_GOLD_VALIDATION_FAILED",
                )
            gold_result = connector.execute(validation.normalized_sql)
            gold_executed = True
    except Exception:
        return _evaluation(
            case,
            evaluation_baseline_id=evaluation_baseline_id,
            code="EVALUATION_GOLD_EXECUTION_FAILED",
            gold_validation_passed=gold_validation_passed,
        )

    counted = _CountingConnector(
        connector,
        metadata_snapshot=shared_snapshot,
    )
    evidence_sink = _EvidenceSink(trace_sink)
    case_model_routing = _case_model_routing(
        case,
        model_routing,
    )
    state = new_task_state(
        request_id=f"evaluation-{case.case_id.casefold()}",
        trace_id=f"trace-{case.case_id.casefold()}",
        question=case.question,
        datasource_id=case.datasource_id,
        requested_schemas=("public",),
    )
    try:
        terminal = TracedWorkflowRunner(
            run_workflow,
            evidence_sink,
        )(
            state,
            context=WorkflowContext(
                connector=counted,
                model_routing=case_model_routing,
                retrieval_runtime=retrieval_runtime,
                datasource_id="pagila",
                allowed_schemas=("public",),
                allowed_tables=allowed_tables,
            ),
        )
    except Exception:
        return _evaluation(
            case,
            evaluation_baseline_id=evaluation_baseline_id,
            code="EVALUATION_INTERNAL_ERROR",
            gold_validation_passed=gold_validation_passed,
            gold_executed=gold_executed,
            prediction_execute_count=counted.execute_count,
        )

    linked_tables = {
        table.table_name
        for table in terminal.candidate_tables
    }
    linked_fields = {
        f"{field.table_name}.{field.column_name}"
        for field in terminal.candidate_fields
    }
    final_validation = terminal.validation_result
    referenced_tables = (
        {
            _gold_table_reference(table)
            for table in final_validation.referenced_tables
        }
        if final_validation is not None
        else set()
    )
    referenced_fields = (
        {
            _gold_field_reference(field)
            for field in final_validation.referenced_columns
        }
        if final_validation is not None
        else set()
    )
    required_tables = set(case.gold_tables)
    required_fields = set(case.gold_fields)
    table_recall_passed = (
        required_tables <= linked_tables
        and required_tables <= referenced_tables
    )
    field_recall_passed = (
        required_fields <= linked_fields
        and required_fields <= referenced_fields
    )
    join_recall_passed = _join_recall(terminal, case)
    comparison = None
    if (
        case.expected_behavior is ExpectedBehavior.EXECUTE
        and terminal.execution_result is not None
        and gold_result is not None
    ):
        comparison = compare_results(
            terminal.execution_result,
            gold_result,
            mode=case.comparison_mode,
            order_sensitive=case.order_sensitive,
            numeric_tolerances=case.numeric_tolerances,
        )
    code = _result_code(
        case,
        terminal,
        gold_validation_passed=gold_validation_passed,
        gold_executed=gold_executed,
        prediction_execute_count=counted.execute_count,
        comparison=comparison,
        table_recall_passed=table_recall_passed,
        field_recall_passed=field_recall_passed,
        trace_sha256=evidence_sink.sha256,
    )
    return _evaluation(
        case,
        evaluation_baseline_id=evaluation_baseline_id,
        code=code,
        actual_state=terminal,
        gold_validation_passed=gold_validation_passed,
        gold_executed=gold_executed,
        prediction_execute_count=counted.execute_count,
        comparison=comparison,
        table_recall_passed=table_recall_passed,
        field_recall_passed=field_recall_passed,
        join_recall_passed=join_recall_passed,
        trace_sha256=evidence_sink.sha256,
    )


def evaluate_case(
    case: EvaluationCase,
    *,
    evaluation_baseline_id: str = "0" * 64,
    connector: EvaluationConnector,
    model_routing: ModelRoutingRuntime,
    retrieval_runtime: RetrievalRuntime | None = None,
    trace_sink: TraceSink,
) -> CaseEvaluation:
    snapshot_factory = getattr(
        connector,
        "read_only_snapshot",
        None,
    )
    if callable(snapshot_factory):
        with snapshot_factory() as snapshot_connector:
            return _evaluate_case_in_snapshot(
                case,
                evaluation_baseline_id=evaluation_baseline_id,
                connector=snapshot_connector,
                model_routing=model_routing,
                retrieval_runtime=retrieval_runtime,
                trace_sink=trace_sink,
            )
    return _evaluate_case_in_snapshot(
        case,
        evaluation_baseline_id=evaluation_baseline_id,
        connector=connector,
        model_routing=model_routing,
        retrieval_runtime=retrieval_runtime,
        trace_sink=trace_sink,
    )
