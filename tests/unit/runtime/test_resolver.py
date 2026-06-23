from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import SecretStr

from text_to_sql_demo.config.models import (
    DatabaseConfig,
    DatabaseConnectionConfig,
    ModelAliasConfig,
    ModelsConfig,
    NodeConfig,
    WorkflowConfig,
    WorkflowSection,
)
from text_to_sql_demo.llm.client import MockLLMClient
from text_to_sql_demo.runtime.exceptions import (
    RuntimeConfigExpiredError,
    RuntimeConfigNotFoundError,
    RuntimeProviderUnsupportedError,
    RuntimeSecretMissingError,
)
from text_to_sql_demo.runtime.models import (
    RuntimeConfig,
    RuntimeConfigDisplay,
    RuntimeDatabaseConfig,
    RuntimeModelConfig,
    RuntimeModelRoutingConfig,
)
from text_to_sql_demo.runtime.resolver import (
    RuntimeConfigResolver,
    driver_to_dialect,
)
from text_to_sql_demo.runtime.store import RuntimeConfigStore

NOW = datetime(2026, 6, 23, tzinfo=UTC)


def make_workflow_config(driver: str = "sqlite") -> WorkflowConfig:
    """构造只包含 resolver 所需字段的 workflow 配置。"""
    return WorkflowConfig(
        workflow=WorkflowSection(name="test", start_node="generate_sql"),
        database=DatabaseConfig(
            default="demo",
            connections={"demo": DatabaseConnectionConfig(driver=driver)},
        ),
        models=ModelsConfig(
            aliases={
                "light": ModelAliasConfig(provider="mock", model="workflow-light"),
                "strong": ModelAliasConfig(provider="mock", model="workflow-strong"),
            }
        ),
        nodes={"generate_sql": NodeConfig(type="generate_sql")},
    )


def make_runtime_config(
    *,
    config_id: str = "runtime-1",
    expires_at: datetime = NOW + timedelta(minutes=10),
    provider: str = "mock",
) -> RuntimeConfig:
    """构造可解析的运行时配置。"""
    return RuntimeConfig(
        id=config_id,
        expires_at=expires_at,
        database=RuntimeDatabaseConfig(
            driver="postgresql",
            database_url=SecretStr("postgresql://demo:secret@localhost/demo"),
            target_dialect="postgres",
            display_name="Runtime Postgres",
        ),
        models=RuntimeModelRoutingConfig(
            light=RuntimeModelConfig(
                provider=provider,
                model="runtime-light",
                api_key=SecretStr("test-key"),
            ),
            strong=RuntimeModelConfig(
                provider=provider,
                model="runtime-strong",
                api_key=SecretStr("test-key"),
            ),
        ),
        display=RuntimeConfigDisplay(
            database="Runtime Postgres",
            models={"light": "mock/runtime-light", "strong": "mock/runtime-strong"},
        ),
    )


def make_openai_runtime_config(
    *,
    light: RuntimeModelConfig,
    strong: RuntimeModelConfig | None = None,
) -> RuntimeConfig:
    """构造 openai_compatible 运行时配置，便于测试密钥解析边界。"""
    return make_runtime_config(provider="openai_compatible").model_copy(
        update={
            "models": RuntimeModelRoutingConfig(
                light=light,
                strong=strong
                or RuntimeModelConfig(
                    provider="openai_compatible",
                    model="runtime-strong",
                    api_key=SecretStr("test-key"),
                ),
            )
        }
    )


def make_resolver(store: RuntimeConfigStore) -> RuntimeConfigResolver:
    """创建带固定时钟的 resolver。"""
    return RuntimeConfigResolver(
        workflow_config=make_workflow_config(),
        store=store,
        default_database_url="sqlite:///default.db",
        default_llm_client=MockLLMClient(),
        now_provider=lambda: NOW,
    )


@pytest.mark.parametrize(
    ("driver", "dialect"),
    [
        ("sqlite", "sqlite"),
        ("postgresql", "postgres"),
        ("mysql", "mysql"),
    ],
)
def test_driver_to_dialect_maps_supported_drivers(driver: str, dialect: str) -> None:
    assert driver_to_dialect(driver) == dialect


def test_resolve_without_runtime_id_uses_default_dependencies() -> None:
    default_client = MockLLMClient()
    resolver = RuntimeConfigResolver(
        workflow_config=make_workflow_config(),
        store=RuntimeConfigStore(),
        default_database_url="sqlite:///default.db",
        default_llm_client=default_client,
        now_provider=lambda: NOW,
    )

    resolved = resolver.resolve()

    assert resolved.runtime_config_id is None
    assert resolved.database_url == "sqlite:///default.db"
    assert resolved.target_dialect == "sqlite"
    assert resolved.llm_client is default_client
    assert resolved.model_profiles["light"].model_name == "workflow-light"
    assert resolved.model_profiles["strong"].model_name == "workflow-strong"


def test_resolve_without_runtime_id_uses_default_workflow_driver_dialect() -> None:
    resolver = RuntimeConfigResolver(
        workflow_config=make_workflow_config(driver="postgresql"),
        store=RuntimeConfigStore(),
        default_database_url="postgresql://demo:secret@localhost/demo",
        default_llm_client=MockLLMClient(),
        now_provider=lambda: NOW,
    )

    resolved = resolver.resolve()

    assert resolved.target_dialect == "postgres"


def test_resolve_runtime_config_uses_runtime_database_models_and_routing_client() -> None:
    store = RuntimeConfigStore()
    store.save(make_runtime_config())
    resolver = make_resolver(store)

    resolved = resolver.resolve(runtime_config_id="runtime-1")

    assert resolved.runtime_config_id == "runtime-1"
    assert resolved.database_url == "postgresql://demo:secret@localhost/demo"
    assert resolved.target_dialect == "postgres"
    assert resolved.model_profiles["light"].model_name == "runtime-light"
    assert resolved.model_profiles["strong"].model_name == "runtime-strong"
    assert set(resolved.llm_client.clients_by_alias) == {"light", "strong"}


def test_missing_runtime_config_raises_not_found() -> None:
    resolver = make_resolver(RuntimeConfigStore())

    with pytest.raises(RuntimeConfigNotFoundError):
        resolver.resolve(runtime_config_id="missing")


def test_expired_runtime_config_raises_expired() -> None:
    store = RuntimeConfigStore()
    store.save(make_runtime_config(expires_at=NOW - timedelta(seconds=1)))
    resolver = make_resolver(store)

    with pytest.raises(RuntimeConfigExpiredError):
        resolver.resolve(runtime_config_id="runtime-1")


def test_unsupported_provider_raises_provider_unsupported() -> None:
    store = RuntimeConfigStore()
    store.save(make_runtime_config(provider="unknown"))
    resolver = make_resolver(store)

    with pytest.raises(RuntimeProviderUnsupportedError):
        resolver.resolve(runtime_config_id="runtime-1")


def test_openai_compatible_missing_api_key_raises_secret_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("MISSING_RUNTIME_API_KEY", raising=False)
    config = make_openai_runtime_config(
        light=RuntimeModelConfig(
            provider="openai_compatible",
            model="runtime-light",
            api_key_env="MISSING_RUNTIME_API_KEY",
        )
    )
    store = RuntimeConfigStore()
    store.save(config)
    resolver = make_resolver(store)

    with pytest.raises(RuntimeSecretMissingError):
        resolver.resolve(runtime_config_id="runtime-1")


def test_openai_compatible_whitespace_api_key_raises_secret_missing() -> None:
    config = make_openai_runtime_config(
        light=RuntimeModelConfig(
            provider="openai_compatible",
            model="runtime-light",
            api_key=SecretStr("   "),
        )
    )
    store = RuntimeConfigStore()
    store.save(config)
    resolver = make_resolver(store)

    with pytest.raises(RuntimeSecretMissingError):
        resolver.resolve(runtime_config_id="runtime-1")


def test_openai_compatible_whitespace_env_api_key_raises_secret_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("WHITESPACE_RUNTIME_API_KEY", "   ")
    config = make_openai_runtime_config(
        light=RuntimeModelConfig(
            provider="openai_compatible",
            model="runtime-light",
            api_key_env="WHITESPACE_RUNTIME_API_KEY",
        )
    )
    store = RuntimeConfigStore()
    store.save(config)
    resolver = make_resolver(store)

    with pytest.raises(RuntimeSecretMissingError):
        resolver.resolve(runtime_config_id="runtime-1")
