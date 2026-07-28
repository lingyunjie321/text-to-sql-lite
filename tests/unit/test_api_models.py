import pytest
from pydantic import ValidationError

from app.api import (
    PublicError,
    QueryRequest,
    QueryResponse,
    ResponseClarification,
    ResponseColumn,
)
from app.connectors.errors import ErrorType
from app.workflow import FinalStatus


def test_query_request_has_strict_safe_defaults() -> None:
    request = QueryRequest(question="  List films  ")

    assert request.question == "  List films  "
    assert request.datasource_id == "pagila"
    assert request.schemas == ()
    assert request.debug is False


@pytest.mark.parametrize(
    "payload",
    [
        {"question": ""},
        {"question": "   "},
        {"question": "x" * 2001},
        {"question": "q", "datasource_id": ""},
        {"question": "q", "schemas": [""]},
        {"question": "q", "debug": 1},
        {"question": "q", "unexpected": True},
    ],
)
def test_query_request_rejects_invalid_or_extra_input(
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        QueryRequest.model_validate(payload)


def test_success_response_allows_a_legal_empty_result() -> None:
    response = QueryResponse(
        request_id="req-1",
        trace_id="trace-1",
        status=FinalStatus.SUCCEEDED_FIRST_PASS,
        sql="SELECT title FROM film WHERE false",
        columns=(ResponseColumn(name="title", type_oid=1043),),
        rows=[],
        returned_row_count=0,
        attempts=1,
    )

    assert response.rows == []
    assert response.error is None
    assert response.clarification is None


def test_success_response_rejects_non_json_row_values() -> None:
    with pytest.raises(ValidationError):
        QueryResponse(
            request_id="req-1",
            trace_id="trace-1",
            status=FinalStatus.SUCCEEDED_FIRST_PASS,
            sql="SELECT 1",
            rows=[[object()]],
            returned_row_count=1,
            attempts=1,
        )


def test_clarification_and_failure_responses_are_mutually_exclusive() -> None:
    clarification = QueryResponse(
        request_id="req-1",
        trace_id="trace-1",
        status=FinalStatus.CLARIFICATION_REQUIRED,
        clarification=ResponseClarification(
            code="AMBIGUOUS_SEMANTICS",
            question="Please clarify the reporting scope.",
        ),
    )
    failure = QueryResponse(
        request_id="req-2",
        trace_id="trace-2",
        status=FinalStatus.REJECTED_SECURITY,
        error=PublicError(
            error_type=ErrorType.PERMISSION_DENIED,
            code="WORKFLOW_PERMISSION_DENIED",
            message="The request is not permitted.",
        ),
    )

    assert clarification.error is None
    assert failure.sql is None
    assert failure.columns == ()
    assert failure.rows == []


def test_response_contract_accepts_every_defined_terminal_status() -> None:
    responses = [
        QueryResponse(
            request_id="req-first",
            trace_id="trace-first",
            status=FinalStatus.SUCCEEDED_FIRST_PASS,
            sql="SELECT 1",
            rows=[[1]],
            returned_row_count=1,
            attempts=1,
        ),
        QueryResponse(
            request_id="req-repaired",
            trace_id="trace-repaired",
            status=FinalStatus.SUCCEEDED_REPAIRED,
            sql="SELECT 1",
            rows=[[1]],
            returned_row_count=1,
            attempts=2,
            repair_count=1,
        ),
        QueryResponse(
            request_id="req-clarify",
            trace_id="trace-clarify",
            status=FinalStatus.CLARIFICATION_REQUIRED,
            clarification=ResponseClarification(
                code="AMBIGUOUS_SEMANTICS",
                question="Please clarify.",
            ),
        ),
    ]
    failure_errors = {
        FinalStatus.REJECTED_SECURITY: (
            ErrorType.PERMISSION_DENIED,
            0,
        ),
        FinalStatus.FAILED_REPAIR_EXHAUSTED: (
            ErrorType.SYNTAX_ERROR,
            3,
        ),
        FinalStatus.FAILED_DUPLICATE_LOOP: (
            ErrorType.DUPLICATE_SQL,
            0,
        ),
        FinalStatus.FAILED_TIMEOUT: (ErrorType.TIMEOUT, 0),
        FinalStatus.FAILED_CONNECTION: (
            ErrorType.CONNECTION_ERROR,
            0,
        ),
        FinalStatus.FAILED_RESOURCE_RISK: (
            ErrorType.RESOURCE_RISK,
            0,
        ),
        FinalStatus.FAILED_INTERNAL: (ErrorType.UNKNOWN, 0),
    }
    responses.extend(
        QueryResponse(
            request_id=f"req-{status.value}",
            trace_id=f"trace-{status.value}",
            status=status,
            repair_count=repair_count,
            error=PublicError(
                error_type=error_type,
                code="SAFE_ERROR",
                message="The request failed.",
            ),
        )
        for status, (error_type, repair_count)
        in failure_errors.items()
    )

    assert {response.status for response in responses} == set(
        FinalStatus
    )


@pytest.mark.parametrize(
    "payload",
    [
        {
            "status": FinalStatus.SUCCEEDED_FIRST_PASS,
            "sql": None,
        },
        {
            "status": FinalStatus.CLARIFICATION_REQUIRED,
            "clarification": None,
        },
        {
            "status": FinalStatus.REJECTED_SECURITY,
            "error": None,
        },
        {
            "status": FinalStatus.FAILED_TIMEOUT,
            "error": {
                "error_type": ErrorType.PERMISSION_DENIED,
                "code": "WRONG",
                "message": "safe",
            },
        },
        {
            "status": FinalStatus.FAILED_INTERNAL,
            "error": {
                "error_type": ErrorType.PERMISSION_DENIED,
                "code": "WRONG",
                "message": "safe",
            },
        },
    ],
)
def test_response_rejects_terminal_payload_mismatches(
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        QueryResponse.model_validate(
            {
                "request_id": "req-1",
                "trace_id": "trace-1",
                **payload,
            }
        )


def test_response_models_forbid_extra_fields() -> None:
    with pytest.raises(ValidationError):
        PublicError(
            error_type=ErrorType.UNKNOWN,
            code="SAFE",
            message="safe",
            raw_driver_error="secret",
        )
