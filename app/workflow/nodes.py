from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timezone
from typing import TypeAlias

from langgraph.runtime import Runtime

from app.connectors.errors import (
    ErrorType,
    PostgreSQLConnectorError,
)
from app.execution import execute_validated_sql
from app.generation import (
    CONTEXT_INPUT_BUDGET_DENOMINATOR,
    CONTEXT_INPUT_BUDGET_NUMERATOR,
    ContextSelectionError,
    GenerationContext,
    LLMMessage,
    LLMProviderError,
    RoutedGenerationError,
    build_generation_messages,
    estimate_message_tokens,
    generate_with_model_route,
    select_generation_context,
)
from app.generation.normalization import normalize_generation_result
from app.reflection import (
    AttemptHistory,
    ReflectionRoute,
    RepairRegistrationStatus,
    RepairStrategy,
    decide_reflection,
    record_execution,
    record_validation,
    register_repair_sql,
    start_attempt,
)
from app.schema_linking import (
    EmbeddingIndexBuildError,
    EmbeddingProviderError,
    PROBE_SCHEMA_TOP_K,
    SchemaRetrievalFailure,
    SchemaLinkingResult,
    link_schema,
)
from app.validation import validate_sql
from app.workflow.complexity import decide_complexity
from app.workflow.models import (
    MAX_WORKFLOW_STEPS,
    REQUEST_TIMEOUT_SECONDS,
    REPAIR_PROMPT_VERSION,
    Clarification,
    ContextSelectionObservation,
    FinalStatus,
    GenerationObservation,
    ModelRoutingObservation,
    NodeTiming,
    SQLTaskState,
    WorkflowContext,
    WorkflowPermissionError,
    WorkflowPublicError,
)
from app.workflow.permissions import resolve_permissions
from app.workflow.preprocess import preprocess_question

NodeUpdate: TypeAlias = dict[str, object]
NodeCore: TypeAlias = Callable[
    [SQLTaskState, WorkflowContext],
    NodeUpdate,
]

_REPAIRABLE_ERRORS = frozenset(
    {
        ErrorType.SYNTAX_ERROR,
        ErrorType.SCHEMA_ERROR,
        ErrorType.DIALECT_ERROR,
    }
)
_INTERNAL_ERROR = WorkflowPublicError(
    error_type=ErrorType.UNKNOWN,
    code="WORKFLOW_INTERNAL_ERROR",
    public_message="The request could not be completed.",
)
_TIMEOUT_ERROR = WorkflowPublicError(
    error_type=ErrorType.TIMEOUT,
    code="WORKFLOW_TIMEOUT",
    public_message="The request timed out.",
)
_MODEL_INTERNAL_ERROR = WorkflowPublicError(
    error_type=ErrorType.UNKNOWN,
    code="LLM_INTERNAL_ERROR",
    public_message="The model request failed.",
)
_STEP_LIMIT_ERROR = WorkflowPublicError(
    error_type=ErrorType.UNKNOWN,
    code="WORKFLOW_STEP_LIMIT",
    public_message="The request could not be completed.",
)
_NO_SCHEMA_ERROR = WorkflowPublicError(
    error_type=ErrorType.BUSINESS_KNOWLEDGE_MISSING,
    code="WORKFLOW_SCHEMA_CLARIFICATION",
    public_message="More information is required.",
)
_DUPLICATE_ERROR = WorkflowPublicError(
    error_type=ErrorType.DUPLICATE_SQL,
    code="WORKFLOW_DUPLICATE_SQL",
    public_message="The SQL repair loop was stopped.",
)
_CONTEXT_RESOURCE_ERROR = WorkflowPublicError(
    error_type=ErrorType.RESOURCE_RISK,
    code="WORKFLOW_CONTEXT_REQUIRED_OVERFLOW",
    public_message=(
        "The required model context exceeds the safety limit."
    ),
)
_EMBEDDING_PUBLIC_ERRORS = {
    "EMBEDDING_INVALID_INPUT": WorkflowPublicError(
        error_type=ErrorType.UNKNOWN,
        code="EMBEDDING_INVALID_INPUT",
        public_message="The embedding input is invalid.",
    ),
    "EMBEDDING_TIMEOUT": WorkflowPublicError(
        error_type=ErrorType.TIMEOUT,
        code="EMBEDDING_TIMEOUT",
        public_message="The embedding request timed out.",
    ),
    "EMBEDDING_CONNECTION_ERROR": WorkflowPublicError(
        error_type=ErrorType.CONNECTION_ERROR,
        code="EMBEDDING_CONNECTION_ERROR",
        public_message="The embedding service is unavailable.",
    ),
    "EMBEDDING_HTTP_ERROR": WorkflowPublicError(
        error_type=ErrorType.UNKNOWN,
        code="EMBEDDING_HTTP_ERROR",
        public_message="The embedding request failed.",
    ),
    "EMBEDDING_RATE_LIMITED": WorkflowPublicError(
        error_type=ErrorType.UNKNOWN,
        code="EMBEDDING_RATE_LIMITED",
        public_message=(
            "The embedding service is temporarily busy."
        ),
    ),
    "EMBEDDING_INVALID_RESPONSE": WorkflowPublicError(
        error_type=ErrorType.UNKNOWN,
        code="EMBEDDING_INVALID_RESPONSE",
        public_message="The embedding response is invalid.",
    ),
}


def _failure_update(error: WorkflowPublicError) -> NodeUpdate:
    return {
        "error_type": error.error_type,
        "public_error": error,
    }


def _public_embedding_error(
    error: EmbeddingProviderError,
) -> WorkflowPublicError:
    return _EMBEDDING_PUBLIC_ERRORS.get(
        error.details.code,
        _INTERNAL_ERROR,
    )


def _attempt_history(state: SQLTaskState) -> AttemptHistory:
    return AttemptHistory(
        attempts=state.sql_attempts,  # type: ignore[arg-type]
        seen_sql_fingerprints=state.seen_sql_fingerprints,
        repair_count=state.repair_count,
    )


def _history_update(history: AttemptHistory) -> NodeUpdate:
    current = history.current_attempt
    return {
        "current_sql": current.sql,
        "sql_attempts": history.attempts,
        "seen_sql_fingerprints": history.seen_sql_fingerprints,
        "validation_result": current.validation_result,
        "execution_result": current.execution_result,
        "database_error": current.database_error,
        "repair_count": history.repair_count,
    }


def _public_database_error(
    error: PostgreSQLConnectorError,
) -> WorkflowPublicError:
    details = error.details
    return WorkflowPublicError(
        error_type=details.error_type,
        code=details.code,
        public_message=details.public_message,
    )


def _public_model_error(error: LLMProviderError) -> WorkflowPublicError:
    details = error.details
    return WorkflowPublicError(
        error_type=details.error_type,
        code=details.code,
        public_message=details.public_message,
    )


def _consume_infrastructure_retries(
    context: WorkflowContext,
) -> int:
    consume = getattr(
        context.connector,
        "_consume_retry_count",
        None,
    )
    if not callable(consume):
        return 0
    try:
        count = consume()
    except Exception:
        return 0
    return count if type(count) is int and count >= 0 else 0


def _request_preprocess(
    state: SQLTaskState,
    context: WorkflowContext,
) -> NodeUpdate:
    now = context.now or datetime.now(timezone.utc)
    try:
        result = preprocess_question(state.question, now=now)
    except ValueError:
        return _failure_update(
            WorkflowPublicError(
                error_type=ErrorType.UNKNOWN,
                code="WORKFLOW_INVALID_REQUEST",
                public_message="The request is invalid.",
            )
        )
    update: NodeUpdate = {
        "normalized_question": result.normalized_question,
        "normalized_time": result.normalized_time,
    }
    if result.requires_clarification:
        update.update(
            {
                "error_type": ErrorType.AMBIGUOUS_SEMANTICS,
                "public_error": None,
            }
        )
    return update


def _permission_resolve(
    state: SQLTaskState,
    context: WorkflowContext,
) -> NodeUpdate:
    try:
        scope = resolve_permissions(
            datasource_id=state.datasource_id,
            requested_schemas=state.requested_schemas,
            context=context,
        )
    except WorkflowPermissionError as error:
        return _failure_update(error.details)
    return {
        "allowed_schemas": scope.allowed_schemas,
        "allowed_tables": scope.allowed_tables,
        "error_type": None,
        "public_error": None,
    }


def _schema_linking(
    state: SQLTaskState,
    context: WorkflowContext,
    *,
    deadline_at: float,
    database_timeout_seconds: float,
) -> NodeUpdate:
    assert state.normalized_question is not None
    decision = state.complexity_decision
    if decision is None:
        try:
            snapshot = context.connector.read_metadata(
                state.allowed_schemas,
                state.allowed_tables,
                timeout_seconds=database_timeout_seconds,
            )
        except PostgreSQLConnectorError as error:
            update = _failure_update(_public_database_error(error))
            update["infrastructure_retry_count"] = (
                state.infrastructure_retry_count
                + _consume_infrastructure_retries(context)
            )
            return update
        retry_count = _consume_infrastructure_retries(context)
        top_k = PROBE_SCHEMA_TOP_K
    else:
        if (
            state.schema_snapshot is None
            or state.schema_version is None
        ):
            return _failure_update(_INTERNAL_ERROR)
        snapshot = state.schema_snapshot
        retry_count = 0
        top_k = decision.schema_top_k
    linking_arguments: dict[str, object] = {}
    if context.retrieval_runtime is not None:
        linking_arguments = {
            "datasource_id": context.datasource_id,
            "retrieval_runtime": context.retrieval_runtime,
            "prepared_pool": (
                state.schema_retrieval_pool
                if decision is not None
                else None
            ),
        }
    try:
        result = link_schema(
            state.normalized_question,
            allowed_schemas=state.allowed_schemas,
            allowed_tables=state.allowed_tables,
            snapshot=snapshot,
            top_k=top_k,
            deadline_at=deadline_at,
            clock=context.clock,
            **linking_arguments,  # type: ignore[arg-type]
        )
    except SchemaRetrievalFailure as error:
        cause = error.cause
        public_error = (
            _public_embedding_error(cause)
            if isinstance(cause, EmbeddingProviderError)
            else _EMBEDDING_PUBLIC_ERRORS[
                "EMBEDDING_INVALID_RESPONSE"
            ]
        )
        update = _failure_update(public_error)
        update.update(
            {
                "schema_version": snapshot.schema_version,
                "schema_snapshot": snapshot,
                "retrieval_failure": error.evidence,
            }
        )
        return update
    except EmbeddingProviderError as error:
        return _failure_update(_public_embedding_error(error))
    except EmbeddingIndexBuildError:
        return _failure_update(
            _EMBEDDING_PUBLIC_ERRORS[
                "EMBEDDING_INVALID_RESPONSE"
            ]
        )
    if (
        result.top_k != top_k
        or len(result.candidate_tables) > top_k
        or (
            decision is not None
            and result.schema_version != state.schema_version
        )
        or (
            decision is not None
            and context.retrieval_runtime is not None
            and (
                result.retrieval_version_id
                != state.retrieval_version_id
                or result.retrieval_pool
                is not state.schema_retrieval_pool
            )
        )
    ):
        return _failure_update(_INTERNAL_ERROR)
    if not result.candidate_tables:
        if state.repair_strategy is RepairStrategy.RELINK_SCHEMA:
            update = _failure_update(_INTERNAL_ERROR)
        else:
            update = _failure_update(_NO_SCHEMA_ERROR)
        update["infrastructure_retry_count"] = (
            state.infrastructure_retry_count + retry_count
        )
        return update
    update: NodeUpdate = {
        "candidate_tables": result.candidate_tables,
        "candidate_fields": result.candidate_fields,
        "join_paths": result.join_paths,
        "schema_version": result.schema_version,
        "schema_snapshot": snapshot,
        "retrieval_version_id": result.retrieval_version_id,
        "schema_retrieval_pool": result.retrieval_pool,
        "retrieval_failure": None,
        "infrastructure_retry_count": (
            state.infrastructure_retry_count + retry_count
        ),
        "public_error": None,
    }
    if decision is None:
        update.update(
            {
                "probe_candidate_table_count": len(
                    result.candidate_tables
                ),
                "probe_candidate_field_count": len(
                    result.candidate_fields
                ),
            }
        )
    return update


def _complexity_route(
    state: SQLTaskState,
    context: WorkflowContext,
) -> NodeUpdate:
    del context
    assert state.normalized_question is not None
    return {
        "complexity_decision": decide_complexity(
            state.normalized_question,
            candidate_tables=state.candidate_tables,
            join_paths=state.join_paths,
            has_repair_history=(
                (
                    bool(state.sql_attempts)
                    and state.repair_strategy is not None
                )
                or state.repair_count > 0
            ),
        ),
    }


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
        while True:
            messages = _generation_messages(
                state,
                selected_field_ids=selected_field_ids,
            )
            estimated_tokens = estimate_message_tokens(messages)
            if estimated_tokens <= usable_input_tokens:
                break
            if (
                len(selected_field_ids)
                <= selection.required_field_count
            ):
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
            selected_field_ids = selected_field_ids[:-1]
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


def _validate_sql(
    state: SQLTaskState,
    context: WorkflowContext,
) -> NodeUpdate:
    del context
    assert state.current_sql is not None
    assert state.schema_snapshot is not None
    result = validate_sql(
        state.current_sql,
        allowed_schemas=state.allowed_schemas,
        allowed_tables=state.allowed_tables,
        snapshot=state.schema_snapshot,
    )
    history = record_validation(_attempt_history(state), result)
    update = _history_update(history)
    if result.is_valid:
        update.update(
            {
                "error_type": None,
                "public_error": None,
            }
        )
        return update
    assert result.issue is not None
    update.update(
        _failure_update(
            WorkflowPublicError(
                error_type=result.issue.error_type,
                code=result.issue.code,
                public_message=result.issue.public_message,
            )
        )
    )
    return update


def _execute_sql(
    state: SQLTaskState,
    context: WorkflowContext,
    *,
    database_timeout_seconds: float,
) -> NodeUpdate:
    assert state.validation_result is not None
    assert state.schema_snapshot is not None
    outcome = execute_validated_sql(
        state.validation_result,
        allowed_schemas=state.allowed_schemas,
        allowed_tables=state.allowed_tables,
        snapshot=state.schema_snapshot,
        connector=context.connector,
        timeout_seconds=database_timeout_seconds,
    )
    retry_count = _consume_infrastructure_retries(context)
    history = record_execution(_attempt_history(state), outcome)
    update = _history_update(history)
    update["infrastructure_retry_count"] = (
        state.infrastructure_retry_count + retry_count
    )
    if outcome.is_success:
        update.update(
            {
                "error_type": None,
                "public_error": None,
            }
        )
        return update
    assert outcome.error is not None
    update.update(
        _failure_update(
            WorkflowPublicError(
                error_type=outcome.error.error_type,
                code=outcome.error.code,
                public_message=outcome.error.public_message,
            )
        )
    )
    return update


def _reflect_sql(
    state: SQLTaskState,
    context: WorkflowContext,
) -> NodeUpdate:
    del context
    if state.error_type is None:
        return _failure_update(_INTERNAL_ERROR)
    decision = decide_reflection(
        state.error_type,
        repair_count=state.repair_count,
    )
    update: NodeUpdate = {
        "repair_strategy": decision.strategy,
    }
    if decision.strategy is RepairStrategy.RELINK_SCHEMA:
        update["complexity_decision"] = None
        update["retrieval_version_id"] = None
        update["schema_retrieval_pool"] = None
        update["probe_candidate_table_count"] = None
        update["probe_candidate_field_count"] = None
        update["selected_generation_field_ids"] = ()
    if (
        decision.route is ReflectionRoute.FINALIZE
        and decision.code == "REFLECT_REPAIR_EXHAUSTED"
    ):
        update["public_error"] = WorkflowPublicError(
            error_type=state.error_type,
            code="WORKFLOW_REPAIR_EXHAUSTED",
            public_message="The SQL repair budget was exhausted.",
        )
    return update


def _clarification(
    state: SQLTaskState,
    context: WorkflowContext,
) -> NodeUpdate:
    del context
    code = (
        "AMBIGUOUS_SEMANTICS"
        if state.error_type is ErrorType.AMBIGUOUS_SEMANTICS
        else "BUSINESS_KNOWLEDGE_MISSING"
    )
    return {
        "clarification": Clarification(
            code=code,
            question=(
                "Please clarify the requested business meaning "
                "or reporting scope."
            ),
        ),
        "public_error": None,
    }


def _final_status(state: SQLTaskState) -> FinalStatus:
    if state.execution_result is not None:
        return (
            FinalStatus.SUCCEEDED_REPAIRED
            if state.repair_count
            else FinalStatus.SUCCEEDED_FIRST_PASS
        )
    if state.clarification is not None:
        return FinalStatus.CLARIFICATION_REQUIRED
    if state.error_type is ErrorType.PERMISSION_DENIED:
        return FinalStatus.REJECTED_SECURITY
    if state.error_type is ErrorType.DUPLICATE_SQL:
        return FinalStatus.FAILED_DUPLICATE_LOOP
    if state.error_type is ErrorType.TIMEOUT:
        return FinalStatus.FAILED_TIMEOUT
    if state.error_type is ErrorType.CONNECTION_ERROR:
        return FinalStatus.FAILED_CONNECTION
    if state.error_type is ErrorType.RESOURCE_RISK:
        return FinalStatus.FAILED_RESOURCE_RISK
    if (
        state.error_type in _REPAIRABLE_ERRORS
        and state.repair_count >= 3
    ):
        return FinalStatus.FAILED_REPAIR_EXHAUSTED
    return FinalStatus.FAILED_INTERNAL


def _finalize(
    state: SQLTaskState,
    context: WorkflowContext,
) -> NodeUpdate:
    del context
    status = _final_status(state)
    update: NodeUpdate = {"final_status": status}
    if status in {
        FinalStatus.SUCCEEDED_FIRST_PASS,
        FinalStatus.SUCCEEDED_REPAIRED,
        FinalStatus.CLARIFICATION_REQUIRED,
    }:
        update["public_error"] = None
    elif state.public_error is None:
        update["public_error"] = _INTERNAL_ERROR
    return update


def _catastrophic_finalize_update() -> NodeUpdate:
    return {
        "current_sql": None,
        "sql_attempts": (),
        "seen_sql_fingerprints": frozenset(),
        "validation_result": None,
        "execution_result": None,
        "database_error": None,
        "error_type": ErrorType.UNKNOWN,
        "repair_strategy": None,
        "repair_count": 0,
        "clarification": None,
        "final_status": FinalStatus.FAILED_INTERNAL,
        "public_error": _INTERNAL_ERROR,
    }


def _terminal_timeout_update(state: SQLTaskState) -> NodeUpdate:
    update = _failure_update(_TIMEOUT_ERROR)
    if state.sql_attempts and state.execution_result is not None:
        attempts = (
            *state.sql_attempts[:-1],
            replace(
                state.sql_attempts[-1],
                execution_result=None,
            ),
        )
        history = AttemptHistory(
            attempts=attempts,  # type: ignore[arg-type]
            seen_sql_fingerprints=state.seen_sql_fingerprints,
            repair_count=state.repair_count,
        )
        update.update(_history_update(history))
    update.update(
        {
            "clarification": None,
            "final_status": FinalStatus.FAILED_TIMEOUT,
        }
    )
    return update


def workflow_node(
    name: str,
    core: NodeCore,
) -> Callable[
    [SQLTaskState, Runtime[WorkflowContext]],
    NodeUpdate,
]:
    def wrapped(
        state: SQLTaskState,
        runtime: Runtime[WorkflowContext],
    ) -> NodeUpdate:
        context = runtime.context
        started = context.clock()
        workflow_started_at = (
            state.workflow_started_at
            if state.workflow_started_at is not None
            else started
        )
        try:
            deadline_exceeded = (
                started - workflow_started_at
                >= REQUEST_TIMEOUT_SECONDS
            )
            if name == "finalize" and deadline_exceeded:
                update = _terminal_timeout_update(state)
            elif (
                name != "finalize"
                and state.step_count >= MAX_WORKFLOW_STEPS - 2
            ):
                update = _failure_update(_STEP_LIMIT_ERROR)
            elif (
                name != "finalize"
                and deadline_exceeded
            ):
                update = _failure_update(_TIMEOUT_ERROR)
            else:
                if name == "schema_linking":
                    deadline_at = (
                        workflow_started_at
                        + REQUEST_TIMEOUT_SECONDS
                    )
                    update = _schema_linking(
                        state,
                        context,
                        deadline_at=deadline_at,
                        database_timeout_seconds=(
                            deadline_at - started
                        ),
                    )
                elif name == "generate_sql":
                    update = _generate_sql(
                        state,
                        context,
                        deadline_at=(
                            workflow_started_at
                            + REQUEST_TIMEOUT_SECONDS
                        ),
                    )
                elif name == "execute_sql":
                    deadline_at = (
                        workflow_started_at
                        + REQUEST_TIMEOUT_SECONDS
                    )
                    update = _execute_sql(
                        state,
                        context,
                        database_timeout_seconds=(
                            deadline_at - started
                        ),
                    )
                else:
                    update = core(state, context)
        except Exception:
            update = (
                _catastrophic_finalize_update()
                if name == "finalize"
                else _failure_update(_INTERNAL_ERROR)
            )
        finished = context.clock()
        observations = update.get(
            "generation_observations",
            state.generation_observations,
        )
        attempts = update.get("sql_attempts", state.sql_attempts)
        if (
            name == "generate_sql"
            and isinstance(observations, tuple)
            and observations
            and isinstance(
                observations[-1],
                GenerationObservation,
            )
        ):
            attempt_number = observations[-1].attempt_number
        elif isinstance(attempts, tuple) and attempts:
            attempt_number = len(attempts) - 1
        else:
            attempt_number = None
        timing = NodeTiming(
            node=name,
            duration_ms=max(0.0, (finished - started) * 1000),
            attempt_number=attempt_number,
        )
        update.update(
            {
                "workflow_started_at": workflow_started_at,
                "node_timings": (*state.node_timings, timing),
                "step_count": state.step_count + 1,
            }
        )
        return update

    wrapped.__name__ = name
    return wrapped


REQUEST_PREPROCESS_NODE = workflow_node(
    "request_preprocess",
    _request_preprocess,
)
PERMISSION_RESOLVE_NODE = workflow_node(
    "permission_resolve",
    _permission_resolve,
)
SCHEMA_LINKING_NODE = workflow_node(
    "schema_linking",
    _schema_linking,
)
COMPLEXITY_ROUTE_NODE = workflow_node(
    "complexity_route",
    _complexity_route,
)
GENERATE_SQL_NODE = workflow_node("generate_sql", _generate_sql)
VALIDATE_SQL_NODE = workflow_node("validate_sql", _validate_sql)
EXECUTE_SQL_NODE = workflow_node("execute_sql", _execute_sql)
REFLECT_SQL_NODE = workflow_node("reflect_sql", _reflect_sql)
CLARIFICATION_NODE = workflow_node(
    "clarification",
    _clarification,
)
FINALIZE_NODE = workflow_node("finalize", _finalize)
