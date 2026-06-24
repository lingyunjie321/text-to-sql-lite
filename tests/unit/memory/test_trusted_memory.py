from datetime import UTC, datetime, timedelta

from text_to_sql_demo.memory import (
    merge_reference_sql_hits,
    search_approved_saved_query_reference_sql,
)
from text_to_sql_demo.metadata.models import SavedQueryRecord
from text_to_sql_demo.metadata.store import MetadataStore
from text_to_sql_demo.retrieval.knowledge import KnowledgeSearchHit, ReferenceSqlItem

NOW = datetime(2026, 6, 24, 10, 30, tzinfo=UTC)


def test_search_approved_saved_query_reference_sql_excludes_drafts(tmp_path) -> None:
    metadata_store = MetadataStore(database_url=f"sqlite:///{tmp_path / 'metadata.db'}")
    metadata_store.save_saved_query(
        SavedQueryRecord(
            id="approved",
            name="approved_order_total",
            question="统计订单金额",
            sql="SELECT SUM(amount) FROM orders",
            tags=["订单", "金额"],
            status="approved",
            created_at=NOW,
            updated_at=NOW,
        )
    )
    metadata_store.save_saved_query(
        SavedQueryRecord(
            id="draft",
            name="draft_order_total",
            question="统计订单金额",
            sql="SELECT SUM(total_amount) FROM orders",
            tags=["订单", "金额"],
            status="draft",
            created_at=NOW,
            updated_at=NOW,
        )
    )
    metadata_store.save_saved_query(
        SavedQueryRecord(
            id="deprecated",
            name="deprecated_order_total",
            question="统计订单金额",
            sql="SELECT SUM(old_amount) FROM orders",
            tags=["订单", "金额"],
            status="deprecated",
            created_at=NOW,
            updated_at=NOW,
        )
    )

    hits = search_approved_saved_query_reference_sql(
        metadata_store=metadata_store,
        query="统计订单金额",
        involved_tables=["orders"],
        top_k=2,
    )

    assert [hit.item.name for hit in hits] == ["approved_order_total"]
    assert hits[0].item.natural_language == "统计订单金额"
    assert hits[0].item.involved_tables == []


def test_search_approved_saved_query_scans_beyond_recent_fifty_candidates(tmp_path) -> None:
    metadata_store = MetadataStore(database_url=f"sqlite:///{tmp_path / 'metadata.db'}")
    old_relevant_time = NOW - timedelta(days=90)
    metadata_store.save_saved_query(
        SavedQueryRecord(
            id="old-relevant",
            name="old_refund_amount",
            question="统计退款订单金额",
            sql="SELECT SUM(refund_amount) FROM refunds",
            tags=["退款", "金额"],
            status="approved",
            created_at=old_relevant_time,
            updated_at=old_relevant_time,
        )
    )
    for index in range(60):
        saved_at = NOW + timedelta(minutes=index)
        metadata_store.save_saved_query(
            SavedQueryRecord(
                id=f"recent-unrelated-{index}",
                name=f"recent_customer_list_{index}",
                question="列出客户名单",
                sql=f"SELECT id, name FROM customers LIMIT {index + 1}",
                tags=["客户"],
                status="approved",
                created_at=saved_at,
                updated_at=saved_at,
            )
        )

    hits = search_approved_saved_query_reference_sql(
        metadata_store=metadata_store,
        query="统计退款订单金额",
        involved_tables=["refunds"],
        top_k=1,
    )

    assert [hit.item.name for hit in hits] == ["old_refund_amount"]


def test_merge_reference_sql_hits_deduplicates_and_limits_top_k() -> None:
    duplicate_yaml = KnowledgeSearchHit(
        item=ReferenceSqlItem(
            name="order_total",
            natural_language="统计订单金额",
            sql="SELECT SUM(amount) FROM orders",
        ),
        score=8,
    )
    duplicate_trusted = KnowledgeSearchHit(
        item=ReferenceSqlItem(
            name="trusted_order_total",
            natural_language="统计订单金额",
            sql="SELECT  SUM(amount)  FROM orders",
        ),
        score=9,
    )
    other_trusted = KnowledgeSearchHit(
        item=ReferenceSqlItem(
            name="trusted_order_detail",
            natural_language="列出订单金额",
            sql="SELECT id, amount FROM orders",
        ),
        score=7,
    )

    merged = merge_reference_sql_hits(
        yaml_hits=[duplicate_yaml],
        trusted_hits=[duplicate_trusted, other_trusted],
        top_k=2,
    )

    assert [hit.item.name for hit in merged] == [
        "trusted_order_total",
        "trusted_order_detail",
    ]
