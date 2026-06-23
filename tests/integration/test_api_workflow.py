from pathlib import Path

from fastapi.testclient import TestClient

from text_to_sql_demo.api.service import TextToSQLApiService
from text_to_sql_demo.llm.client import MockLLMClient
from text_to_sql_demo.main import create_app


def build_client(tmp_path: Path) -> TestClient:
    database_url = f"sqlite:///{tmp_path / 'demo.db'}"
    llm_client = MockLLMClient(
        responses={
            "light": "SELECT id, amount FROM orders ORDER BY id",
            "strong": "SELECT id, amount FROM orders ORDER BY id",
        }
    )
    app = create_app(database_url=database_url, llm_client=llm_client)
    return TestClient(app)


def test_query_endpoint_runs_workflow_and_returns_demo_payload(tmp_path: Path) -> None:
    client = build_client(tmp_path)

    response = client.post(
        "/api/v1/query",
        json={
            "question": "列出订单金额",
            "target_dialect": "sqlite",
            "max_attempts": 2,
            "debug": True,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "success"
    assert payload["final_sql"] == "SELECT id, amount FROM orders ORDER BY id"
    assert payload["attempts"] == 0
    assert payload["selected_model"] in {"light", "strong"}
    assert payload["routing_reason"]
    assert payload["linked_schema"]["tables"]
    assert isinstance(payload["retrieved_examples"], list)
    assert payload["errors"] == []
    assert payload["result"]["columns"] == ["id", "amount"]

    first_trace = payload["trace"][0]
    assert {
        "node_name",
        "node_type",
        "start_time",
        "end_time",
        "duration_ms",
        "status",
        "outcome",
        "input_summary",
        "output_summary",
        "error",
    } <= set(first_trace)


def test_runs_endpoint_returns_previous_workflow_state(tmp_path: Path) -> None:
    client = build_client(tmp_path)
    query_response = client.post(
        "/api/v1/query",
        json={"question": "列出订单金额", "target_dialect": "sqlite", "max_attempts": 1},
    )
    request_id = query_response.json()["request_id"]

    response = client.get(f"/api/v1/runs/{request_id}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["request_id"] == request_id
    assert payload["status"] == "success"
    assert payload["trace"]


def test_schema_endpoint_returns_demo_schema(tmp_path: Path) -> None:
    client = build_client(tmp_path)

    response = client.get("/api/v1/schema")

    assert response.status_code == 200
    tables = response.json()["tables"]
    assert {"customers", "regions", "orders", "order_items", "products"} <= set(tables)


def test_v1_transpile_endpoint_returns_unified_payload(tmp_path: Path) -> None:
    client = build_client(tmp_path)

    response = client.post(
        "/api/v1/transpile",
        json={
            "sql": "SELECT name || email AS label FROM customers",
            "source_dialect": "postgres",
            "target_dialect": "mysql",
        },
    )

    assert response.status_code == 200
    assert response.json()["rendered_sql"] == "SELECT CONCAT(name, email) AS label FROM customers"


def test_execute_sql_endpoint_runs_read_only_sql(tmp_path: Path) -> None:
    client = build_client(tmp_path)

    response = client.post(
        "/api/v1/sql/execute",
        json={
            "sql": "SELECT id, amount FROM orders ORDER BY id",
            "target_dialect": "sqlite",
            "max_rows": 2,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "success"
    assert payload["final_sql"] == "SELECT id, amount FROM orders ORDER BY id"
    assert payload["result"]["columns"] == ["id", "amount"]
    assert len(payload["result"]["rows"]) == 2
    assert payload["trace"] == []
    assert payload["selected_model"] is None


def test_execute_sql_endpoint_rejects_write_sql(tmp_path: Path) -> None:
    client = build_client(tmp_path)

    response = client.post(
        "/api/v1/sql/execute",
        json={
            "sql": "DELETE FROM orders",
            "target_dialect": "sqlite",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "failed"
    assert payload["result"] is None
    assert payload["errors"][0]["error_type"] == "dialect_error"
    assert payload["errors"][0]["message"] == "只允许只读 SELECT 查询"


def test_api_errors_use_unified_response_shape(tmp_path: Path) -> None:
    client = build_client(tmp_path)

    response = client.get("/api/v1/runs/missing-request-id")

    assert response.status_code == 404
    assert response.json() == {
        "error": {
            "code": "not_found",
            "message": "未找到工作流运行记录",
            "details": {"request_id": "missing-request-id"},
        }
    }


def test_request_config_injects_top_level_retrieval_settings(tmp_path: Path) -> None:
    service = TextToSQLApiService(
        database_url=f"sqlite:///{tmp_path / 'demo.db'}",
        llm_client=MockLLMClient(),
    )

    request_config = service._config_for_request(max_attempts=1, target_dialect="sqlite")
    retrieval_node = request_config.nodes["example_retrieval"].model_dump(mode="python")

    assert retrieval_node["examples_path"] == "configs/examples.yaml"
    assert retrieval_node["top_k"] == 5
    assert retrieval_node["strategy"] == "lexical_overlap"
