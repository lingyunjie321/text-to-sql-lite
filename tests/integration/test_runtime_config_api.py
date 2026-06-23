from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

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


def create_runtime_sqlite_database(database_path: Path) -> None:
    """创建只包含 runtime 测试表的 SQLite 数据库，便于区分默认 demo 库。"""
    engine = create_engine(f"sqlite:///{database_path}")
    try:
        with engine.begin() as connection:
            connection.execute(
                text("CREATE TABLE runtime_items (id INTEGER PRIMARY KEY, name TEXT NOT NULL)")
            )
            connection.execute(
                text("INSERT INTO runtime_items (id, name) VALUES (1, 'runtime-row')")
            )
    finally:
        engine.dispose()


def create_runtime_config(client: TestClient, database_path: Path) -> str:
    """通过公开 API 创建 runtime config，并返回可用于业务接口的 id。"""
    response = client.post(
        "/api/v1/runtime/configs",
        json={
            "database": {
                "mode": "custom",
                "config": {
                    "driver": "sqlite",
                    "sqlite_path": str(database_path),
                    "display_name": "Runtime SQLite",
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
    assert response.status_code == 200
    return str(response.json()["runtime_config_id"])


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


def test_runtime_custom_model_missing_secret_source_uses_neutral_validation_message() -> None:
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


def test_query_uses_runtime_config_database_and_models(tmp_path: Path) -> None:
    default_llm_client = MockLLMClient(default_response="SELECT id FROM orders ORDER BY id")
    client, _store = build_client_with_store(llm_client=default_llm_client)
    runtime_db_path = tmp_path / "runtime.db"
    create_runtime_sqlite_database(runtime_db_path)
    runtime_config_id = create_runtime_config(client, runtime_db_path)

    response = client.post(
        "/api/v1/query",
        json={
            "question": "返回常量 1",
            "runtime_config_id": runtime_config_id,
            "target_dialect": "mysql",
            "max_attempts": 1,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "success"
    assert payload["final_sql"] == "SELECT 1"
    assert payload["result"]["rows"] == [{"1": 1}]
    assert default_llm_client.requests == []


def test_schema_uses_runtime_config_database(tmp_path: Path) -> None:
    client, _store = build_client_with_store()
    runtime_db_path = tmp_path / "runtime.db"
    create_runtime_sqlite_database(runtime_db_path)
    runtime_config_id = create_runtime_config(client, runtime_db_path)

    response = client.get(
        "/api/v1/schema",
        params={"runtime_config_id": runtime_config_id},
    )

    assert response.status_code == 200
    tables = response.json()["tables"]
    assert set(tables) == {"runtime_items"}
    assert list(tables["runtime_items"]["columns"]) == ["id", "name"]


def test_execute_sql_uses_runtime_config_database(tmp_path: Path) -> None:
    client, _store = build_client_with_store()
    runtime_db_path = tmp_path / "runtime.db"
    create_runtime_sqlite_database(runtime_db_path)
    runtime_config_id = create_runtime_config(client, runtime_db_path)

    response = client.post(
        "/api/v1/sql/execute",
        json={
            "sql": "SELECT name FROM runtime_items ORDER BY id",
            "runtime_config_id": runtime_config_id,
            "target_dialect": "mysql",
            "max_rows": 5,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "success"
    assert payload["result"]["columns"] == ["name"]
    assert payload["result"]["rows"] == [{"name": "runtime-row"}]


def test_query_missing_runtime_config_id_uses_unified_error_response() -> None:
    client, _store = build_client_with_store()

    response = client.post(
        "/api/v1/query",
        json={"question": "列出订单", "runtime_config_id": "rt_missing"},
    )

    assert response.status_code == 404
    assert response.json() == {
        "error": {
            "code": "runtime_config_not_found",
            "message": "运行时配置不存在",
            "details": {"runtime_config_id": "rt_missing"},
        }
    }
