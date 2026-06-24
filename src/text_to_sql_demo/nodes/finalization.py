from text_to_sql_demo.reflection import (
    append_success_sql_context,
    build_success_sql_attempt_context,
)
from text_to_sql_demo.workflow.node import BaseNode, NodeResult
from text_to_sql_demo.workflow.registry import register_node
from text_to_sql_demo.workflow.state import WorkflowState


@register_node("finalization")
class FinalizeNode(BaseNode):
    """收敛成功或失败状态，生成最终输出。"""

    def run(self, state: WorkflowState) -> NodeResult:
        if state.data.get("final_status") == "needs_human_review":
            payload = {
                "final_status": "needs_human_review",
                "final_sql": state.data.get("current_sql") or state.data.get("generated_sql"),
                "final_error": state.data.get("final_error") or state.data.get("last_error"),
                "attempt_count": int(state.data.get("attempt_count", 0)),
                "hitl_reason": state.data.get("hitl_reason"),
                "termination_reason": state.data.get("termination_reason") or "hitl_required",
            }
            return NodeResult(
                outcome="finalize_hitl",
                state_patch={"data": payload},
                output=payload,
            )

        execution_result = state.data.get("execution_result") or {}
        if execution_result.get("success") is True:
            final_sql = state.data.get("validated_sql") or state.data.get("generated_sql")
            success_context = build_success_sql_attempt_context(
                state_data={**state.data, "validated_sql": final_sql}
            )
            sql_contexts = append_success_sql_context(
                state.data.get("sql_contexts"),
                success_context,
            )
            payload = {
                "final_status": "success",
                "final_sql": final_sql,
                "final_result": execution_result,
                "attempt_count": int(state.data.get("attempt_count", 0)),
                "sql_contexts": sql_contexts,
            }
            return NodeResult(
                outcome="finalize_success",
                state_patch={"data": payload},
                output=payload,
            )

        payload = {
            "final_status": "failed",
            "final_sql": state.data.get("current_sql") or state.data.get("generated_sql"),
            "final_error": state.data.get("last_error"),
            "attempt_count": int(state.data.get("attempt_count", 0)),
            "termination_reason": state.data.get("termination_reason") or "failed",
        }
        return NodeResult(outcome="finalize_failed", state_patch={"data": payload}, output=payload)
