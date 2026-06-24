from __future__ import annotations

from text_to_sql_demo.workflow.node import BaseNode, NodeResult
from text_to_sql_demo.workflow.registry import register_node
from text_to_sql_demo.workflow.state import WorkflowState


@register_node("hitl")
class HITLNode(BaseNode):
    """把自动修复无法处理的状态标记为需要人工介入。"""

    def run(self, state: WorkflowState) -> NodeResult:
        decision = state.data.get("reflection_decision") or {}
        reason = str(
            decision.get("reason")
            or state.data.get("termination_reason")
            or "需要人工确认 SQL、Schema 或业务口径"
        )
        payload = {
            "final_status": "needs_human_review",
            "hitl_reason": reason,
            "final_error": state.data.get("last_error"),
            "termination_reason": state.data.get("termination_reason") or "hitl_required",
        }
        return NodeResult(
            outcome="hitl_required",
            state_patch={"data": payload},
            output=payload,
        )
