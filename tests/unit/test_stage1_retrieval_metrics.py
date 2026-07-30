from dataclasses import replace

import pytest
from pydantic import ValidationError

from app.workflow import QueryComplexity
from app.observability import build_trace_record
from app.schema_linking import (
    CandidateField,
    CandidateTable,
    RRFContribution,
    RerankEvidence,
    RerankReason,
    RetrievalEvidence,
    SchemaRetrievalPool,
    authorization_scope_sha256,
    retrieval_query_sha256,
)
from app.workflow import (
    Clarification,
    ComplexityDecision,
    ComplexityReason,
    ContextSelectionObservation,
    FinalStatus,
    GenerationObservation,
    ModelRoutingObservation,
    NodeTiming,
    SQLTaskState,
    TokenUsage,
)
from app.connectors.errors import ErrorType
from evaluation.models import (
    Difficulty,
    RetrievalLatencyEvidence,
    RetrievalRoutingCase,
    RetrievalRoutingCaseEvidence,
    RetrievalRoutingSuiteRole,
    RetrievalStageEvidence,
)
from evaluation.code_freeze import Stage1CalibrationFreeze
from evaluation.loader import LoadedRetrievalRoutingSuite
from evaluation.report import (
    Stage1LatencyMetric,
    Stage1RetrievalMetricBucket,
    aggregate_stage1_retrieval_metrics,
    qualify_stage1_retrieval,
)
from evaluation.runner import collect_retrieval_routing_evidence


_TABLE_STAGES = ("bm25", "embedding", "rrf", "rerank", "final")
_FIELD_STAGES = ("bm25", "embedding", "rrf", "final")
_LATENCY_STAGES = (
    "bm25",
    "embedding",
    "rrf",
    "rerank",
    "retrieval_total",
    "generation",
    "wall_clock",
)
_DATASET_FILE_SHA256 = "a" * 64
_DATASET_NORMALIZED_SHA256 = "b" * 64
_STAGE1_CONFIG_SHA256 = "c" * 64
_CONTROLLED_CODE_SHA256 = "d" * 64
_CALIBRATION_BASELINE_ID = "e" * 64


def _freeze() -> Stage1CalibrationFreeze:
    return Stage1CalibrationFreeze.model_construct(
        contract_version="stage1-calibration-freeze-v1",
        development_file_sha256=_DATASET_FILE_SHA256,
        development_normalized_sha256=(
            _DATASET_NORMALIZED_SHA256
        ),
        calibration_file_sha256="f" * 64,
        calibration_normalized_sha256="0" * 64,
        stage1_config_sha256=_STAGE1_CONFIG_SHA256,
        controlled_code_sha256=_CONTROLLED_CODE_SHA256,
        stage1_calibration_baseline_id=(
            _CALIBRATION_BASELINE_ID
        ),
    )


def _suite(
    cases: tuple[RetrievalRoutingCase, ...],
) -> LoadedRetrievalRoutingSuite:
    return LoadedRetrievalRoutingSuite(
        role=RetrievalRoutingSuiteRole.DEVELOPMENT,
        namespace="synthetic/rrdev",
        cases=cases,
        raw_sha256=_DATASET_FILE_SHA256,
        normalized_sha256=_DATASET_NORMALIZED_SHA256,
    )


def _stage(
    object_kind: str,
    stage: str,
    *,
    expected: int,
    candidates: tuple[int, int, int],
    hits: tuple[int, int, int],
) -> RetrievalStageEvidence:
    return RetrievalStageEvidence(
        object_kind=object_kind,
        stage=stage,
        expected_count=expected,
        candidate_count_at_5=candidates[0],
        candidate_count_at_10=candidates[1],
        candidate_count_at_20=candidates[2],
        hit_count_at_5=hits[0],
        hit_count_at_10=hits[1],
        hit_count_at_20=hits[2],
    )


def _case(
    *,
    case_id: str,
    suite_role: str,
    expected_complexity: Difficulty,
    observed_complexity: QueryComplexity,
    table_bm25: RetrievalStageEvidence,
    embedding_degraded: bool,
    rerank_degraded: bool,
    route_id: str,
    durations: tuple[float, float, float, float, float],
    probe_table_count: int,
    final_table_count: int,
    probe_field_count: int,
    final_field_count: int,
    candidate_field_count: int,
    pruned_field_count: int,
    input_tokens: int,
    output_tokens: int,
) -> RetrievalRoutingCaseEvidence:
    table_stages = tuple(
        table_bm25
        if stage == "bm25"
        else _stage(
            "table",
            stage,
            expected=2,
            candidates=(
                tuple(
                    min(final_table_count, k)
                    for k in (5, 10, 20)
                )
                if stage == "final"
                else (2, 2, 2)
            ),
            hits=(2, 2, 2),
        )
        for stage in _TABLE_STAGES
    )
    field_stages = tuple(
        _stage(
            "field",
            stage,
            expected=3,
            candidates=(
                tuple(
                    min(final_field_count, k)
                    for k in (5, 10, 20)
                )
                if stage == "final"
                else (3, 3, 3)
            ),
            hits=(2, 3, 3),
        )
        for stage in _FIELD_STAGES
    )
    return RetrievalRoutingCaseEvidence(
        case_id=case_id,
        suite_role=(
            RetrievalRoutingSuiteRole.DEVELOPMENT
            if suite_role == "development"
            else RetrievalRoutingSuiteRole.CALIBRATION
        ),
        dataset_file_sha256=_DATASET_FILE_SHA256,
        dataset_normalized_sha256=(
            _DATASET_NORMALIZED_SHA256
        ),
        stage1_config_sha256=_STAGE1_CONFIG_SHA256,
        controlled_code_sha256=_CONTROLLED_CODE_SHA256,
        stage1_calibration_baseline_id=(
            _CALIBRATION_BASELINE_ID
        ),
        trace_sha256="1" * 64,
        query_sha256="2" * 64,
        authorization_scope_sha256="3" * 64,
        schema_version="4" * 64,
        retrieval_version_id="5" * 64,
        expected_complexity=expected_complexity,
        observed_complexity=observed_complexity,
        route_id=route_id,
        stage_evidence=(*table_stages, *field_stages),
        probe_table_count=probe_table_count,
        final_table_count=final_table_count,
        probe_field_count=probe_field_count,
        final_field_count=final_field_count,
        embedding_degraded=embedding_degraded,
        rerank_degraded=rerank_degraded,
        expected_fields_selected=True,
        join_recall_passed=True,
        candidate_field_count=candidate_field_count,
        pruned_field_count=pruned_field_count,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        latency_evidence=tuple(
            RetrievalLatencyEvidence(
                stage=stage,
                duration_ms=duration,
            )
            for stage, duration in zip(
                _LATENCY_STAGES,
                (
                    *durations[:4],
                    sum(durations[:4]),
                    durations[4],
                    durations[4],
                ),
                strict=True,
            )
        ),
        unauthorized_hit_count=0,
    )


def test_stage1_metrics_use_exact_micro_denominators() -> None:
    simple = _case(
        case_id="RRDEV-001",
        suite_role="development",
        expected_complexity=Difficulty.SIMPLE,
        observed_complexity=QueryComplexity.SIMPLE,
        table_bm25=_stage(
            "table",
            "bm25",
            expected=2,
            candidates=(5, 7, 7),
            hits=(1, 2, 2),
        ),
        embedding_degraded=False,
        rerank_degraded=False,
        route_id="simple_route",
        durations=(1, 2, 3, 4, 20),
        probe_table_count=7,
        final_table_count=5,
        probe_field_count=9,
        final_field_count=6,
        candidate_field_count=6,
        pruned_field_count=2,
        input_tokens=100,
        output_tokens=10,
    )
    medium = _case(
        case_id="RRDEV-002",
        suite_role="development",
        expected_complexity=Difficulty.MEDIUM,
        observed_complexity=QueryComplexity.COMPLEX,
        table_bm25=_stage(
            "table",
            "bm25",
            expected=2,
            candidates=(4, 8, 8),
            hits=(2, 2, 2),
        ),
        embedding_degraded=True,
        rerank_degraded=True,
        route_id="complex_route",
        durations=(3, 6, 9, 12, 40),
        probe_table_count=8,
        final_table_count=8,
        probe_field_count=12,
        final_field_count=10,
        candidate_field_count=10,
        pruned_field_count=5,
        input_tokens=200,
        output_tokens=20,
    )

    suite_cases = (
        RetrievalRoutingCase(
            case_id="RRDEV-001",
            suite_role="development",
            namespace="synthetic/rrdev",
            question="定位第一组信号。",
            allowed_tables=("synthetic/rrdev.signal_one",),
            expected_tables=("synthetic/rrdev.signal_one",),
            expected_fields=(
                "synthetic/rrdev.signal_one.signal_key",
            ),
            expected_complexity=Difficulty.SIMPLE,
            expected_top_k=5,
        ),
        RetrievalRoutingCase(
            case_id="RRDEV-002",
            suite_role="development",
            namespace="synthetic/rrdev",
            question="连接第二组信号。",
            allowed_tables=("synthetic/rrdev.signal_two",),
            expected_tables=("synthetic/rrdev.signal_two",),
            expected_fields=(
                "synthetic/rrdev.signal_two.signal_key",
            ),
            expected_complexity=Difficulty.MEDIUM,
            expected_top_k=10,
        ),
    )
    metrics = aggregate_stage1_retrieval_metrics(
        (simple, medium),
        suite=_suite(suite_cases),
        freeze=_freeze(),
    )

    simple_bm25_at_5 = next(
        bucket
        for bucket in metrics.retrieval_buckets
        if (
            bucket.complexity is QueryComplexity.SIMPLE
            and bucket.object_kind == "table"
            and bucket.stage == "bm25"
            and bucket.k == 5
        )
    )
    medium_bm25_at_5 = next(
        bucket
        for bucket in metrics.retrieval_buckets
        if (
            bucket.complexity is QueryComplexity.MEDIUM
            and bucket.object_kind == "table"
            and bucket.stage == "bm25"
            and bucket.k == 5
        )
    )
    assert len(metrics.retrieval_buckets) == 81
    assert simple_bm25_at_5.hit_count == 1
    assert simple_bm25_at_5.expected_count == 2
    assert simple_bm25_at_5.candidate_count == 5
    assert simple_bm25_at_5.recall == pytest.approx(0.5)
    assert simple_bm25_at_5.precision == pytest.approx(0.2)
    assert simple_bm25_at_5.mean_candidates == pytest.approx(5)
    assert medium_bm25_at_5.recall == pytest.approx(1)
    assert medium_bm25_at_5.precision == pytest.approx(0.5)

    assert metrics.case_count == 2
    assert metrics.complexity_match_count == 1
    assert tuple(
        (item.complexity, item.count)
        for item in metrics.route_distribution
    ) == (
        (QueryComplexity.SIMPLE, 1),
        (QueryComplexity.MEDIUM, 0),
        (QueryComplexity.COMPLEX, 1),
    )
    assert metrics.embedding_degraded_count == 1
    assert metrics.rerank_degraded_count == 1
    assert metrics.probe_table_mean == pytest.approx(7.5)
    assert metrics.final_table_mean == pytest.approx(6.5)
    assert metrics.probe_field_mean == pytest.approx(10.5)
    assert metrics.final_field_mean == pytest.approx(8)
    assert metrics.pruned_field_count == 7
    assert metrics.candidate_field_count == 16
    assert metrics.pruning_ratio == pytest.approx(7 / 16)
    assert metrics.input_tokens == 300
    assert metrics.output_tokens == 30

    embedding_latency = next(
        item
        for item in metrics.latencies
        if item.stage == "embedding"
    )
    assert embedding_latency.p50_ms == pytest.approx(4)
    assert embedding_latency.p95_ms == pytest.approx(5.8)

    with pytest.raises(
        ValueError,
        match=r"^stage1 retrieval evidence is invalid$",
    ):
        aggregate_stage1_retrieval_metrics(
            (simple,),
            suite=_suite(suite_cases),
            freeze=_freeze(),
        )
    with pytest.raises(
        ValueError,
        match=r"^stage1 retrieval evidence is invalid$",
    ):
        aggregate_stage1_retrieval_metrics(
            (
                simple,
                medium.model_copy(
                    update={
                        "suite_role": (
                            RetrievalRoutingSuiteRole.CALIBRATION
                        )
                    }
                ),
            ),
            suite=_suite(suite_cases),
            freeze=_freeze(),
        )
    with pytest.raises(
        ValueError,
        match=r"^stage1 retrieval evidence is invalid$",
    ):
        aggregate_stage1_retrieval_metrics(
            (simple, medium),
            suite=_suite(suite_cases),
            freeze=_freeze().model_copy(
                update={"stage1_config_sha256": "9" * 64}
            ),
        )

    calibration_cases = tuple(
        RetrievalRoutingCase(
            case_id=f"RRCAL-{index:03d}",
            suite_role="calibration",
            namespace="synthetic/rrcal",
            question=f"校准保留集问题 {index}。",
            allowed_tables=(
                f"synthetic/rrcal.signal_{index}",
            ),
            expected_tables=(
                f"synthetic/rrcal.signal_{index}",
            ),
            expected_fields=(
                f"synthetic/rrcal.signal_{index}.signal_key",
            ),
            expected_complexity=expected_complexity,
            expected_top_k=(
                5
                if expected_complexity is Difficulty.SIMPLE
                else 10
            ),
        )
        for index, expected_complexity in (
            (1, Difficulty.SIMPLE),
            (2, Difficulty.MEDIUM),
        )
    )
    calibration_suite = LoadedRetrievalRoutingSuite(
        role=RetrievalRoutingSuiteRole.CALIBRATION,
        namespace="synthetic/rrcal",
        cases=calibration_cases,
        raw_sha256="f" * 64,
        normalized_sha256="0" * 64,
    )
    calibration_evidence = (
        simple.model_copy(
            update={
                "case_id": "RRCAL-001",
                "suite_role": (
                    RetrievalRoutingSuiteRole.CALIBRATION
                ),
                "dataset_file_sha256": "f" * 64,
                "dataset_normalized_sha256": "0" * 64,
            }
        ),
        medium.model_copy(
            update={
                "case_id": "RRCAL-002",
                "suite_role": (
                    RetrievalRoutingSuiteRole.CALIBRATION
                ),
                "dataset_file_sha256": "f" * 64,
                "dataset_normalized_sha256": "0" * 64,
                "observed_complexity": QueryComplexity.MEDIUM,
                "route_id": "standard_route",
                "embedding_degraded": False,
                "rerank_degraded": False,
            }
        ),
    )
    calibration_metrics = aggregate_stage1_retrieval_metrics(
        calibration_evidence,
        suite=calibration_suite,
        freeze=_freeze(),
    )
    quality_gate = qualify_stage1_retrieval(
        calibration_metrics
    )

    assert quality_gate.passed is True
    assert quality_gate.improved_bucket_count >= 1

    regressed_final = calibration_evidence[
        0
    ].stage_evidence[4].model_copy(
        update={
            "hit_count_at_5": 0,
            "hit_count_at_10": 0,
            "hit_count_at_20": 0,
        }
    )
    regressed_evidence = (
        calibration_evidence[0].model_copy(
            update={
                "stage_evidence": (
                    *calibration_evidence[0].stage_evidence[:4],
                    regressed_final,
                    *calibration_evidence[0].stage_evidence[5:],
                )
            }
        ),
        calibration_evidence[1],
    )
    with pytest.raises(
        ValueError,
        match=r"^stage1 retrieval quality gate failed$",
    ):
        qualify_stage1_retrieval(
            aggregate_stage1_retrieval_metrics(
                regressed_evidence,
                suite=calibration_suite,
                freeze=_freeze(),
            )
        )


def test_stage1_evidence_rejects_missing_or_unsafe_evidence() -> None:
    valid = _case(
        case_id="RRDEV-001",
        suite_role="development",
        expected_complexity=Difficulty.SIMPLE,
        observed_complexity=QueryComplexity.SIMPLE,
        table_bm25=_stage(
            "table",
            "bm25",
            expected=2,
            candidates=(2, 2, 2),
            hits=(2, 2, 2),
        ),
        embedding_degraded=False,
        rerank_degraded=False,
        route_id="simple_route",
        durations=(1, 1, 1, 1, 5),
        probe_table_count=2,
        final_table_count=2,
        probe_field_count=3,
        final_field_count=3,
        candidate_field_count=3,
        pruned_field_count=0,
        input_tokens=1,
        output_tokens=1,
    )

    for update in (
        {"unauthorized_hit_count": 1},
        {"stage_evidence": valid.stage_evidence[:-1]},
        {"latency_evidence": valid.latency_evidence[:-1]},
        {"final_table_count": 1},
        {
            "stage_evidence": (
                valid.stage_evidence[0],
                *valid.stage_evidence,
            )
        },
    ):
        with pytest.raises(ValidationError):
            RetrievalRoutingCaseEvidence.model_validate(
                {
                    **valid.model_dump(),
                    **update,
                }
            )


def test_stage1_persisted_metrics_reject_impossible_formulas() -> None:
    with pytest.raises(ValidationError):
        Stage1RetrievalMetricBucket(
            complexity=QueryComplexity.SIMPLE,
            object_kind="table",
            stage="bm25",
            k=5,
            case_count=1,
            hit_count=1,
            expected_count=1,
            candidate_count=1,
            recall=0,
            precision=1,
            mean_candidates=1,
        )

    with pytest.raises(ValidationError):
        Stage1LatencyMetric(
            stage="embedding",
            sample_count=1,
            p50_ms=float("inf"),
            p95_ms=float("inf"),
        )


def test_stage1_evidence_allows_wide_authorized_pool_counts() -> None:
    evidence = _case(
        case_id="RRDEV-001",
        suite_role="development",
        expected_complexity=Difficulty.SIMPLE,
        observed_complexity=QueryComplexity.SIMPLE,
        table_bm25=_stage(
            "table",
            "bm25",
            expected=2,
            candidates=(5, 10, 20),
            hits=(1, 2, 2),
        ),
        embedding_degraded=False,
        rerank_degraded=False,
        route_id="simple_route",
        durations=(1, 1, 1, 1, 5),
        probe_table_count=24,
        final_table_count=5,
        probe_field_count=96,
        final_field_count=64,
        candidate_field_count=64,
        pruned_field_count=40,
        input_tokens=1,
        output_tokens=1,
    )

    assert evidence.probe_table_count == 24
    assert evidence.probe_field_count == 96
    assert evidence.candidate_field_count == 64


def test_stage_evidence_rejects_impossible_ranks() -> None:
    with pytest.raises(ValidationError):
        RetrievalStageEvidence(
            object_kind="table",
            stage="bm25",
            expected_count=1,
            candidate_count_at_5=6,
            candidate_count_at_10=6,
            candidate_count_at_20=6,
            hit_count_at_5=1,
            hit_count_at_10=1,
            hit_count_at_20=1,
        )


def test_collect_stage1_evidence_reads_labels_only_after_terminal() -> None:
    table_id = "synthetic/rrdev.weather_beacon"
    field_id = f"{table_id}.signal_state"
    question = "定位天气信标的信号状态。"
    contributions = (
        RRFContribution(
            channel="bm25",
            rank=1,
            value=1 / 61,
        ),
        RRFContribution(
            channel="embedding",
            rank=1,
            value=1 / 61,
        ),
    )
    pool = SchemaRetrievalPool(
        query_sha256=retrieval_query_sha256(question),
        schema_version="2" * 64,
        authorization_scope_sha256=authorization_scope_sha256(
            allowed_schemas=("synthetic/rrdev",),
            allowed_tables=(table_id,),
        ),
        retrieval_version_id="4" * 64,
        retrieval_version_contract="retrieval-version-v1",
        bm25_version="bm25-v1",
        embedding_provider_contract_version=(
            "openai-compatible-embedding-v1"
        ),
        embedding_provider_config_sha256="8" * 64,
        document_version="schema-doc-v1",
        fusion_version="rrf-v1",
        rrf_k=60,
        rerank_version="schema-rerank-v2",
        mode="hybrid",
        ranked_table_ids=(table_id,),
        ranked_field_ids=(field_id,),
        table_evidence=(
            RetrievalEvidence(
                object_id=table_id,
                bm25_rank=1,
                bm25_score=1,
                embedding_rank=1,
                embedding_similarity=0.9,
                fusion_rank=1,
                fusion_score=2 / 61,
                contributions=contributions,
            ),
        ),
        field_evidence=(
            RetrievalEvidence(
                object_id=field_id,
                bm25_rank=1,
                bm25_score=1,
                embedding_rank=1,
                embedding_similarity=0.8,
                fusion_rank=1,
                fusion_score=2 / 61,
                contributions=contributions,
            ),
        ),
        reranked_table_ids=(table_id,),
        rerank_evidence=(
            RerankEvidence(
                object_id=table_id,
                fusion_rank=1,
                rerank_rank=1,
                fusion_score=2 / 61,
                direct_field_count=1,
                approved_alias_count=0,
                required_bridge=False,
                join_connected=False,
                relevant_path_edges=None,
                has_direct_evidence=True,
                reason_codes=(RerankReason.FIELD_COVERAGE,),
            ),
        ),
        bm25_duration_ms=1,
        embedding_duration_ms=2,
        rrf_duration_ms=3,
        rerank_duration_ms=4,
    )
    state = SQLTaskState(
        request_id="request",
        trace_id="trace",
        question=question,
        normalized_question=question,
        datasource_id="synthetic",
        allowed_schemas=("synthetic/rrdev",),
        allowed_tables=(table_id,),
        candidate_tables=(
            CandidateTable(
                object_id=table_id,
                schema_name="synthetic/rrdev",
                table_name="weather_beacon",
                relation_kind="table",
                comment=None,
                score=1,
                matched_tokens=("signal",),
            ),
        ),
        candidate_fields=(
            CandidateField(
                object_id=field_id,
                schema_name="synthetic/rrdev",
                table_name="weather_beacon",
                column_name="signal_state",
                formatted_type="text",
                nullable=False,
                comment=None,
                score=1,
                matched_tokens=("signal",),
            ),
        ),
        schema_version="2" * 64,
        retrieval_version_id="4" * 64,
        schema_retrieval_pool=pool,
        probe_candidate_table_count=1,
        probe_candidate_field_count=1,
        complexity_decision=ComplexityDecision(
            level=QueryComplexity.SIMPLE,
            schema_top_k=5,
            reason_codes=(ComplexityReason.DEFAULT_SIMPLE,),
        ),
        token_usage=TokenUsage(input_tokens=10, output_tokens=2),
        generation_observations=(
            GenerationObservation(
                call_number=1,
                attempt_number=0,
                model_config_id="safe-model",
                provider_prompt_version="mvp-v1",
                effective_prompt_version="mvp-v1",
                input_tokens=10,
                output_tokens=2,
            ),
        ),
        context_selection_observations=(
            ContextSelectionObservation(
                call_number=1,
                attempt_number=0,
                candidate_field_count=1,
                required_field_count=1,
                selected_field_count=1,
                pruned_field_count=0,
                estimated_tokens=10,
                usable_input_tokens=100,
                outcome="selected",
            ),
        ),
        selected_generation_field_ids=(field_id,),
        model_routing_observations=(
            ModelRoutingObservation(
                call_number=1,
                attempt_number=0,
                route_id="simple_route",
                primary_model_config_sha256="5" * 64,
                model_config_sha256="5" * 64,
                data_boundary_sha256="6" * 64,
                provider_call_count=1,
                fallback_used=False,
                outcome="succeeded",
            ),
        ),
        node_timings=(
            NodeTiming(node="schema_linking", duration_ms=8),
            NodeTiming(node="generate_sql", duration_ms=12),
        ),
        step_count=2,
        error_type=ErrorType.AMBIGUOUS_SEMANTICS,
        clarification=Clarification(
            code="AMBIGUOUS_SEMANTICS",
            question="Clarify the request.",
        ),
        final_status=FinalStatus.CLARIFICATION_REQUIRED,
    )
    case = RetrievalRoutingCase(
        case_id="RRDEV-001",
        suite_role="development",
        namespace="synthetic/rrdev",
        question=question,
        allowed_tables=(table_id,),
        expected_tables=(table_id,),
        expected_fields=(field_id,),
        expected_join_edges=(),
        expected_complexity=Difficulty.SIMPLE,
        expected_top_k=5,
    )

    trace = build_trace_record(state)
    suite = _suite((case,))
    freeze = _freeze()
    evidence = collect_retrieval_routing_evidence(
        case,
        state,
        trace,
        suite=suite,
        freeze=freeze,
        workflow_wall_clock_duration_ms=20,
    )

    assert evidence.case_id == "RRDEV-001"
    assert evidence.stage_evidence[0].hit_count_at_5 == 1
    assert evidence.stage_evidence[5].hit_count_at_5 == 1
    assert evidence.latency_evidence[0].duration_ms == 1
    assert evidence.latency_evidence[4].duration_ms == 10
    assert evidence.latency_evidence[5].duration_ms == 12
    assert evidence.latency_evidence[6].duration_ms == 20
    serialized = evidence.model_dump_json()
    assert question not in serialized
    assert table_id not in serialized
    assert field_id not in serialized

    mismatched_route = trace.model_copy(
        update={
            "model_routes": (
                trace.model_routes[0].model_copy(
                    update={"model_config_hash": "7" * 64}
                ),
            )
        }
    )
    mismatched_context = trace.model_copy(
        update={
            "context_selections": (
                trace.context_selections[0].model_copy(
                    update={"estimated_tokens": 11}
                ),
            )
        }
    )
    mismatched_retrieval = trace.model_copy(
        update={
            "retrieval": trace.retrieval.model_copy(
                update={"candidate_table_count": 0}
            )
            if trace.retrieval is not None
            else None
        }
    )
    mismatched_node = trace.model_copy(
        update={
            "nodes": (
                trace.nodes[0].model_copy(
                    update={"duration_ms": 999.0}
                ),
                *trace.nodes[1:],
            )
        }
    )
    mismatched_generation = trace.model_copy(
        update={
            "generations": (
                trace.generations[0].model_copy(
                    update={"model_config_hash": "7" * 64}
                ),
            )
        }
    )
    mismatched_rerank_reasons = trace.model_copy(
        update={
            "retrieval": trace.retrieval.model_copy(
                update={"rerank_reason_codes": ()}
            )
            if trace.retrieval is not None
            else None
        }
    )
    for mismatched_trace in (
        mismatched_route,
        mismatched_context,
        mismatched_retrieval,
        mismatched_node,
        mismatched_generation,
        mismatched_rerank_reasons,
    ):
        with pytest.raises(
            ValueError,
            match=r"^retrieval routing evidence is invalid$",
        ):
            collect_retrieval_routing_evidence(
                case,
                state,
                mismatched_trace,
                suite=suite,
                freeze=freeze,
                workflow_wall_clock_duration_ms=20,
            )

    with pytest.raises(
        ValueError,
        match=r"^retrieval routing evidence is invalid$",
    ):
        collect_retrieval_routing_evidence(
            case,
            state.model_copy(
                update={"question": f"{question} altered"}
            ),
            trace,
            suite=suite,
            freeze=freeze,
            workflow_wall_clock_duration_ms=20,
        )

    unauthorized_pool = replace(
        pool,
        table_evidence=(
            *pool.table_evidence,
            RetrievalEvidence(
                object_id="synthetic/rrdev.unauthorized_table",
                bm25_rank=None,
                bm25_score=0,
                embedding_rank=None,
                embedding_similarity=None,
                fusion_rank=None,
                fusion_score=0,
                contributions=(),
            ),
        ),
    )
    unauthorized_state = state.model_copy(
        update={"schema_retrieval_pool": unauthorized_pool}
    )
    with pytest.raises(
        ValueError,
        match=r"^retrieval routing evidence is invalid$",
    ):
        collect_retrieval_routing_evidence(
            case,
            unauthorized_state,
            build_trace_record(unauthorized_state),
            suite=suite,
            freeze=freeze,
            workflow_wall_clock_duration_ms=20,
        )
