from __future__ import annotations

from typing import Any

import yaml

from text_to_sql_demo.exceptions import NodeExecutionError
from text_to_sql_demo.llm.models import ModelProfile
from text_to_sql_demo.prompts.templates import PromptTemplateRenderer
from text_to_sql_demo.reflection import format_sql_contexts
from text_to_sql_demo.sql.cleaner import clean_llm_sql_output
from text_to_sql_demo.workflow.node import BaseNode, NodeResult
from text_to_sql_demo.workflow.registry import register_node
from text_to_sql_demo.workflow.state import WorkflowState


@register_node("reasoning_rewrite")
class ReasoningRewriteNode(BaseNode):
    """结合最近反思记忆重新推理并生成 SQL。"""

    def run(self, state: WorkflowState) -> NodeResult:
        llm_client = self.dependencies.get("llm_client")
        if llm_client is None:
            raise NodeExecutionError("ReasoningRewriteNode requires llm_client dependency")

        profile = _model_profile(
            profiles=self.dependencies.get("model_profiles") or self.config.get("models"),
            model_alias=str(self.config.get("model_alias", "strong")),
        )
        system_prompt, user_prompt = _build_rewrite_prompt(
            state=state,
            template_path=self.config.get("prompt_template"),
            sql_context_limit=int(self.config.get("sql_context_limit", 3)),
        )
        response = llm_client.complete(
            model_alias=profile.alias,
            model_name=profile.model_name,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=profile.temperature,
            max_tokens=profile.max_tokens,
        )
        rewritten_sql = clean_llm_sql_output(response.text)
        attempt_count = int(state.data.get("attempt_count", 0)) + 1
        return NodeResult(
            outcome="rewrite_complete",
            state_patch={
                "data": {
                    "generated_sql": rewritten_sql,
                    "current_sql": rewritten_sql,
                    "attempt_count": attempt_count,
                }
            },
            output={"generated_sql": rewritten_sql, "attempt_count": attempt_count},
        )


def _model_profile(*, profiles: object, model_alias: str) -> ModelProfile:
    if not isinstance(profiles, dict) or model_alias not in profiles:
        raise NodeExecutionError(
            f"ReasoningRewriteNode requires model profile alias: {model_alias}"
        )
    raw_profile = profiles[model_alias]
    if isinstance(raw_profile, dict):
        return ModelProfile.model_validate({"alias": model_alias, **raw_profile})
    return ModelProfile.model_validate(raw_profile)


def _build_rewrite_prompt(
    *,
    state: WorkflowState,
    template_path: str | None = None,
    sql_context_limit: int = 3,
) -> tuple[str, str]:
    reflection_decision = state.data.get("reflection_decision") or {}
    context = {
        "user_question": state.user_question,
        "target_dialect": state.data.get("target_dialect") or "sqlite",
        "linked_schema": _dump_prompt_value(
            state.data.get("schema_linking") or state.data.get("linked_schema") or {}
        ),
        "rag_context": _dump_prompt_value(state.data.get("rag_context") or {}),
        "sql_context_block": format_sql_contexts(
            state.data.get("sql_contexts") or [],
            limit=sql_context_limit,
        ),
        "last_error": _dump_prompt_value(state.data.get("last_error") or {}),
        "reflection_reason": str(reflection_decision.get("reason") or ""),
    }
    if template_path:
        rendered_prompt = PromptTemplateRenderer.from_path(template_path).render(context)
        return rendered_prompt.system, rendered_prompt.user

    return (
        "你是 Text-to-SQL 重新推理节点，只返回新的只读 SQL。",
        "\n".join(
            [
                f"用户问题: {context['user_question']}",
                f"目标 SQL 方言: {context['target_dialect']}",
                "Linked schema:",
                str(context["linked_schema"]),
                "RAG context:",
                str(context["rag_context"]),
                "最近反思记忆:",
                str(context["sql_context_block"]),
                "Last error:",
                str(context["last_error"]),
                f"反思原因: {context['reflection_reason']}",
                "输出约束:",
                "- 只返回一条只读 SQL。",
                "- 不要解释，不要使用 Markdown 代码块。",
                "- 只使用 linked schema 和可信上下文。",
            ]
        ),
    )


def _dump_prompt_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return yaml.safe_dump(value, allow_unicode=True, sort_keys=False).strip()
