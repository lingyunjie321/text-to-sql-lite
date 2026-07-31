"""工作流包装器：组装 LangGraph 状态图并暴露同步运行入口。"""

from __future__ import annotations

from collections.abc import Callable

from langgraph.runtime import Runtime

from app.workflow.models import (
    MAX_WORKFLOW_STEPS,
    REQUEST_TIMEOUT_SECONDS,
    GenerationObservation,
    NodeTiming,
    SQLTaskState,
    WorkflowContext,
)
from app.workflow.nodes._common import (
    NodeCore,
    NodeUpdate,
    _INTERNAL_ERROR,
    _STEP_LIMIT_ERROR,
    _TIMEOUT_ERROR,
    _failure_update,
)
from app.workflow.nodes.finalize import (
    _catastrophic_finalize_update,
    _terminal_timeout_update,
)


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
            elif name in {"schema_linking", "generate_sql", "execute_sql"}:
                deadline_at = (
                    workflow_started_at + REQUEST_TIMEOUT_SECONDS
                )
                remaining = deadline_at - started
                if name == "schema_linking":
                    from app.workflow.nodes.schema_linking import (
                        _schema_linking,
                    )
                    update = _schema_linking(
                        state,
                        context,
                        deadline_at=deadline_at,
                        database_timeout_seconds=remaining,
                    )
                elif name == "generate_sql":
                    from app.workflow.nodes.generate_sql import (
                        _generate_sql,
                    )
                    update = _generate_sql(
                        state,
                        context,
                        deadline_at=deadline_at,
                    )
                else:
                    from app.workflow.nodes.execute_sql import (
                        _execute_sql,
                    )
                    update = _execute_sql(
                        state,
                        context,
                        database_timeout_seconds=remaining,
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
