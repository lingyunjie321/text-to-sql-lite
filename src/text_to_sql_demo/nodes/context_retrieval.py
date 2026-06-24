from pathlib import Path

from text_to_sql_demo.retrieval.knowledge import KnowledgeStore
from text_to_sql_demo.workflow.node import BaseNode, NodeResult
from text_to_sql_demo.workflow.registry import register_node
from text_to_sql_demo.workflow.state import WorkflowState


@register_node("context_retrieval")
class ContextRetrievalNode(BaseNode):
    """检索 SQL 生成需要的多路知识上下文。"""

    def run(self, state: WorkflowState) -> NodeResult:
        """检索 reference SQL、文档、指标和语义模型上下文。"""
        store = self.dependencies.get("knowledge_store") or self._store_from_config()
        if store is None:
            payload = _empty_rag_context()
            return NodeResult(
                outcome="success",
                state_patch={"data": {"rag_context": payload}},
                output={"rag_context": payload},
            )

        schema_linking = state.data.get("schema_linking") or {}
        involved_tables = _linked_table_names(schema_linking.get("tables", []))
        result = store.search(
            query=state.user_question,
            involved_tables=involved_tables,
            top_k=int(self.config.get("top_k", 5)),
        )
        payload = result.model_dump(mode="python")
        return NodeResult(
            outcome="success",
            state_patch={"data": {"rag_context": payload}},
            output={"rag_context": payload},
        )

    def _store_from_config(self) -> KnowledgeStore | None:
        knowledge_path = self.config.get("knowledge_path")
        if not knowledge_path:
            return None
        path = Path(str(knowledge_path))
        if not path.exists():
            return None
        return KnowledgeStore.from_yaml(path)


def _empty_rag_context() -> dict[str, list[dict]]:
    return {
        "reference_sql": [],
        "documents": [],
        "metrics": [],
        "semantic_models": [],
    }


def _linked_table_names(tables: object) -> list[str]:
    """从 linked schema 中提取表名，兼容字符串和对象两种形态。"""
    if not isinstance(tables, list):
        return []
    names: list[str] = []
    for table in tables:
        if isinstance(table, str):
            names.append(table)
        elif isinstance(table, dict) and isinstance(table.get("name"), str):
            names.append(table["name"])
    return names
