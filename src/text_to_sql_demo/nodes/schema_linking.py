from text_to_sql_demo.schema.catalog import DatabaseSchemaMetadata
from text_to_sql_demo.schema.linking import SchemaLinker
from text_to_sql_demo.workflow.node import BaseNode, NodeResult
from text_to_sql_demo.workflow.registry import register_node
from text_to_sql_demo.workflow.state import WorkflowState


@register_node("schema_linking")
class SchemaLinkingNode(BaseNode):
    """使用轻量可解释规则选择与问题相关的 Schema 子集。"""

    def run(self, state: WorkflowState) -> NodeResult:
        schema_payload = state.data.get("schema") or self.dependencies.get("schema")
        if schema_payload is None:
            raise ValueError("SchemaLinkingNode requires schema metadata in state or dependencies")

        schema = DatabaseSchemaMetadata.model_validate(schema_payload)
        linker = SchemaLinker(
            top_k_tables=int(self.config.get("top_k_tables", 5)),
            max_columns_per_table=int(self.config.get("max_columns_per_table", 8)),
        )
        result = linker.link(state.user_question, schema)
        payload = result.model_dump(mode="python")
        return NodeResult(
            outcome="success",
            state_patch={"data": {"schema_linking": payload}},
            output={"schema_linking": payload},
        )
