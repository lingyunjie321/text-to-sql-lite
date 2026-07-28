from datetime import datetime, timezone
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from app.connectors.errors import ErrorType
from app.workflow import (
    MAX_WORKFLOW_STEPS,
    REQUEST_TIMEOUT_SECONDS,
    Clarification,
    FinalStatus,
    GenerationObservation,
    NodeTiming,
    SQLTaskState,
    TokenUsage,
    WorkflowContext,
    WorkflowPublicError,
    new_task_state,
)


def test_workflow_constants_match_mvp() -> None:
    assert MAX_WORKFLOW_STEPS == 32
    assert REQUEST_TIMEOUT_SECONDS == 120


def test_new_task_state_has_safe_defaults() -> None:
    state = new_task_state(
        request_id="req-1",
        trace_id="trace-1",
        question="列出影片",
        datasource_id="pagila",
    )

    assert isinstance(state, SQLTaskState)
    assert state.request_id == "req-1"
    assert state.trace_id == "trace-1"
    assert state.question == "列出影片"
    assert state.dialect == "postgres"
    assert state.sql_attempts == ()
    assert state.seen_sql_fingerprints == frozenset()
    assert state.repair_count == 0
    assert state.infrastructure_retry_count == 0
    assert state.token_usage == TokenUsage()
    assert state.generation_observations == ()
    assert state.node_timings == ()
    assert state.step_count == 0
    assert state.final_status is None


def test_state_forbids_extra_fields() -> None:
    with pytest.raises(ValidationError):
        SQLTaskState(
            request_id="req-1",
            trace_id="trace-1",
            question="q",
            datasource_id="pagila",
            unexpected=True,
        )


def test_state_rejects_inconsistent_attempt_counters() -> None:
    with pytest.raises(
        ValidationError, match="workflow attempt state is invalid"
    ):
        SQLTaskState(
            request_id="req-1",
            trace_id="trace-1",
            question="q",
            datasource_id="pagila",
            repair_count=1,
        )


def test_terminal_status_requires_matching_payload() -> None:
    with pytest.raises(
        ValidationError, match="workflow terminal state is invalid"
    ):
        SQLTaskState(
            request_id="req-1",
            trace_id="trace-1",
            question="q",
            datasource_id="pagila",
            final_status=FinalStatus.SUCCEEDED_FIRST_PASS,
        )

    with pytest.raises(
        ValidationError, match="workflow terminal state is invalid"
    ):
        SQLTaskState(
            request_id="req-1",
            trace_id="trace-1",
            question="q",
            datasource_id="pagila",
            final_status=FinalStatus.CLARIFICATION_REQUIRED,
        )


def test_terminal_failure_status_must_match_error_type() -> None:
    error = WorkflowPublicError(
        error_type=ErrorType.PERMISSION_DENIED,
        code="WORKFLOW_PERMISSION_DENIED",
        public_message="The request is not permitted.",
    )

    with pytest.raises(
        ValidationError,
        match="workflow terminal state is invalid",
    ):
        SQLTaskState(
            request_id="req-1",
            trace_id="trace-1",
            question="q",
            datasource_id="pagila",
            error_type=ErrorType.PERMISSION_DENIED,
            public_error=error,
            final_status=FinalStatus.FAILED_TIMEOUT,
        )


def test_observability_contracts_are_strict() -> None:
    usage = TokenUsage(input_tokens=3, output_tokens=2)
    timing = NodeTiming(
        node="generate_sql",
        duration_ms=1.25,
        attempt_number=0,
    )
    clarification = Clarification(
        code="AMBIGUOUS_SEMANTICS",
        question="请明确查询范围。",
    )
    error = WorkflowPublicError(
        error_type=ErrorType.PERMISSION_DENIED,
        code="WORKFLOW_PERMISSION_DENIED",
        public_message="The request is not permitted.",
    )
    observation = GenerationObservation(
        call_number=1,
        attempt_number=0,
        model_config_id="stub-model",
        provider_prompt_version="mvp-v1",
        effective_prompt_version="mvp-v1",
        input_tokens=3,
        output_tokens=2,
    )

    assert usage.add(input_tokens=4, output_tokens=1) == TokenUsage(
        input_tokens=7,
        output_tokens=3,
    )
    assert timing.node == "generate_sql"
    assert clarification.question == "请明确查询范围。"
    assert error.error_type is ErrorType.PERMISSION_DENIED
    assert observation.repair_strategy is None

    with pytest.raises(ValidationError):
        NodeTiming(
            node="",
            duration_ms=-1,
            attempt_number=-1,
        )
    with pytest.raises(ValidationError):
        TokenUsage(input_tokens=-1)


def test_state_requires_generation_observations_to_match_tokens() -> None:
    observation = GenerationObservation(
        call_number=1,
        attempt_number=0,
        model_config_id="stub-model",
        provider_prompt_version="mvp-v1",
        effective_prompt_version="mvp-v1",
        input_tokens=3,
        output_tokens=2,
    )

    with pytest.raises(
        ValidationError,
        match="workflow generation observation is invalid",
    ):
        SQLTaskState(
            request_id="req-1",
            trace_id="trace-1",
            question="q",
            datasource_id="pagila",
            generation_observations=(observation,),
        )


def test_workflow_context_is_strict_and_hides_dependencies() -> None:
    provider = Mock()
    connector = Mock()
    context = WorkflowContext(
        provider=provider,
        connector=connector,
        datasource_id="pagila",
        allowed_schemas=("public",),
        allowed_tables=("public.film",),
        now=datetime(2026, 7, 28, tzinfo=timezone.utc),
        clock=lambda: 10.0,
    )

    rendered = repr(context)
    assert "provider=" not in rendered
    assert "connector=" not in rendered

    with pytest.raises(ValueError, match="workflow context is invalid"):
        WorkflowContext(
            provider=provider,
            connector=connector,
            datasource_id="pagila",
            allowed_schemas=("public",),
            allowed_tables=("film",),
        )
