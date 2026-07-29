"""Pagila MVP evaluation contracts."""

from evaluation.loader import (
    CASES_INITIAL_SHA256,
    CASES_STATUS_NEUTRAL_SHA256,
    LoadedCaseSuite,
    load_case_suite,
    status_neutral_sha256,
)
from evaluation.models import (
    AuditStatus,
    CaseEvaluation,
    CaseCategory,
    CaseStatus,
    ComparisonMode,
    Difficulty,
    EvaluationCase,
    ExpectedBehavior,
    GoldResultSource,
    NumericTolerance,
    ComparisonResult,
)
from evaluation.comparator import (
    compare_results,
)
from evaluation.runner import (
    case_evidence_sha256,
    evaluate_case,
    review_evidence_sha256,
)

__all__ = [
    "AuditStatus",
    "CASES_INITIAL_SHA256",
    "CASES_STATUS_NEUTRAL_SHA256",
    "CaseEvaluation",
    "CaseCategory",
    "CaseStatus",
    "ComparisonMode",
    "ComparisonResult",
    "Difficulty",
    "EvaluationCase",
    "ExpectedBehavior",
    "GoldResultSource",
    "LoadedCaseSuite",
    "NumericTolerance",
    "compare_results",
    "case_evidence_sha256",
    "evaluate_case",
    "load_case_suite",
    "review_evidence_sha256",
    "status_neutral_sha256",
]
