from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from text_to_sql_demo.llm.client import LLMClient, MockLLMClient
from text_to_sql_demo.main import create_app
from text_to_sql_demo.runtime.store import RuntimeConfigStore


def build_client_with_store(
    *,
    llm_client: LLMClient | None = None,
) -> tuple[TestClient, RuntimeConfigStore]:
    """创建带共享 runtime store 的测试客户端。"""
    store = RuntimeConfigStore()
    app = create_app(llm_client=llm_client or MockLLMClient(), runtime_store=store)
    return TestClient(app), store


def assert_no_secrets(value: object) -> None:
    """递归后的字符串内容不应包含真实密钥或密码字段。"""
    rendered = str(value).lower()
    assert "sk-secret" not in rendered
    assert "db-password" not in rendered
    assert "api_key" not in rendered
    assert "password" not in rendered


def test_runtime_options_returns_desensitized_database_and_model_presets() -> None:
    client, _store = build_client_with_store()

    response = client.get("/api/v1/runtime/options")

    assert response.status_code == 200
    payload = response.json()
    database_presets = payload["database_presets"]
    model_presets = payload["model_presets"]
    assert any(item["id"] == "demo_sqlite" for item in database_presets)
    assert [item["id"] for item in model_presets["light"]] == ["light"]
    assert [item["id"] for item in model_presets["strong"]] == ["strong"]
    assert_no_secrets(payload)


def test_create_runtime_config_with_preset_database_and_custom_mock_models() -> None:
    client, store = build_client_with_store()

    response = client.post(
        "/api/v1/runtime/configs",
        json={
            "database": {"mode": "preset", "preset_id": "demo_sqlite"},
            "models": {
                "light": {
                    "mode": "custom",
                    "provider": "mock",
                    "model": "runtime-light",
                    "api_key_env": "MOCK_RUNTIME_KEY",
                },
                "strong": {
                    "mode": "custom",
                    "provider": "mock",
                    "model": "runtime-strong",
                    "api_key_env": "MOCK_RUNTIME_KEY",
                },
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()
    runtime_config_id = payload["runtime_config_id"]
    assert runtime_config_id.startswith("rt_")
    assert payload["expires_at"]
    assert payload["database"]["display_name"] == "demo_sqlite"
    assert payload["database"]["driver"] == "sqlite"
    assert {"customers", "orders", "products"} <= set(payload["database"]["tables"])
    assert payload["models"] == {
        "light": {"provider": "mock", "model": "runtime-light"},
        "strong": {"provider": "mock", "model": "runtime-strong"},
    }
    config = store.get_raw(runtime_config_id)
    assert config is not None
    ttl_seconds = (config.expires_at - datetime.now(UTC)).total_seconds()
    assert 7100 <= ttl_seconds <= 7200
    assert_no_secrets(payload)


def test_runtime_validation_error_does_not_echo_secret_inputs() -> None:
    client, _store = build_client_with_store()

    response = client.post(
        "/api/v1/runtime/configs",
        json={
            "database": {
                "mode": "preset",
                "preset_id": "demo_sqlite",
                "config": {
                    "driver": "postgresql",
                    "host": "localhost",
                    "port": 5432,
                    "database_name": "demo",
                    "username": "demo",
                    "password": "db-password",
                },
            },
            "models": {
                "light": {
                    "mode": "preset",
                    "preset_id": "light",
                    "api_key": "sk-secret",
                },
                "strong": {
                    "mode": "custom",
                    "provider": "mock",
                    "model": "runtime-strong",
                    "api_key_env": "MOCK_RUNTIME_KEY",
                },
            },
        },
    )

    assert response.status_code == 422
    payload = response.json()
    assert payload["error"]["code"] == "validation_error"
    assert_no_secrets(payload)
    assert "input" not in str(payload).lower()


def test_runtime_custom_model_rejects_blank_inline_api_key_without_echoing_input() -> None:
    client, _store = build_client_with_store()

    response = client.post(
        "/api/v1/runtime/configs",
        json={
            "database": {"mode": "preset", "preset_id": "demo_sqlite"},
            "models": {
                "light": {
                    "mode": "custom",
                    "provider": "mock",
                    "model": "runtime-light",
                    "api_key": "   ",
                    "api_key_env": "MOCK_RUNTIME_KEY",
                },
                "strong": {
                    "mode": "custom",
                    "provider": "mock",
                    "model": "runtime-strong",
                    "api_key_env": "MOCK_RUNTIME_KEY",
                },
            },
        },
    )

    assert response.status_code == 422
    payload = response.json()
    assert payload["error"]["code"] == "validation_error"
    assert_no_secrets(payload)
    assert "input" not in str(payload).lower()


def test_runtime_connection_error_uses_unified_response_without_secrets(tmp_path: Path) -> None:
    client, _store = build_client_with_store()
    missing_parent = tmp_path / "missing" / "secret-db-password.db"

    response = client.post(
        "/api/v1/runtime/configs",
        json={
            "database": {
                "mode": "custom",
                "config": {
                    "driver": "sqlite",
                    "sqlite_path": str(missing_parent),
                    "display_name": "Broken SQLite",
                },
            },
            "models": {
                "light": {
                    "mode": "custom",
                    "provider": "mock",
                    "model": "runtime-light",
                    "api_key_env": "MOCK_RUNTIME_KEY",
                },
                "strong": {
                    "mode": "custom",
                    "provider": "mock",
                    "model": "runtime-strong",
                    "api_key_env": "MOCK_RUNTIME_KEY",
                },
            },
        },
    )

    assert response.status_code == 400
    payload = response.json()
    assert payload["error"]["code"] == "runtime_connection_failed"
    assert_no_secrets(payload)
    assert "secret-db-password" not in str(payload)
