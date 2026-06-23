from text_to_sql_demo.workflow.node import BaseNode, NodeResult
from text_to_sql_demo.workflow.registry import register_node
from text_to_sql_demo.workflow.state import WorkflowState


@register_node("finalization")
class FinalizeNode(BaseNode):
    """收敛成功或失败状态，生成最终输出。"""

    def run(self, state: WorkflowState) -> NodeResult:
        execution_result = state.data.get("execution_result") or {}
        if execution_result.get("success") is True:
            payload = {
                "final_status": "success",
                "final_sql": state.data.get("validated_sql") or state.data.get("generated_sql"),
                "final_result": execution_result,
                "attempt_count": int(state.data.get("attempt_count", 0)),
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
