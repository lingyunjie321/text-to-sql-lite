import json
from pathlib import Path

from fastapi.testclient import TestClient

from text_to_sql_demo.llm.client import MockLLMClient
from text_to_sql_demo.main import create_app


def test_query_request_writes_api_and_workflow_logs_with_same_request_id(
    tmp_path: Path,
) -> None:
    log_file = tmp_path / "app.log"
    config_path = _write_logged_workflow_config(tmp_path, log_file)
    database_url = f"sqlite:///{tmp_path / 'demo.db'}"
    llm_client = MockLLMClient(
        responses={
            "light": "SELECT id, amount FROM orders ORDER BY id",
            "strong": "SELECT id, amount FROM orders ORDER BY id",
        }
    )
    client = TestClient(
        create_app(
            config_path=config_path,
            database_url=database_url,
            llm_client=llm_client,
        )
    )

    response = client.post(
        "/api/v1/query",
        json={"question": "列出订单金额", "target_dialect": "sqlite", "max_attempts": 1},
    )

    assert response.status_code == 200
    request_id = response.json()["request_id"]
    events = _read_json_lines(log_file)
    event_names = [event["event"] for event in events]
    assert "api.request.completed" in event_names
    assert "workflow.started" in event_names
    assert "workflow.node.completed" in event_names
    assert "workflow.completed" in event_names
    assert {
        event["request_id"]
        for event in events
        if event["event"] in {"api.request.completed", "workflow.started", "workflow.completed"}
    } == {request_id}


def _write_logged_workflow_config(tmp_path: Path, log_file: Path) -> Path:
    source = Path("workflow.yaml").read_text(encoding="utf-8")
    config_text = source.replace("path: logs/app.log", f"path: {log_file}")
    config_path = tmp_path / "workflow.yaml"
    config_path.write_text(config_text, encoding="utf-8")
    return config_path


def _read_json_lines(log_file: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in log_file.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

