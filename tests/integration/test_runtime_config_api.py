from __future__ import annotations

from fastapi.testclient import TestClient

from text_to_sql_demo.llm.client import MockLLMClient
from text_to_sql_demo.main import create_app
from text_to_sql_demo.runtime.store import RuntimeConfigStore


def build_client_with_store() -> tuple[TestClient, RuntimeConfigStore]:
    """创建带共享 runtime store 的测试客户端。"""
    store = RuntimeConfigStore()
    app = create_app(llm_client=MockLLMClient(), runtime_store=store)
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
    assert model_presets["light"]["id"] == "light"
    assert model_presets["strong"]["id"] == "strong"
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
            "ttl_seconds": 7200,
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
    assert store.get_raw(runtime_config_id) is not None
    assert_no_secrets(payload)
