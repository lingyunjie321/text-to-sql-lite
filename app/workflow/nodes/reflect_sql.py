"""反思修复节点：按错误类型路由到 Schema 重新探测或语法/方言重新生成（最多三次）。"""

from __future__ import annotations

from app.reflection import (
    ReflectionRoute,
    RepairStrategy,
    decide_reflection,
)
from app.workflow.models import (
    SQLTaskState,
    WorkflowContext,
    WorkflowPublicError,
)
from app.workflow.nodes._common import (
    NodeUpdate,
    _INTERNAL_ERROR,
    _failure_update,
)


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
