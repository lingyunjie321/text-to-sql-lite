"""节点共用工具：节点间共享的状态读取、deadline 计算与错误映射辅助。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timezone
from typing import TypeAlias

from app.connectors.errors import ErrorType, PostgreSQLConnectorError
from app.generation import LLMProviderError
from app.reflection import (
    AttemptHistory,
    RepairStrategy,
    register_repair_sql,
    start_attempt,
)
from app.schema_linking import EmbeddingProviderError
from app.validation import validate_sql
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
    WorkflowPublicError,
)

NodeUpdate: TypeAlias = dict[str, object]
NodeCore: TypeAlias = Callable[
    [SQLTaskState, WorkflowContext],
    NodeUpdate,
]

# ── Error groups ─────────────────────────────────────────
_REPAIRABLE_ERRORS = frozenset(
    {
        ErrorType.SYNTAX_ERROR,
        ErrorType.SCHEMA_ERROR,
        ErrorType.DIALECT_ERROR,
    }
)

# ── Public error presets ──────────────────────────────────
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


# ── Shared helpers ────────────────────────────────────────

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
