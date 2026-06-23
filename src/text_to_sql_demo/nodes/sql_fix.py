from text_to_sql_demo.exceptions import NodeExecutionError
from text_to_sql_demo.llm.models import ModelProfile
from text_to_sql_demo.workflow.node import BaseNode, NodeResult
from text_to_sql_demo.workflow.registry import register_node
from text_to_sql_demo.workflow.state import WorkflowState


@register_node("sql_fix")
@register_node("reflection_fix")
class FixSQLNode(BaseNode):
    """根据 RepairInstruction 生成新的 SQL，并记录修复历史。"""

    def run(self, state: WorkflowState) -> NodeResult:
        instruction = state.data["repair_instruction"]
        old_sql = str(instruction["current_sql"])
        llm_client = self.dependencies.get("llm_client")
        if llm_client is None:
            raise NodeExecutionError("FixSQLNode requires llm_client dependency")

        profiles = self.dependencies.get("model_profiles") or self.config.get("models")
        model_alias = str(self.config.get("model_alias", "strong"))
        if not isinstance(profiles, dict) or model_alias not in profiles:
            raise NodeExecutionError(f"FixSQLNode requires model profile alias: {model_alias}")
        profile = ModelProfile.model_validate(profiles[model_alias])

        response = llm_client.complete(
            model_alias=profile.alias,
            model_name=profile.model_name,
            system_prompt="You repair SQL and return only SQL text.",
            user_prompt=_build_fix_prompt(instruction),
            temperature=profile.temperature,
            max_tokens=profile.max_tokens,
        )
        new_sql = response.text.strip()
        attempt_count = int(state.data.get("attempt_count", 0)) + 1
        repair_entry = {
            "attempt": attempt_count,
            "old_sql": old_sql,
            "new_sql": new_sql,
            "error_type": instruction["error_category"],
            "reason": instruction["reason"],
        }
        repair_history = [*state.data.get("repair_history", []), repair_entry]
        return NodeResult(
            outcome="fix_complete",
            state_patch={
                "data": {
                    "generated_sql": new_sql,
                    "current_sql": new_sql,
                    "attempt_count": attempt_count,
                    "repair_history": repair_history,
                }
            },
            output={"repair": repair_entry},
        )


def _build_fix_prompt(instruction: dict) -> str:
    return "\n".join(
        [
            f"Original question: {instruction['original_question']}",
            f"Current SQL: {instruction['current_sql']}",
            f"Error category: {instruction['error_category']}",
            f"Original error: {instruction['original_error']}",
            f"Relevant schema: {instruction['related_schema']}",
            f"Repair history: {instruction['repair_history']}",
            "Return only the corrected SQL. Do not change the user question.",
        ]
    )
