from __future__ import annotations

from datetime import UTC, datetime, timedelta

from pydantic import SecretStr

from text_to_sql_demo.runtime import RuntimeConfigStore
from text_to_sql_demo.runtime.models import (
    RuntimeConfig,
    RuntimeConfigDisplay,
    RuntimeDatabaseConfig,
    RuntimeModelConfig,
    RuntimeModelRoutingConfig,
)

NOW = datetime(2026, 6, 23, tzinfo=UTC)


def make_config(expires_at: datetime) -> RuntimeConfig:
    """构造固定时间的运行时配置，避免测试依赖真实时钟。"""
    database = RuntimeDatabaseConfig(
        driver="sqlite",
        database_url=SecretStr("sqlite:///demo.db"),
        target_dialect="sqlite",
        display_name="Demo SQLite",
    )
    light_model = RuntimeModelConfig(
        provider="mock",
        model="light",
        api_key=SecretStr("test-key"),
    )
    strong_model = RuntimeModelConfig(
        provider="mock",
        model="strong",
        api_key_env="TEST_API_KEY",
    )
    return RuntimeConfig(
        id="runtime-1",
        expires_at=expires_at,
        database=database,
        models=RuntimeModelRoutingConfig(light=light_model, strong=strong_model),
        display=RuntimeConfigDisplay(
            database="Demo SQLite",
            models={"light": "mock/light", "strong": "mock/strong"},
        ),
    )


def test_runtime_store_returns_active_config() -> None:
    store = RuntimeConfigStore()
    config = make_config(NOW + timedelta(minutes=30))

    store.save(config)

    assert store.get("runtime-1", now=NOW) == config
    assert store.get_raw("runtime-1") == config


def test_runtime_store_hides_expired_config_and_prunes_it() -> None:
    store = RuntimeConfigStore()
    expired_config = make_config(NOW - timedelta(seconds=1))
    active_config = make_config(NOW + timedelta(minutes=30)).model_copy(update={"id": "runtime-2"})

    store.save(expired_config)
    store.save(active_config)

    assert store.get("runtime-1", now=NOW) is None
    assert store.get("missing", now=NOW) is None

    assert store.get_raw("runtime-1") == expired_config
    assert store.prune_expired(now=NOW) == 1
    assert store.get_raw("runtime-1") is None
    assert store.get("runtime-2", now=NOW) == active_config
