import math
import re
import unicodedata

from app.schema_linking.models import CandidateTable, JoinEdge, JoinPath
from app.workflow.models import (
    ComplexityDecision,
    ComplexityReason,
    QueryComplexity,
)

COMPLEXITY_POLICY_VERSION = "complexity-v1"

_ASCII_PHRASES = {
    ComplexityReason.AGGREGATION_REQUESTED: (
        "count",
        "sum",
        "average",
        "total",
        "minimum",
        "maximum",
    ),
    ComplexityReason.WINDOW_OR_RANKING_REQUESTED: (
        "rank",
        "ranking",
        "top",
        "bottom",
        "running total",
        "moving average",
        "partition",
        "over",
    ),
    ComplexityReason.SUBQUERY_OR_ANTI_JOIN_REQUESTED: (
        "without",
        "never",
        "not exists",
        "except",
    ),
    ComplexityReason.TIME_ANALYSIS_REQUESTED: (
        "daily",
        "weekly",
        "monthly",
        "yearly",
        "trend",
        "growth",
    ),
}
_CJK_PHRASES = {
    ComplexityReason.AGGREGATION_REQUESTED: (
        "数量",
        "总数",
        "合计",
        "平均",
        "最小",
        "最大",
    ),
    ComplexityReason.WINDOW_OR_RANKING_REQUESTED: (
        "排名",
        "排行",
        "累计",
        "移动平均",
    ),
    ComplexityReason.SUBQUERY_OR_ANTI_JOIN_REQUESTED: (
        "没有",
        "从未",
        "不存在",
    ),
    ComplexityReason.TIME_ANALYSIS_REQUESTED: (
        "每天",
        "每周",
        "每月",
        "每年",
        "趋势",
        "同比",
        "环比",
        "增长",
    ),
}
_HIGH_REASONS = frozenset(
    {
        ComplexityReason.WINDOW_OR_RANKING_REQUESTED,
        ComplexityReason.SUBQUERY_OR_ANTI_JOIN_REQUESTED,
        ComplexityReason.LONG_JOIN_PATH,
        ComplexityReason.REPAIR_HISTORY,
    }
)
_MEDIUM_REASONS = frozenset(
    {
        ComplexityReason.AGGREGATION_REQUESTED,
        ComplexityReason.TIME_ANALYSIS_REQUESTED,
        ComplexityReason.MULTIPLE_POSITIVE_TABLES,
        ComplexityReason.RELEVANT_JOIN_PATH,
    }
)


def _contains_ascii_phrase(text: str, phrase: str) -> bool:
    return re.search(
        rf"(?<!\w){re.escape(phrase)}(?!\w)",
        text,
    ) is not None


def _normalized_question(question: str) -> str:
    return " ".join(
        unicodedata.normalize("NFKC", question).casefold().split()
    )


def _validate_evidence(
    question: str,
    candidate_tables: tuple[CandidateTable, ...],
    join_paths: tuple[JoinPath, ...],
    has_repair_history: bool,
) -> str:
    if (
        not isinstance(question, str)
        or type(candidate_tables) is not tuple
        or type(join_paths) is not tuple
        or type(has_repair_history) is not bool
    ):
        raise ValueError("complexity evidence is invalid")
    normalized = _normalized_question(question)
    if not normalized:
        raise ValueError("complexity evidence is invalid")

    candidate_ids: set[str] = set()
    for candidate in candidate_tables:
        if not isinstance(candidate, CandidateTable):
            raise ValueError("complexity evidence is invalid")
        score = candidate.score
        if (
            not isinstance(candidate.object_id, str)
            or not candidate.object_id.strip()
            or candidate.object_id in candidate_ids
            or isinstance(score, bool)
            or not isinstance(score, (int, float))
            or not math.isfinite(score)
            or score < 0
        ):
            raise ValueError("complexity evidence is invalid")
        candidate_ids.add(candidate.object_id)

    for path in join_paths:
        if (
            not isinstance(path, JoinPath)
            or type(path.tables) is not tuple
            or type(path.edges) is not tuple
            or not path.tables
            or len(path.edges) != len(path.tables) - 1
            or any(
                not isinstance(table_id, str)
                or not table_id.strip()
                for table_id in path.tables
            )
            or len(set(path.tables)) != len(path.tables)
        ):
            raise ValueError("complexity evidence is invalid")
        for index, edge in enumerate(path.edges):
            if (
                not isinstance(edge, JoinEdge)
                or not isinstance(edge.source_table, str)
                or not isinstance(edge.target_table, str)
            ):
                raise ValueError("complexity evidence is invalid")
            path_pair = {
                path.tables[index],
                path.tables[index + 1],
            }
            edge_pair = {edge.source_table, edge.target_table}
            if path_pair != edge_pair:
                raise ValueError("complexity evidence is invalid")
    return normalized


def decide_complexity(
    normalized_question: str,
    *,
    candidate_tables: tuple[CandidateTable, ...],
    join_paths: tuple[JoinPath, ...],
    has_repair_history: bool,
) -> ComplexityDecision:
    question = _validate_evidence(
        normalized_question,
        candidate_tables,
        join_paths,
        has_repair_history,
    )
    reasons: set[ComplexityReason] = set()
    for reason, phrases in _ASCII_PHRASES.items():
        if any(
            _contains_ascii_phrase(question, phrase)
            for phrase in phrases
        ):
            reasons.add(reason)
    for reason, phrases in _CJK_PHRASES.items():
        if any(phrase in question for phrase in phrases):
            reasons.add(reason)

    positive_table_ids = {
        candidate.object_id
        for candidate in candidate_tables
        if candidate.score > 0
    }
    if len(positive_table_ids) >= 2:
        reasons.add(ComplexityReason.MULTIPLE_POSITIVE_TABLES)
    for path in join_paths:
        if len(set(path.tables) & positive_table_ids) < 2:
            continue
        reasons.add(ComplexityReason.RELEVANT_JOIN_PATH)
        if len(path.edges) >= 2:
            reasons.add(ComplexityReason.LONG_JOIN_PATH)
    if has_repair_history:
        reasons.add(ComplexityReason.REPAIR_HISTORY)

    if not reasons:
        reasons.add(ComplexityReason.DEFAULT_SIMPLE)
    ordered_reasons = tuple(
        reason
        for reason in ComplexityReason
        if reason in reasons
    )
    if (
        reasons & _HIGH_REASONS
        or len(reasons & _MEDIUM_REASONS) >= 2
    ):
        level = QueryComplexity.COMPLEX
        schema_top_k = 20
    elif reasons & _MEDIUM_REASONS:
        level = QueryComplexity.MEDIUM
        schema_top_k = 10
    else:
        level = QueryComplexity.SIMPLE
        schema_top_k = 5
    return ComplexityDecision(
        level=level,
        schema_top_k=schema_top_k,
        reason_codes=ordered_reasons,
    )
