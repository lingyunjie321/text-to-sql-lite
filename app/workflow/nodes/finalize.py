"""终结节点：形成唯一 FinalStatus 并组装公开响应与错误脱敏。"""

from __future__ import annotations

from dataclasses import replace

from app.connectors.errors import ErrorType
from app.reflection import AttemptHistory
from app.workflow.models import (
    FinalStatus,
    SQLTaskState,
    WorkflowContext,
)
from app.workflow.nodes._common import (
    NodeUpdate,
    _INTERNAL_ERROR,
    _REPAIRABLE_ERRORS,
    _TIMEOUT_ERROR,
    _failure_update,
    _history_update,
)


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
