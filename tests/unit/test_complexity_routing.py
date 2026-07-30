import pytest

from app.schema_linking import CandidateTable, JoinEdge, JoinPath
from app.workflow import (
    ComplexityDecision,
    ComplexityReason,
    QueryComplexity,
    decide_complexity,
)


def _candidate(
    object_id: str,
    *,
    score: float,
) -> CandidateTable:
    schema_name, table_name = object_id.split(".", 1)
    return CandidateTable(
        object_id=object_id,
        schema_name=schema_name,
        table_name=table_name,
        relation_kind="table",
        comment=None,
        score=score,
        matched_tokens=(),
    )


def _join_path(*table_ids: str) -> JoinPath:
    return JoinPath(
        tables=table_ids,
        edges=tuple(
            JoinEdge(
                constraint_name=f"fk_{index}",
                source_table=source,
                source_columns=("id",),
                target_table=target,
                target_columns=("id",),
            )
            for index, (source, target) in enumerate(
                zip(table_ids, table_ids[1:]),
                start=1,
            )
        ),
    )


def test_default_question_routes_to_simple_five() -> None:
    decision = decide_complexity(
        "list film titles",
        candidate_tables=(_candidate("public.film", score=4.0),),
        join_paths=(),
        has_repair_history=False,
    )

    assert decision == ComplexityDecision(
        level=QueryComplexity.SIMPLE,
        schema_top_k=5,
        reason_codes=(ComplexityReason.DEFAULT_SIMPLE,),
    )


def test_one_medium_signal_routes_to_medium_ten() -> None:
    decision = decide_complexity(
        "average payment amount",
        candidate_tables=(_candidate("public.payment", score=3.0),),
        join_paths=(),
        has_repair_history=False,
    )

    assert decision == ComplexityDecision(
        level=QueryComplexity.MEDIUM,
        schema_top_k=10,
        reason_codes=(ComplexityReason.AGGREGATION_REQUESTED,),
    )


def test_one_time_signal_routes_to_medium_ten() -> None:
    decision = decide_complexity(
        "monthly payments",
        candidate_tables=(_candidate("public.payment", score=3.0),),
        join_paths=(),
        has_repair_history=False,
    )

    assert decision == ComplexityDecision(
        level=QueryComplexity.MEDIUM,
        schema_top_k=10,
        reason_codes=(ComplexityReason.TIME_ANALYSIS_REQUESTED,),
    )


def test_aggregation_and_time_route_to_complex_twenty() -> None:
    decision = decide_complexity(
        "monthly average payment amount",
        candidate_tables=(_candidate("public.payment", score=3.0),),
        join_paths=(),
        has_repair_history=False,
    )

    assert decision == ComplexityDecision(
        level=QueryComplexity.COMPLEX,
        schema_top_k=20,
        reason_codes=(
            ComplexityReason.AGGREGATION_REQUESTED,
            ComplexityReason.TIME_ANALYSIS_REQUESTED,
        ),
    )


@pytest.mark.parametrize(
    ("question", "reason"),
    (
        (
            "rank customers by payment",
            ComplexityReason.WINDOW_OR_RANKING_REQUESTED,
        ),
        (
            "customers without rentals",
            ComplexityReason.SUBQUERY_OR_ANTI_JOIN_REQUESTED,
        ),
    ),
)
def test_high_question_signal_routes_to_complex_twenty(
    question: str,
    reason: ComplexityReason,
) -> None:
    decision = decide_complexity(
        question,
        candidate_tables=(_candidate("public.customer", score=1.0),),
        join_paths=(),
        has_repair_history=False,
    )

    assert decision.level is QueryComplexity.COMPLEX
    assert decision.schema_top_k == 20
    assert decision.reason_codes == (reason,)


def test_two_positive_tables_without_path_route_to_medium_ten() -> None:
    decision = decide_complexity(
        "list matching records",
        candidate_tables=(
            _candidate("public.film", score=2.0),
            _candidate("public.actor", score=1.0),
        ),
        join_paths=(),
        has_repair_history=False,
    )

    assert decision == ComplexityDecision(
        level=QueryComplexity.MEDIUM,
        schema_top_k=10,
        reason_codes=(ComplexityReason.MULTIPLE_POSITIVE_TABLES,),
    )


def test_relevant_one_edge_path_adds_second_medium_signal() -> None:
    decision = decide_complexity(
        "list matching records",
        candidate_tables=(
            _candidate("public.film", score=2.0),
            _candidate("public.actor", score=1.0),
        ),
        join_paths=(_join_path("public.film", "public.actor"),),
        has_repair_history=False,
    )

    assert decision == ComplexityDecision(
        level=QueryComplexity.COMPLEX,
        schema_top_k=20,
        reason_codes=(
            ComplexityReason.MULTIPLE_POSITIVE_TABLES,
            ComplexityReason.RELEVANT_JOIN_PATH,
        ),
    )


def test_relevant_two_edge_path_is_a_high_signal() -> None:
    decision = decide_complexity(
        "list matching records",
        candidate_tables=(
            _candidate("public.film", score=2.0),
            _candidate("public.actor", score=1.0),
            _candidate("public.film_actor", score=0.0),
        ),
        join_paths=(
            _join_path(
                "public.film",
                "public.film_actor",
                "public.actor",
            ),
        ),
        has_repair_history=False,
    )

    assert decision == ComplexityDecision(
        level=QueryComplexity.COMPLEX,
        schema_top_k=20,
        reason_codes=(
            ComplexityReason.MULTIPLE_POSITIVE_TABLES,
            ComplexityReason.RELEVANT_JOIN_PATH,
            ComplexityReason.LONG_JOIN_PATH,
        ),
    )


def test_fallback_path_with_one_positive_table_is_not_relevant() -> None:
    decision = decide_complexity(
        "list film titles",
        candidate_tables=(
            _candidate("public.film", score=2.0),
            _candidate("public.actor", score=0.0),
        ),
        join_paths=(_join_path("public.film", "public.actor"),),
        has_repair_history=False,
    )

    assert decision == ComplexityDecision(
        level=QueryComplexity.SIMPLE,
        schema_top_k=5,
        reason_codes=(ComplexityReason.DEFAULT_SIMPLE,),
    )


def test_pending_first_repair_is_a_high_signal() -> None:
    decision = decide_complexity(
        "list film titles",
        candidate_tables=(_candidate("public.film", score=2.0),),
        join_paths=(),
        has_repair_history=True,
    )

    assert decision == ComplexityDecision(
        level=QueryComplexity.COMPLEX,
        schema_top_k=20,
        reason_codes=(ComplexityReason.REPAIR_HISTORY,),
    )


def test_reason_extraction_is_nfkc_casefolded_deduplicated_and_stable() -> None:
    decision = decide_complexity(
        "ＭＯＮＴＨＬＹ monthly AVERAGE average payment",
        candidate_tables=(_candidate("public.payment", score=1.0),),
        join_paths=(),
        has_repair_history=False,
    )

    assert decision.reason_codes == (
        ComplexityReason.AGGREGATION_REQUESTED,
        ComplexityReason.TIME_ANALYSIS_REQUESTED,
    )
    assert decide_complexity(
        "ＭＯＮＴＨＬＹ monthly AVERAGE average payment",
        candidate_tables=(_candidate("public.payment", score=1.0),),
        join_paths=(),
        has_repair_history=False,
    ) == decision


def test_ascii_phrases_require_token_boundaries() -> None:
    decision = decide_complexity(
        "topology counter report",
        candidate_tables=(_candidate("public.report", score=1.0),),
        join_paths=(),
        has_repair_history=False,
    )

    assert decision.reason_codes == (ComplexityReason.DEFAULT_SIMPLE,)


def test_ascii_phrases_do_not_match_next_to_unicode_letters() -> None:
    decision = decide_complexity(
        "topé counté sumé report",
        candidate_tables=(_candidate("public.report", score=1.0),),
        join_paths=(),
        has_repair_history=False,
    )

    assert decision.reason_codes == (ComplexityReason.DEFAULT_SIMPLE,)


def test_chinese_phrases_match_without_single_character_false_positive() -> None:
    complex_decision = decide_complexity(
        "每月平均付款",
        candidate_tables=(_candidate("public.payment", score=1.0),),
        join_paths=(),
        has_repair_history=False,
    )
    simple_decision = decide_complexity(
        "未来付款",
        candidate_tables=(_candidate("public.payment", score=1.0),),
        join_paths=(),
        has_repair_history=False,
    )

    assert complex_decision.reason_codes == (
        ComplexityReason.AGGREGATION_REQUESTED,
        ComplexityReason.TIME_ANALYSIS_REQUESTED,
    )
    assert simple_decision.reason_codes == (
        ComplexityReason.DEFAULT_SIMPLE,
    )


@pytest.mark.parametrize(
    ("question", "candidate_tables", "join_paths", "has_repair_history"),
    (
        (None, (), (), False),
        (" ", (), (), False),
        (
            "list films",
            (_candidate("public.film", score=float("nan")),),
            (),
            False,
        ),
        (
            "list films",
            (_candidate("public.film", score=-1.0),),
            (),
            False,
        ),
        (
            "list films",
            (
                CandidateTable(
                    object_id=1,  # type: ignore[arg-type]
                    schema_name="public",
                    table_name="film",
                    relation_kind="table",
                    comment=None,
                    score=1.0,
                    matched_tokens=(),
                ),
            ),
            (),
            False,
        ),
        (
            "list films",
            (),
            (
                JoinPath(
                    tables=(1,),  # type: ignore[arg-type]
                    edges=(),
                ),
            ),
            False,
        ),
        (
            "list films",
            (_candidate("public.film", score=1.0),),
            (
                JoinPath(
                    tables=("public.film",),
                    edges=(
                        _join_path(
                            "public.film",
                            "public.actor",
                        ).edges[0],
                    ),
                ),
            ),
            False,
        ),
        ("list films", (object(),), (), False),
        ("list films", (), (), 1),
    ),
)
def test_invalid_complexity_evidence_fails_closed(
    question: object,
    candidate_tables: tuple[object, ...],
    join_paths: tuple[JoinPath, ...],
    has_repair_history: object,
) -> None:
    with pytest.raises(ValueError, match="complexity evidence is invalid"):
        decide_complexity(
            question,  # type: ignore[arg-type]
            candidate_tables=candidate_tables,  # type: ignore[arg-type]
            join_paths=join_paths,
            has_repair_history=has_repair_history,  # type: ignore[arg-type]
        )
