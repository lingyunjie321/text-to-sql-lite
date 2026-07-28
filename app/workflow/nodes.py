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
    GenerationContext,
    LLMMessage,
    LLMProviderError,
    build_generation_messages,
)
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
from app.schema_linking import SchemaLinkingResult, link_schema
from app.validation import validate_sql
from app.workflow.models import (
    MAX_WORKFLOW_STEPS,
    REQUEST_TIMEOUT_SECONDS,
    REPAIR_PROMPT_VERSION,
    Clarification,
    FinalStatus,
    GenerationObservation,
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


def _failure_update(error: WorkflowPublicError) -> NodeUpdate:
    return {
        "error_type": error.error_type,
        "public_error": error,
    }


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
) -> NodeUpdate:
    assert state.normalized_question is not None
    try:
        snapshot = context.connector.read_metadata(
            state.allowed_schemas,
            state.allowed_tables,
        )
    except PostgreSQLConnectorError as error:
        update = _failure_update(_public_database_error(error))
        update["infrastructure_retry_count"] = (
            state.infrastructure_retry_count
            + _consume_infrastructure_retries(context)
        )
        return update
    retry_count = _consume_infrastructure_retries(context)
    result = link_schema(
        state.normalized_question,
        allowed_schemas=state.allowed_schemas,
        allowed_tables=state.allowed_tables,
        snapshot=snapshot,
    )
    if not result.candidate_tables:
        if state.repair_strategy is RepairStrategy.RELINK_SCHEMA:
            update = _failure_update(_INTERNAL_ERROR)
        else:
            update = _failure_update(_NO_SCHEMA_ERROR)
        update["infrastructure_retry_count"] = (
            state.infrastructure_retry_count + retry_count
        )
        return update
    return {
        "candidate_tables": result.candidate_tables,
        "candidate_fields": result.candidate_fields,
        "join_paths": result.join_paths,
        "schema_version": result.schema_version,
        "schema_snapshot": snapshot,
        "infrastructure_retry_count": (
            state.infrastructure_retry_count + retry_count
        ),
        "public_error": None,
    }


def _generation_context(state: SQLTaskState) -> GenerationContext:
    assert state.normalized_question is not None
    assert state.schema_snapshot is not None
    assert state.schema_version is not None
    linking = SchemaLinkingResult(
        candidate_tables=state.candidate_tables,
        candidate_fields=state.candidate_fields,
        join_paths=state.join_paths,
        schema_version=state.schema_version,
    )
    return GenerationContext(
        question=state.question,
        normalized_question=state.normalized_question,
        normalized_time=state.normalized_time,
        dialect=state.dialect,
        schema_linking=linking,
        snapshot=state.schema_snapshot,
    )


def _generation_messages(
    state: SQLTaskState,
) -> tuple[LLMMessage, ...]:
    messages = build_generation_messages(_generation_context(state))
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
) -> NodeUpdate:
    try:
        result = context.provider.generate(
            _generation_messages(state)
        )
    except LLMProviderError as error:
        return _failure_update(_public_model_error(error))

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
) -> NodeUpdate:
    assert state.validation_result is not None
    assert state.schema_snapshot is not None
    outcome = execute_validated_sql(
        state.validation_result,
        allowed_schemas=state.allowed_schemas,
        allowed_tables=state.allowed_tables,
        snapshot=state.schema_snapshot,
        connector=context.connector,
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
GENERATE_SQL_NODE = workflow_node("generate_sql", _generate_sql)
VALIDATE_SQL_NODE = workflow_node("validate_sql", _validate_sql)
EXECUTE_SQL_NODE = workflow_node("execute_sql", _execute_sql)
REFLECT_SQL_NODE = workflow_node("reflect_sql", _reflect_sql)
CLARIFICATION_NODE = workflow_node(
    "clarification",
    _clarification,
)
FINALIZE_NODE = workflow_node("finalize", _finalize)
