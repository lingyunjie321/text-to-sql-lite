import json
from pathlib import Path

from fastapi.testclient import TestClient

from text_to_sql_demo.llm.client import MockLLMClient
from text_to_sql_demo.main import create_app


def test_missing_llm_credential_is_logged_without_secret(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.delenv("MISSING_LLM_API_KEY", raising=False)
    log_file = tmp_path / "app.log"
    config_path = _write_logged_workflow_config(
        tmp_path,
        log_file,
        replacements={
            "api_key_env: DEEPSEEK_API_KEY": "api_key_env: MISSING_LLM_API_KEY",
            "base_url_env: DEEPSEEK_BASE_URL": "base_url: https://example.test/v1/chat/completions",
        },
    )
    client = TestClient(
        create_app(
            config_path=config_path,
            database_url=f"sqlite:///{tmp_path / 'demo.db'}",
        )
    )

    response = client.post(
        "/api/v1/query",
        json={"question": "列出订单金额", "target_dialect": "sqlite", "max_attempts": 1},
    )

    assert response.status_code == 500
    events = _read_json_lines(log_file)
    event_names = [event["event"] for event in events]
    assert "service.initialization.failed" in event_names
    assert "llm.client.configure_failed" in event_names
    failed_event = _event_by_name(events, "llm.client.configure_failed")
    assert failed_event["error_type"] == "CredentialMissingError"
    log_text = log_file.read_text(encoding="utf-8")
    assert "sk-" not in log_text
    assert "MISSING_LLM_API_KEY" in log_text


def test_sql_validation_and_repair_exhaustion_are_logged_without_sql_preview(
    tmp_path: Path,
) -> None:
    log_file = tmp_path / "app.log"
    config_path = _write_logged_workflow_config(tmp_path, log_file)
    database_url = f"sqlite:///{tmp_path / 'demo.db'}"
    invalid_sql = "SELECT SUM(orders.total_amount) AS total FROM orders"
    client = TestClient(
        create_app(
            config_path=config_path,
            database_url=database_url,
            llm_client=MockLLMClient(responses={"light": invalid_sql, "strong": invalid_sql}),
        )
    )

    response = client.post(
        "/api/v1/query",
        json={"question": "统计订单金额", "target_dialect": "sqlite", "max_attempts": 1},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "needs_human_review"
    assert response.json()["hitl_required"] is True
    events = _read_json_lines(log_file)
    event_names = [event["event"] for event in events]
    assert "sql.validation.failed" in event_names
    assert "repair.attempted" in event_names
    assert "repair.exhausted" in event_names
    validation_event = _event_by_name(events, "sql.validation.failed")
    assert validation_event["sql_hash"]
    assert validation_event["sql_length"] == len(invalid_sql)
    assert "sql_preview" not in validation_event


def _write_logged_workflow_config(
    tmp_path: Path,
    log_file: Path,
    replacements: dict[str, str] | None = None,
) -> Path:
    source = Path("workflow.yaml").read_text(encoding="utf-8")
    config_text = source.replace("path: logs/app.log", f"path: {log_file}")
    for old, new in (replacements or {}).items():
        config_text = config_text.replace(old, new)
    config_path = tmp_path / "workflow.yaml"
    config_path.write_text(config_text, encoding="utf-8")
    return config_path


def _read_json_lines(log_file: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in log_file.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _event_by_name(events: list[dict], event_name: str) -> dict:
    for event in events:
        if event["event"] == event_name:
            return event
    raise AssertionError(f"missing log event: {event_name}")
