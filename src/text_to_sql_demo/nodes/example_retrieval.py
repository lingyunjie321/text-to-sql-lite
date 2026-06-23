from pathlib import Path

from text_to_sql_demo.retrieval.examples import ExampleStore
from text_to_sql_demo.workflow.node import BaseNode, NodeResult
from text_to_sql_demo.workflow.registry import register_node
from text_to_sql_demo.workflow.state import WorkflowState


@register_node("example_retrieval")
class ExampleRetrievalNode(BaseNode):
    """基于本地词法相似度检索历史 Text-to-SQL 示例。"""

    def run(self, state: WorkflowState) -> NodeResult:
        store = self.dependencies.get("example_store")
        if store is None:
            examples_path = self.config.get("examples_path", "configs/examples.yaml")
            store = ExampleStore.from_yaml(Path(str(examples_path)))

        schema_linking = state.data.get("schema_linking") or {}
        involved_tables = [
            table["name"]
            for table in schema_linking.get("tables", [])
            if isinstance(table, dict) and "name" in table
        ]
        results = store.search(
            query=state.user_question,
            dialect=self.config.get("dialect") or state.data.get("dialect"),
            top_k=int(self.config.get("top_k", 5)),
            involved_tables=involved_tables,
        )
        payload = [result.model_dump(mode="python") for result in results]
        available_example_count = len(getattr(store, "examples", []))
        return NodeResult(
            outcome="success",
            state_patch={
                "data": {
                    "retrieved_examples": payload,
                    "available_example_count": available_example_count,
                }
            },
            output={"retrieved_examples": payload},
        )
