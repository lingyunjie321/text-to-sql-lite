from text_to_sql_demo.exceptions import NodeExecutionError
from text_to_sql_demo.llm.models import ModelProfile
from text_to_sql_demo.prompts.builder import PromptBuilder
from text_to_sql_demo.retrieval.patterns import BusinessPatternStore
from text_to_sql_demo.routing.complexity import ComplexityClassifier, ModelRouter
from text_to_sql_demo.sql.cleaner import clean_llm_sql_output
from text_to_sql_demo.workflow.node import BaseNode, NodeResult
from text_to_sql_demo.workflow.registry import register_node
from text_to_sql_demo.workflow.state import WorkflowState


@register_node("sql_generation")
@register_node("gen_sql_agentic")
class GenSQLAgenticNode(BaseNode):
    """构建 prompt、注入上下文、路由模型并生成 SQL。"""

    def run(self, state: WorkflowState) -> NodeResult:
        llm_client = self.dependencies.get("llm_client")
        if llm_client is None:
            raise NodeExecutionError("GenSQLAgenticNode requires llm_client dependency")

        profiles = _load_profiles(
            self.dependencies.get("model_profiles") or self.config.get("models")
        )
        linked_schema = state.data.get("schema_linking") or state.data.get("linked_schema") or {}
        examples = state.data.get("retrieved_examples") or []
        target_dialect = str(
            state.data.get("target_dialect") or self.config.get("target_dialect") or "sqlite"
        )
        business_patterns = _load_business_patterns(
            state=state,
            config=self.config,
            dependencies=self.dependencies,
            target_dialect=target_dialect,
            linked_schema=linked_schema,
        )

        complexity = ComplexityClassifier().classify(state.user_question, linked_schema)
        selected_profile = ModelRouter(profiles=profiles).route(complexity)
        prompt = PromptBuilder().build(
            user_question=state.user_question,
            target_dialect=target_dialect,
            original_schema=state.data.get("schema"),
            linked_schema=linked_schema,
            examples=examples,
            original_example_count=state.data.get("available_example_count"),
            business_patterns=business_patterns,
            template_path=self.config.get("prompt_template"),
        )
        response = llm_client.complete(
            model_alias=selected_profile.alias,
            model_name=selected_profile.model_name,
            system_prompt=prompt.system_prompt,
            user_prompt=prompt.user_prompt,
            temperature=selected_profile.temperature,
            max_tokens=selected_profile.max_tokens,
        )
        generated_sql = clean_llm_sql_output(response.text)
        routing_reason = "; ".join(complexity.reasons)
        payload = {
            "generated_sql": generated_sql,
            "selected_model": selected_profile.alias,
            "complexity_level": complexity.level,
            "routing_reason": routing_reason,
            "prompt_summary": prompt.summary,
            "business_patterns": business_patterns,
        }
        return NodeResult(
            outcome="success",
            state_patch={"data": payload},
            output=payload,
        )


def _load_profiles(raw_profiles: object) -> dict[str, ModelProfile]:
    if not isinstance(raw_profiles, dict):
        raise NodeExecutionError(
            "GenSQLAgenticNode requires model profiles for light and strong aliases"
        )
    return {
        alias: ModelProfile.model_validate({"alias": alias, **profile})
        if isinstance(profile, dict)
        else ModelProfile.model_validate(profile)
        for alias, profile in raw_profiles.items()
    }


def _load_business_patterns(
    *,
    state: WorkflowState,
    config: dict,
    dependencies: object,
    target_dialect: str,
    linked_schema: dict,
) -> list[dict]:
    configured_patterns = state.data.get("business_patterns")
    if isinstance(configured_patterns, list):
        return configured_patterns

    store = dependencies.get("business_pattern_store")
    patterns_path = config.get("patterns_path")
    if store is None and patterns_path:
        store = BusinessPatternStore.from_yaml(str(patterns_path))
    if store is None:
        return []

    involved_tables = [
        table["name"]
        for table in linked_schema.get("tables", [])
        if isinstance(table, dict) and "name" in table
    ]
    results = store.search(
        query=state.user_question,
        dialect=target_dialect,
        top_k=int(config.get("patterns_top_k", 3)),
        involved_tables=involved_tables,
    )
    return [result.model_dump(mode="python") for result in results]


GenerateSQLNode = GenSQLAgenticNode
