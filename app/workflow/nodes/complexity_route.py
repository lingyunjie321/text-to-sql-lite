from __future__ import annotations

from app.workflow.complexity import decide_complexity
from app.workflow.models import SQLTaskState, WorkflowContext
from app.workflow.nodes._common import NodeUpdate


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
