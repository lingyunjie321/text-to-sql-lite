"""SQL 生成节点：按路由选定的模型与上下文生成目标方言 SQL 或澄清请求。"""

from __future__ import annotations

import json

from app.connectors.errors import ErrorType
from app.generation import (
    CONTEXT_INPUT_BUDGET_DENOMINATOR,
    CONTEXT_INPUT_BUDGET_NUMERATOR,
    ContextSelectionError,
    GenerationContext,
    LLMMessage,
    RoutedGenerationError,
    build_generation_messages,
    estimate_message_tokens,
    generate_with_model_route,
    select_generation_context,
)
from app.generation.normalization import normalize_generation_result
from app.reflection import (
    AttemptHistory,
    RepairRegistrationStatus,
    register_repair_sql,
    start_attempt,
)
from app.schema_linking import SchemaLinkingResult
from app.workflow.models import (
    REQUEST_TIMEOUT_SECONDS,
    REPAIR_PROMPT_VERSION,
    ContextSelectionObservation,
    GenerationObservation,
    ModelRoutingObservation,
    SQLTaskState,
    WorkflowContext,
    WorkflowPublicError,
)
from app.workflow.nodes._common import (
    NodeUpdate,
    _CONTEXT_RESOURCE_ERROR,
    _DUPLICATE_ERROR,
    _MODEL_INTERNAL_ERROR,
    _attempt_history,
    _failure_update,
    _history_update,
)


def _generation_context(
    state: SQLTaskState,
    *,
    selected_field_ids: tuple[str, ...] | None = None,
) -> GenerationContext:
    assert state.normalized_question is not None
    assert state.schema_snapshot is not None
    assert state.schema_version is not None
    assert state.complexity_decision is not None
    linking = SchemaLinkingResult(
        candidate_tables=state.candidate_tables,
        candidate_fields=state.candidate_fields,
        join_paths=state.join_paths,
        schema_version=state.schema_version,
        top_k=state.complexity_decision.schema_top_k,
        retrieval_version_id=state.retrieval_version_id,
        retrieval_pool=state.schema_retrieval_pool,
    )
    return GenerationContext(
        question=state.question,
        normalized_question=state.normalized_question,
        normalized_time=state.normalized_time,
        dialect=state.dialect,
        schema_linking=linking,
        snapshot=state.schema_snapshot,
        selected_field_ids=selected_field_ids,
    )


def _generation_messages(
    state: SQLTaskState,
    *,
    selected_field_ids: tuple[str, ...] | None = None,
) -> tuple[LLMMessage, ...]:
    messages = build_generation_messages(
        _generation_context(
            state,
            selected_field_ids=selected_field_ids,
        )
    )
    if not state.sql_attempts:
        return messages
    if state.error_type is None or state.repair_strategy is None:
        raise ValueError("workflow repair context is invalid")
    payload = json.loads(messages[-1].content)
    payload["repair_context"] = {
        "attempt_number": len(state.sql_attempts),
        "sql": state.current_sql,
        "error_type": state.error_type.value,
        "strategy": state.repair_strategy.value,
    }
    return (
        *messages[:-1],
        LLMMessage(
            role="user",
            content=json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
        ),
    )


def _generate_sql(
    state: SQLTaskState,
    context: WorkflowContext,
    *,
    deadline_at: float,
) -> NodeUpdate:
    assert state.complexity_decision is not None
    call_number = len(state.model_routing_observations) + 1
    attempt_number = len(state.sql_attempts)
    route = context.model_routing.route_table.select(
        state.complexity_decision.level.value
    )
    candidate_field_count = len(state.candidate_fields)
    try:
        selection = select_generation_context(
            _generation_context(state),
            max_input_tokens=(
                route.primary.max_input_tokens
            ),
            max_output_tokens=(
                route.primary.max_output_tokens
            ),
        )
        selected_field_ids = selection.field_ids
        usable_input_tokens = selection.usable_input_tokens
        # Binary search: fields are priority-ordered, find largest
        # subset that fits within the token budget.
        required = selection.required_field_count
        low, high = required, len(selected_field_ids)
        while low <= high:
            mid = (low + high) // 2
            messages = _generation_messages(
                state,
                selected_field_ids=selected_field_ids[:mid],
            )
            estimated_tokens = estimate_message_tokens(messages)
            if estimated_tokens <= usable_input_tokens:
                low = mid + 1
            else:
                high = mid - 1
        if high < required:
            # Even the minimum required fields overflow the budget
            messages = _generation_messages(
                state,
                selected_field_ids=selected_field_ids[:required],
            )
            estimated_tokens = estimate_message_tokens(messages)
            raise ContextSelectionError(
                "CONTEXT_REQUIRED_OVERFLOW",
                candidate_field_count=(
                    candidate_field_count
                ),
                required_field_count=(
                    selection.required_field_count
                ),
                estimated_tokens=estimated_tokens,
                usable_input_tokens=usable_input_tokens,
            )
        selected_field_ids = selected_field_ids[:high]
    except ContextSelectionError as error:
        usable_input_tokens = (
            error.usable_input_tokens
            if error.usable_input_tokens is not None
            else (
                route.primary.max_input_tokens
                * CONTEXT_INPUT_BUDGET_NUMERATOR
                // CONTEXT_INPUT_BUDGET_DENOMINATOR
                - route.primary.max_output_tokens
            )
        )
        required_field_count = (
            error.required_field_count
            if error.required_field_count is not None
            else 0
        )
        estimated_tokens = (
            error.estimated_tokens
            if error.estimated_tokens is not None
            else max(0, usable_input_tokens + 1)
        )
        observed_candidate_count = (
            error.candidate_field_count
            if error.candidate_field_count is not None
            else candidate_field_count
        )
        update = _failure_update(_CONTEXT_RESOURCE_ERROR)
        update.update(
            {
                "context_selection_observations": (
                    *state.context_selection_observations,
                    ContextSelectionObservation(
                        call_number=call_number,
                        attempt_number=attempt_number,
                        candidate_field_count=(
                            observed_candidate_count
                        ),
                        required_field_count=(
                            required_field_count
                        ),
                        selected_field_count=(
                            required_field_count
                        ),
                        pruned_field_count=(
                            observed_candidate_count
                            - required_field_count
                        ),
                        estimated_tokens=estimated_tokens,
                        usable_input_tokens=(
                            usable_input_tokens
                        ),
                        outcome="required_overflow",
                    ),
                ),
                "selected_generation_field_ids": (),
                "model_routing_observations": (
                    *state.model_routing_observations,
                    ModelRoutingObservation(
                        call_number=call_number,
                        attempt_number=attempt_number,
                        route_id=route.route_id,
                        primary_model_config_sha256=(
                            route.primary.model_config_sha256
                        ),
                        model_config_sha256=(
                            route.primary.model_config_sha256
                        ),
                        data_boundary_sha256=(
                            route.primary.data_boundary_sha256
                        ),
                        provider_call_count=0,
                        fallback_used=False,
                        outcome="context_rejected",
                        error_code=(
                            "WORKFLOW_CONTEXT_REQUIRED_OVERFLOW"
                        ),
                    ),
                ),
            }
        )
        return update

    context_observation = ContextSelectionObservation(
        call_number=call_number,
        attempt_number=attempt_number,
        candidate_field_count=candidate_field_count,
        required_field_count=selection.required_field_count,
        selected_field_count=len(selected_field_ids),
        pruned_field_count=(
            candidate_field_count - len(selected_field_ids)
        ),
        estimated_tokens=estimated_tokens,
        usable_input_tokens=usable_input_tokens,
        outcome="selected",
    )

    try:
        routed = generate_with_model_route(
            runtime=context.model_routing,
            route=route,
            messages=messages,
            deadline_at=deadline_at,
            clock=context.clock,
        )
    except RoutedGenerationError as error:
        update = _failure_update(
            WorkflowPublicError(
                error_type=error.details.error_type,
                code=error.details.code,
                public_message=error.details.public_message,
            )
        )
        update.update(
            {
                "context_selection_observations": (
                    *state.context_selection_observations,
                    context_observation,
                ),
                "selected_generation_field_ids": (
                    selected_field_ids
                ),
                "model_routing_observations": (
                    *state.model_routing_observations,
                    ModelRoutingObservation(
                        call_number=call_number,
                        attempt_number=attempt_number,
                        route_id=route.route_id,
                        primary_model_config_sha256=(
                            route.primary.model_config_sha256
                        ),
                        model_config_sha256=(
                            error.target.model_config_sha256
                        ),
                        data_boundary_sha256=(
                            error.target.data_boundary_sha256
                        ),
                        provider_call_count=(
                            error.provider_call_count
                        ),
                        fallback_used=error.fallback_used,
                        outcome="failed",
                        error_code=error.details.code,
                        primary_error_code=(
                            error.primary_error_code
                        ),
                        failure_stage="provider",
                    ),
                ),
            }
        )
        return update

    try:
        result = normalize_generation_result(
            routed.result,
            snapshot=state.schema_snapshot,
        )
    except Exception:
        update = _failure_update(_MODEL_INTERNAL_ERROR)
        update.update(
            {
                "context_selection_observations": (
                    *state.context_selection_observations,
                    context_observation,
                ),
                "selected_generation_field_ids": (
                    selected_field_ids
                ),
                "model_routing_observations": (
                    *state.model_routing_observations,
                    ModelRoutingObservation(
                        call_number=call_number,
                        attempt_number=attempt_number,
                        route_id=route.route_id,
                        primary_model_config_sha256=(
                            route.primary.model_config_sha256
                        ),
                        model_config_sha256=(
                            routed.target.model_config_sha256
                        ),
                        data_boundary_sha256=(
                            routed.target.data_boundary_sha256
                        ),
                        provider_call_count=(
                            routed.provider_call_count
                        ),
                        fallback_used=routed.fallback_used,
                        outcome="failed",
                        error_code="LLM_INTERNAL_ERROR",
                        primary_error_code=(
                            routed.primary_error_code
                        ),
                        failure_stage="normalization",
                    ),
                ),
            }
        )
        return update

    update: NodeUpdate = {
        "token_usage": state.token_usage.add(
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
        ),
        "generation_observations": (
            *state.generation_observations,
            GenerationObservation(
                call_number=len(state.generation_observations) + 1,
                attempt_number=len(state.sql_attempts),
                model_config_id=result.model,
                provider_prompt_version=result.prompt_version,
                effective_prompt_version=(
                    result.prompt_version
                    if state.repair_strategy is None
                    else (
                        f"{result.prompt_version}"
                        f"+{REPAIR_PROMPT_VERSION}"
                    )
                ),
                repair_strategy=state.repair_strategy,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
            ),
        ),
        "context_selection_observations": (
            *state.context_selection_observations,
            context_observation,
        ),
        "selected_generation_field_ids": selected_field_ids,
        "model_routing_observations": (
            *state.model_routing_observations,
            ModelRoutingObservation(
                call_number=call_number,
                attempt_number=attempt_number,
                route_id=route.route_id,
                primary_model_config_sha256=(
                    route.primary.model_config_sha256
                ),
                model_config_sha256=(
                    routed.target.model_config_sha256
                ),
                data_boundary_sha256=(
                    routed.target.data_boundary_sha256
                ),
                provider_call_count=(
                    routed.provider_call_count
                ),
                fallback_used=routed.fallback_used,
                outcome="succeeded",
                primary_error_code=(
                    routed.primary_error_code
                ),
            ),
        ),
    }
    if result.output.clarification_reason is not None:
        update.update(
            {
                "error_type": ErrorType.AMBIGUOUS_SEMANTICS,
                "repair_strategy": None,
                "public_error": None,
            }
        )
        return update

    assert result.output.sql is not None
    if not state.sql_attempts:
        history = start_attempt(result.output.sql)
    else:
        registration = register_repair_sql(
            _attempt_history(state),
            result.output.sql,
        )
        if (
            registration.status
            is RepairRegistrationStatus.DUPLICATE
        ):
            update.update(_failure_update(_DUPLICATE_ERROR))
            return update
        if (
            registration.status
            is RepairRegistrationStatus.EXHAUSTED
        ):
            update.update(
                _failure_update(
                    WorkflowPublicError(
                        error_type=state.error_type
                        or ErrorType.UNKNOWN,
                        code="WORKFLOW_REPAIR_EXHAUSTED",
                        public_message=(
                            "The SQL repair budget was exhausted."
                        ),
                    )
                )
            )
            return update
        history = registration.history
    update.update(_history_update(history))
    update.update(
        {
            "error_type": None,
            "repair_strategy": None,
            "public_error": None,
        }
    )
    return update
