from pathlib import Path

from text_to_sql_demo.retrieval.knowledge import KnowledgeStore


def test_knowledge_store_searches_reference_documents_metrics_and_semantic_models(
    tmp_path: Path,
) -> None:
    knowledge_path = tmp_path / "knowledge.yaml"
    knowledge_path.write_text(
        """
reference_sql:
  - name: order_amount
    natural_language: 订单金额明细
    sql: SELECT amount FROM orders
    involved_tables: [orders]
documents:
  - title: 订单口径
    content: 订单金额使用 orders.amount 字段
    tags: [订单, 金额]
metrics:
  - name: total_amount
    description: 订单总金额
    expression: SUM(orders.amount)
    involved_tables: [orders]
semantic_models:
  - name: orders_semantic
    description: 订单事实表，包含订单金额和状态
    tables: [orders]
""",
        encoding="utf-8",
    )

    store = KnowledgeStore.from_yaml(knowledge_path)
    result = store.search(
        query="统计订单金额",
        involved_tables=["orders"],
        top_k=3,
    )

    assert result.reference_sql[0].item.name == "order_amount"
    assert result.documents[0].item.title == "订单口径"
    assert result.metrics[0].item.name == "total_amount"
    assert result.semantic_models[0].item.name == "orders_semantic"
    assert result.model_dump(mode="python")["reference_sql"][0]["score"] > 0
