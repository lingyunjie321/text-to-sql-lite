from text_to_sql_demo.exceptions import NodeExecutionError
from text_to_sql_demo.llm.models import ModelProfile
from text_to_sql_demo.prompts.templates import PromptTemplateRenderer
from text_to_sql_demo.reflection import format_sql_contexts
from text_to_sql_demo.sql.cleaner import clean_llm_sql_output
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
        system_prompt, user_prompt = _build_fix_prompt(
            instruction,
            template_path=self.config.get("prompt_template"),
            reflection_decision=state.data.get("reflection_decision"),
            sql_contexts=state.data.get("sql_contexts") or [],
        )

        response = llm_client.complete(
            model_alias=profile.alias,
            model_name=profile.model_name,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=profile.temperature,
            max_tokens=profile.max_tokens,
        )
        new_sql = clean_llm_sql_output(response.text)
        attempt_count = int(state.data.get("attempt_count", 0)) + 1
        repair_entry = {
            "attempt": attempt_count,
            "old_sql": old_sql,
            "new_sql": new_sql,
            "error_type": instruction["error_category"],
            "reason": instruction["reason"],
        }
        strategy_name = (instruction.get("strategy") or {}).get("name")
        if strategy_name:
            repair_entry["strategy_name"] = strategy_name
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


def _build_fix_prompt(
    instruction: dict,
    *,
    template_path: str | None = None,
    reflection_decision: object = None,
    sql_contexts: list[dict] | None = None,
) -> tuple[str, str]:
    reflection_reason = _reflection_reason(reflection_decision) or instruction["reason"]
    context = {
        "original_question": instruction["original_question"],
        "current_sql": instruction["current_sql"],
        "error_category": instruction["error_category"],
        "original_error": instruction["original_error"],
        "related_schema": instruction["related_schema"],
        "repair_history": instruction["repair_history"],
        "reason": instruction["reason"],
        "reflection_reason": reflection_reason,
        "sql_context_block": format_sql_contexts(sql_contexts or [], limit=3),
        "strategy_block": _format_strategy_block(instruction.get("strategy")),
    }
    if template_path:
        rendered_prompt = PromptTemplateRenderer.from_path(template_path).render(context)
        return rendered_prompt.system, rendered_prompt.user

    return (
        "你修复 SQL，只返回修复后的只读 SQL。",
        "\n".join(
            [
                f"原始问题: {instruction['original_question']}",
                f"当前 SQL: {instruction['current_sql']}",
                f"错误类型: {instruction['error_category']}",
                f"原始错误: {instruction['original_error']}",
                f"相关 Schema: {instruction['related_schema']}",
                f"修复历史: {instruction['repair_history']}",
                "最近反思记忆:",
                format_sql_contexts(sql_contexts or [], limit=3),
                f"策略反思原因: {reflection_reason}",
                "定向修复策略:",
                _format_strategy_block(instruction.get("strategy")),
                "只返回修复后的 SQL，不要改变用户问题含义。",
            ]
        ),
    )


def _format_strategy_block(strategy: object) -> str:
    """把结构化修复策略压缩成 prompt 可读文本。"""
    if not isinstance(strategy, dict):
        return "未提供定向策略，按错误类型和相关 Schema 保守修复。"

    lines = [
        f"- 策略: {strategy.get('name')}",
        f"- 重点: {strategy.get('focus')}",
    ]
    instructions = strategy.get("instructions")
    if isinstance(instructions, list) and instructions:
        lines.append("- 执行:")
        lines.extend(f"  - {item}" for item in instructions)

    avoid = strategy.get("avoid")
    if isinstance(avoid, list) and avoid:
        lines.append("- 避免:")
        lines.extend(f"  - {item}" for item in avoid)
    return "\n".join(lines)


def _reflection_reason(reflection_decision: object) -> str | None:
    if not isinstance(reflection_decision, dict):
        return None
    reason = reflection_decision.get("reason")
    return reason if isinstance(reason, str) and reason else None
