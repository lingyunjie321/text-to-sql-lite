import json

import pytest
from pydantic import ValidationError

from app.connectors.errors import ErrorType
from app.workflow import FinalStatus
from evaluation import EvaluationCase
from evaluation.models import CaseEvidence


def _case_payload() -> dict[str, object]:
    return {
        "case_id": "PG-MVP-001",
        "status": "draft",
        "category": "single_table",
        "question": "List films",
        "datasource_id": "pagila",
        "dialect": "postgres",
        "allowed_tables": ["film"],
        "expected_behavior": "EXECUTE",
        "expected_final_status": "SUCCEEDED_FIRST_PASS",
        "gold_tables": ["film"],
        "gold_fields": ["film.film_id"],
        "gold_join_edges": [],
        "gold_sql": "SELECT film_id FROM film",
        "gold_result_source": "execute_gold_sql",
        "comparison_mode": "multiset",
        "order_sensitive": False,
        "numeric_tolerances": {},
        "tags": ["mvp_gate"],
        "difficulty": "simple",
    }


def test_execute_case_parses_strict_typed_contract() -> None:
    case = EvaluationCase.model_validate(_case_payload())

    assert case.case_id == "PG-MVP-001"
    assert case.expected_final_status is FinalStatus.SUCCEEDED_FIRST_PASS
    assert case.expected_error_type is None
    assert case.fixture == {}


@pytest.mark.parametrize(
    "change",
    [
        {"gold_sql": ""},
        {"gold_tables": []},
        {"gold_fields": []},
        {"gold_result_source": "not_applicable"},
        {"expected_behavior": "EXECUTE", "expected_error_type": "TIMEOUT"},
        {"datasource_id": "other"},
        {"dialect": "mysql"},
        {"unexpected": True},
    ],
)
def test_execute_case_rejects_invalid_or_extra_contract(
    change: dict[str, object],
) -> None:
    payload = {**_case_payload(), **change}

    with pytest.raises(ValidationError):
        EvaluationCase.model_validate(payload)


def test_reject_case_requires_security_contract() -> None:
    payload = {
        **_case_payload(),
        "category": "permission",
        "expected_behavior": "REJECT",
        "expected_final_status": "REJECTED_SECURITY",
        "expected_error_type": "PERMISSION_DENIED",
        "gold_sql": "",
        "gold_result_source": "not_applicable",
        "comparison_mode": "none",
        "tags": [
            "security",
            "excluded_from_executable_rate",
            "mvp_gate",
        ],
    }

    case = EvaluationCase.model_validate(payload)

    assert case.expected_final_status is FinalStatus.REJECTED_SECURITY
    assert case.expected_error_type is ErrorType.PERMISSION_DENIED


def test_reject_case_cannot_claim_gold_execution() -> None:
    payload = {
        **_case_payload(),
        "category": "permission",
        "expected_behavior": "REJECT",
        "expected_final_status": "REJECTED_SECURITY",
        "expected_error_type": "PERMISSION_DENIED",
        "gold_result_source": "not_applicable",
        "comparison_mode": "none",
        "tags": ["security", "excluded_from_executable_rate"],
    }

    with pytest.raises(ValidationError):
        EvaluationCase.model_validate(payload)


def test_fixture_values_must_be_json_values() -> None:
    payload = {
        **_case_payload(),
        "fixture": {"unsafe": object()},
    }

    with pytest.raises(ValidationError):
        EvaluationCase.model_validate(payload)


def test_case_json_never_serializes_python_enum_repr() -> None:
    rendered = json.loads(
        EvaluationCase.model_validate(_case_payload()).model_dump_json()
    )

    assert rendered["expected_final_status"] == "SUCCEEDED_FIRST_PASS"


def _passing_execute_evidence() -> dict[str, object]:
    return {
        "case_id": "PG-MVP-001",
        "evaluation_baseline_id": "0" * 64,
        "initial_status": "draft",
        "expected_behavior": "EXECUTE",
        "expected_final_status": "SUCCEEDED_FIRST_PASS",
        "actual_final_status": "SUCCEEDED_FIRST_PASS",
        "gold_validation_passed": True,
        "gold_executed": True,
        "prediction_validation_passed": True,
        "prediction_execute_count": 1,
        "comparison": {
            "passed": True,
            "code": "RESULT_MATCH",
            "message": "results match",
            "predicted_row_count": 1,
            "gold_row_count": 1,
        },
        "table_recall_passed": True,
        "field_recall_passed": True,
        "attempt_count": 1,
        "repair_count": 0,
        "trace_sha256": "a" * 64,
        "passed": True,
        "code": "EVALUATION_PASS",
    }


@pytest.mark.parametrize(
    "change",
    [
        {"comparison": None},
        {"comparison": {
            "passed": False,
            "code": "RESULT_MISMATCH",
            "message": "results differ",
            "predicted_row_count": 1,
            "gold_row_count": 2,
        }},
        {"prediction_execute_count": 0},
        {"gold_executed": False},
        {"table_recall_passed": False},
        {"field_recall_passed": False},
    ],
)
def test_passing_execute_evidence_requires_complete_proof(
    change: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        CaseEvidence.model_validate(
            {**_passing_execute_evidence(), **change}
        )


def test_passing_reject_evidence_proves_zero_execution_and_repair() -> None:
    payload = {
        **_passing_execute_evidence(),
        "expected_behavior": "REJECT",
        "expected_final_status": "REJECTED_SECURITY",
        "actual_final_status": "REJECTED_SECURITY",
        "expected_error_type": "PERMISSION_DENIED",
        "actual_error_type": "PERMISSION_DENIED",
        "gold_validation_passed": False,
        "gold_executed": False,
        "prediction_validation_passed": False,
        "prediction_execute_count": 1,
        "comparison": None,
        "table_recall_passed": False,
        "field_recall_passed": False,
        "repair_count": 1,
    }

    with pytest.raises(ValidationError):
        CaseEvidence.model_validate(payload)
