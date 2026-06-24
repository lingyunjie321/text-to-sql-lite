from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from text_to_sql_demo.llm.client import MockLLMClient
from text_to_sql_demo.main import create_app
from text_to_sql_demo.metadata.store import MetadataStore


def build_client(tmp_path: Path) -> TestClient:
    app = create_app(
        database_url=f"sqlite:///{tmp_path / 'demo.db'}",
        llm_client=MockLLMClient(
            responses={
                "light": "SELECT id, amount FROM orders ORDER BY id",
                "strong": "SELECT id, amount FROM orders ORDER BY id",
            }
        ),
        metadata_store=MetadataStore(database_url=f"sqlite:///{tmp_path / 'metadata.db'}"),
    )
    return TestClient(app)


def test_runs_endpoint_lists_persisted_query_runs(tmp_path: Path) -> None:
    client = build_client(tmp_path)
    query_response = client.post(
        "/api/v1/query",
        json={"question": "列出订单金额", "target_dialect": "sqlite", "max_attempts": 1},
    )
    request_id = query_response.json()["request_id"]

    response = client.get("/api/v1/runs")

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["items"][0]["request_id"] == request_id
    assert payload["items"][0]["question"] == "列出订单金额"
    assert payload["items"][0]["status"] == "success"


def test_saved_query_and_feedback_api_use_persisted_run(tmp_path: Path) -> None:
    client = build_client(tmp_path)
    query_response = client.post(
        "/api/v1/query",
        json={"question": "列出订单金额", "target_dialect": "sqlite", "max_attempts": 1},
    )
    request_id = query_response.json()["request_id"]

    save_response = client.post(
        "/api/v1/saved-queries",
        json={
            "name": "订单金额明细",
            "request_id": request_id,
            "tags": ["运营", "订单"],
        },
    )
    feedback_response = client.post(
        f"/api/v1/runs/{request_id}/feedback",
        json={
            "rating": "up",
            "issue_type": "accurate",
            "comment": "结果可直接使用",
        },
    )

    assert save_response.status_code == 200
    saved_payload = save_response.json()
    assert saved_payload["created_from_run_id"] == request_id
    assert saved_payload["sql"] == "SELECT id, amount FROM orders ORDER BY id"
    assert saved_payload["tags"] == ["运营", "订单"]

    assert feedback_response.status_code == 200
    feedback_payload = feedback_response.json()
    assert feedback_payload["request_id"] == request_id
    assert feedback_payload["rating"] == "up"

    list_response = client.get("/api/v1/saved-queries")
    assert list_response.status_code == 200
    assert list_response.json()["items"][0]["name"] == "订单金额明细"
