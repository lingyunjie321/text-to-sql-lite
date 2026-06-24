from __future__ import annotations

from datetime import UTC, datetime

from text_to_sql_demo.metadata.models import (
    FeedbackRecord,
    QueryRunRecord,
    SavedQueryRecord,
    TraceEventRecord,
)
from text_to_sql_demo.metadata.store import MetadataStore

NOW = datetime(2026, 6, 24, 10, 30, tzinfo=UTC)


def test_metadata_store_persists_query_run_trace_saved_query_and_feedback(
    tmp_path,
) -> None:
    store = MetadataStore(database_url=f"sqlite:///{tmp_path / 'metadata.db'}")
    run = QueryRunRecord(
        request_id="req-1",
        question="统计订单金额",
        status="success",
        final_sql="SELECT SUM(amount) AS total_amount FROM orders",
        attempts=0,
        selected_model="light",
        routing_reason="简单聚合",
        target_dialect="sqlite",
        runtime_config_id=None,
        row_count=1,
        error_message=None,
        created_at=NOW,
        updated_at=NOW,
    )
    trace = TraceEventRecord(
        request_id="req-1",
        step=1,
        node_name="begin",
        node_type="BeginNode",
        status="success",
        outcome="success",
        duration_ms=3,
        input_summary={"question_length": 6},
        output_summary={"outcome": "success"},
        error=None,
        started_at=NOW,
        ended_at=NOW,
    )

    store.save_query_run(run, trace_events=[trace])
    saved_query = store.save_saved_query(
        SavedQueryRecord(
            id="saved-1",
            name="订单总金额",
            question=run.question,
            sql=run.final_sql or "",
            created_from_run_id=run.request_id,
            tags=["运营", "订单"],
            created_at=NOW,
            updated_at=NOW,
        )
    )
    feedback = store.save_feedback(
        FeedbackRecord(
            id="feedback-1",
            request_id=run.request_id,
            rating="up",
            issue_type="accurate",
            comment="结果可用",
            created_at=NOW,
        )
    )

    loaded_run = store.get_query_run("req-1")
    assert loaded_run is not None
    assert loaded_run.query_run == run
    assert loaded_run.trace_events == [trace]

    assert store.list_query_runs(limit=10).items[0].request_id == "req-1"
    assert saved_query.created_from_run_id == "req-1"
    assert store.list_saved_queries(limit=10).items == [saved_query]
    assert feedback.request_id == "req-1"
    assert store.list_feedback(request_id="req-1", limit=10).items == [feedback]
