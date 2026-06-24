import json
from datetime import UTC, datetime

from text_to_sql_demo.metadata.models import SavedQueryRecord
from text_to_sql_demo.metadata.store import MetadataStore
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

NOW = datetime(2026, 6, 24, 10, 30, tzinfo=UTC)


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


def test_context_retrieval_uses_only_approved_saved_queries_as_reference_sql(tmp_path) -> None:
    metadata_store = MetadataStore(database_url=f"sqlite:///{tmp_path / 'metadata.db'}")
    metadata_store.save_saved_query(
        SavedQueryRecord(
            id="saved-approved",
            name="approved_order_total",
            question="统计订单金额",
            sql="SELECT SUM(amount) AS total_amount FROM orders",
            tags=["订单", "金额"],
            status="approved",
            created_at=NOW,
            updated_at=NOW,
        )
    )
    metadata_store.save_saved_query(
        SavedQueryRecord(
            id="saved-draft",
            name="draft_order_total",
            question="统计订单金额",
            sql="SELECT SUM(total_amount) FROM orders",
            tags=["订单", "金额"],
            status="draft",
            created_at=NOW,
            updated_at=NOW,
        )
    )
    store = KnowledgeStore(
        reference_sql=[
            ReferenceSqlItem(
                name="yaml_order_detail",
                natural_language="列出订单金额",
                sql="SELECT id, amount FROM orders ORDER BY id",
                involved_tables=["orders"],
            )
        ]
    )
    state = WorkflowState(
        user_question="统计订单金额",
        data={"schema_linking": {"tables": [{"name": "orders"}]}},
    )
    node = ContextRetrievalNode(
        name="context_retrieval",
        config={"top_k": 3},
        dependencies=NodeDependencies(
            values={
                "knowledge_store": store,
                "metadata_store": metadata_store,
            }
        ),
    )

    result = node.run(state)

    reference_sql = result.state_patch["data"]["rag_context"]["reference_sql"]
    names = {hit["item"]["name"] for hit in reference_sql}
    sql_values = {hit["item"]["sql"] for hit in reference_sql}
    assert "approved_order_total" in names
    assert "yaml_order_detail" in names
    assert "draft_order_total" not in names
    assert "SELECT SUM(total_amount) FROM orders" not in sql_values
    assert len(reference_sql) <= 3
