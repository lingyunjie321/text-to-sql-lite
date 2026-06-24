import json

from text_to_sql_demo.nodes.context_retrieval import ContextRetrievalNode
from text_to_sql_demo.retrieval.knowledge import (
    DocumentKnowledgeItem,
    KnowledgeStore,
    MetricItem,
    ReferenceSqlItem,
    SemanticModelItem,
)
from text_to_sql_demo.workflow.dependencies import NodeDependencies
from text_to_sql_demo.workflow.state import WorkflowState


def test_context_retrieval_node_writes_serializable_rag_context() -> None:
    store = KnowledgeStore(
        reference_sql=[
            ReferenceSqlItem(
                name="order_amount",
                natural_language="订单金额",
                sql="SELECT amount FROM orders",
                involved_tables=["orders"],
            )
        ],
        documents=[
            DocumentKnowledgeItem(title="订单口径", content="订单金额使用 orders.amount 字段")
        ],
        metrics=[
            MetricItem(
                name="total_amount",
                description="订单总金额",
                expression="SUM(orders.amount)",
                involved_tables=["orders"],
            )
        ],
        semantic_models=[
            SemanticModelItem(
                name="orders_semantic",
                description="订单事实表",
                tables=["orders"],
            )
        ],
    )
    state = WorkflowState(
        user_question="统计订单金额",
        data={
            "schema_linking": {
                "tables": [
                    {"name": "orders", "columns": {"amount": {"name": "amount"}}}
                ]
            }
        },
    )

    node = ContextRetrievalNode(
        name="context_retrieval",
        config={"top_k": 3},
        dependencies=NodeDependencies(values={"knowledge_store": store}),
    )
    result = node.run(state)

    assert result.outcome == "success"
    rag_context = result.state_patch["data"]["rag_context"]
    assert rag_context["reference_sql"][0]["item"]["name"] == "order_amount"
    assert rag_context["documents"][0]["item"]["title"] == "订单口径"
    assert rag_context["metrics"][0]["item"]["name"] == "total_amount"
    assert rag_context["semantic_models"][0]["item"]["name"] == "orders_semantic"
    json.dumps(result.model_dump(mode="json"))
