from __future__ import annotations

from datetime import datetime

import pytest
from pydantic import SecretStr, ValidationError

from text_to_sql_demo.runtime.models import (
    RuntimeConfig,
    RuntimeConfigDisplay,
    RuntimeCustomDatabaseInput,
    RuntimeDatabaseConfig,
    RuntimeDatabaseSelection,
    RuntimeModelConfig,
    RuntimeModelRoutingConfig,
    RuntimeModelSelection,
)


def make_sqlite_database_input() -> RuntimeCustomDatabaseInput:
    """构造合法 sqlite 自定义数据库输入。"""
    return RuntimeCustomDatabaseInput(driver="sqlite", sqlite_path="/tmp/demo.db")


def make_runtime_config(expires_at: datetime) -> RuntimeConfig:
    """构造最小合法运行时配置。"""
    model = RuntimeModelConfig(provider="mock", model="demo", api_key=SecretStr("sk-secret"))
    return RuntimeConfig(
        id="runtime-1",
        expires_at=expires_at,
        database=RuntimeDatabaseConfig(
            driver="sqlite",
            database_url=SecretStr("sqlite:////tmp/demo.db"),
            target_dialect="sqlite",
            display_name="Demo",
        ),
        models=RuntimeModelRoutingConfig(light=model, strong=model),
        display=RuntimeConfigDisplay(database="Demo", models={"light": "mock/demo"}),
    )


def test_database_selection_requires_either_preset_or_custom() -> None:
    custom_config = make_sqlite_database_input()

    assert RuntimeDatabaseSelection(mode="preset", preset_id="local-demo").preset_id == "local-demo"
    assert RuntimeDatabaseSelection(mode="custom", config=custom_config).config == custom_config

    with pytest.raises(ValidationError, match="数据库 preset 模式不能提供 config"):
        RuntimeDatabaseSelection(mode="preset", preset_id="local-demo", config=custom_config)

    with pytest.raises(ValidationError, match="数据库 custom 模式不能提供 preset_id"):
        RuntimeDatabaseSelection(mode="custom", preset_id="local-demo", config=custom_config)


def test_model_selection_requires_either_preset_or_custom() -> None:
    assert RuntimeModelSelection(mode="preset", preset_id="light").preset_id == "light"
    assert RuntimeModelSelection(
        mode="custom",
        provider="openai-compatible",
        model="demo",
        api_key_env="TEST_API_KEY",
    ).provider == "openai-compatible"

    with pytest.raises(ValidationError, match="模型 preset 模式不能提供自定义字段"):
        RuntimeModelSelection(mode="preset", preset_id="light", provider="mock", model="demo")

    with pytest.raises(ValidationError, match="模型 custom 模式不能提供 preset_id"):
        RuntimeModelSelection(
            mode="custom",
            preset_id="light",
            provider="mock",
            model="demo",
            api_key_env="TEST_API_KEY",
        )


def test_custom_service_database_missing_required_fields_fails() -> None:
    with pytest.raises(ValidationError, match="自定义服务型数据库缺少字段"):
        RuntimeCustomDatabaseInput(driver="postgresql", host="localhost")


def test_sqlite_custom_without_sqlite_path_fails() -> None:
    with pytest.raises(ValidationError, match="自定义 sqlite 数据库必须提供 sqlite_path"):
        RuntimeCustomDatabaseInput(driver="sqlite")


def test_custom_model_without_api_key_or_env_fails() -> None:
    with pytest.raises(ValidationError, match="api_key 或 api_key_env"):
        RuntimeModelSelection(mode="custom", provider="mock", model="demo")


def test_runtime_config_rejects_naive_expires_at() -> None:
    with pytest.raises(ValidationError, match="expires_at 必须包含时区信息"):
        make_runtime_config(datetime(2026, 6, 23))


def test_secret_str_output_does_not_expose_secrets() -> None:
    database = RuntimeCustomDatabaseInput(
        driver="postgresql",
        host="localhost",
        port=5432,
        database_name="demo",
        username="demo",
        password=SecretStr("db-password"),
    )
    model = RuntimeModelSelection(
        mode="custom",
        provider="mock",
        model="demo",
        api_key=SecretStr("sk-secret"),
    )

    combined_output = (
        f"{database!r} {database.model_dump_json()} "
        f"{model!r} {model.model_dump_json()}"
    )

    assert "db-password" not in combined_output
    assert "sk-secret" not in combined_output
    assert "**********" in combined_output
