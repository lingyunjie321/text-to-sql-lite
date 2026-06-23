from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from text_to_sql_demo.config.models import ModelAliasConfig, WorkflowConfig
from text_to_sql_demo.llm.client import LLMClient, MockLLMClient
from text_to_sql_demo.llm.models import ModelProfile
from text_to_sql_demo.llm.providers import OpenAICompatibleLLMClient
from text_to_sql_demo.llm.routing import RoutingLLMClient
from text_to_sql_demo.runtime.exceptions import (
    RuntimeConfigExpiredError,
    RuntimeConfigNotFoundError,
    RuntimeProviderUnsupportedError,
    RuntimeSecretMissingError,
)
from text_to_sql_demo.runtime.models import RuntimeDriver, RuntimeModelConfig
from text_to_sql_demo.runtime.store import RuntimeConfigStore
from text_to_sql_demo.sql.dialect import DialectName

DEFAULT_OPENAI_COMPATIBLE_BASE_URL = "https://api.openai.com/v1/chat/completions"
DRIVER_TO_DIALECT: dict[RuntimeDriver, DialectName] = {
    "sqlite": "sqlite",
    "postgresql": "postgres",
    "mysql": "mysql",
}
RUNTIME_MODEL_ALIASES = ("light", "strong")
MOCK_PROVIDER = "mock"
OPENAI_COMPATIBLE_PROVIDER = "openai_compatible"


@dataclass(frozen=True)
class ResolvedRuntimeConfig:
    """工作流执行前解析完成的数据库、方言与模型依赖。"""

    database_url: str
    target_dialect: DialectName
    llm_client: LLMClient
    model_profiles: dict[str, ModelProfile]
    runtime_config_id: str | None = None


class RuntimeConfigResolver:
    """把可选运行时配置解析为工作流可直接使用的依赖。"""

    def __init__(
        self,
        *,
        workflow_config: WorkflowConfig,
        store: RuntimeConfigStore,
        default_database_url: str,
        default_llm_client: LLMClient,
        now_provider: Callable[[], datetime] | None = None,
    ) -> None:
        self.workflow_config = workflow_config
        self.store = store
        self.default_database_url = default_database_url
        self.default_llm_client = default_llm_client
        self.now_provider = now_provider or (lambda: datetime.now(UTC))

    def resolve(self, runtime_config_id: str | None = None) -> ResolvedRuntimeConfig:
        """解析默认配置或指定的短生命周期运行时配置。"""
        if runtime_config_id is None:
            default_connection = self.workflow_config.database.connections[
                self.workflow_config.database.default
            ]
            return ResolvedRuntimeConfig(
                database_url=self.default_database_url,
                target_dialect=driver_to_dialect(default_connection.driver),
                llm_client=self.default_llm_client,
                model_profiles=_workflow_model_profiles(self.workflow_config),
            )

        raw_config = self.store.get_raw(runtime_config_id)
        if raw_config is None:
            raise RuntimeConfigNotFoundError(f"运行时配置不存在: {runtime_config_id}")

        active_config = self.store.get(runtime_config_id, now=self.now_provider())
        if active_config is None:
            raise RuntimeConfigExpiredError(f"运行时配置已过期: {runtime_config_id}")

        runtime_models = {
            alias: getattr(active_config.models, alias)
            for alias in RUNTIME_MODEL_ALIASES
        }
        return ResolvedRuntimeConfig(
            database_url=active_config.database.database_url.get_secret_value(),
            target_dialect=active_config.database.target_dialect,
            llm_client=RoutingLLMClient(
                clients_by_alias={
                    alias: self._build_llm_client(model_config)
                    for alias, model_config in runtime_models.items()
                }
            ),
            model_profiles={
                alias: _runtime_model_profile(alias, model_config)
                for alias, model_config in runtime_models.items()
            },
            runtime_config_id=active_config.id,
        )

    def _build_llm_client(self, model_config: RuntimeModelConfig) -> LLMClient:
        """按运行时模型 provider 创建实际 LLM client。"""
        if model_config.provider == MOCK_PROVIDER:
            return MockLLMClient()

        if model_config.provider == OPENAI_COMPATIBLE_PROVIDER:
            api_key = _resolve_api_key(model_config)
            if not api_key:
                raise RuntimeSecretMissingError("运行时 openai_compatible 模型缺少 API key")
            return OpenAICompatibleLLMClient(
                api_key=api_key,
                base_url=model_config.base_url or DEFAULT_OPENAI_COMPATIBLE_BASE_URL,
            )

        raise RuntimeProviderUnsupportedError(
            f"不支持的运行时模型 provider: {model_config.provider}"
        )


def driver_to_dialect(driver: RuntimeDriver) -> DialectName:
    """把数据库 driver 映射为 SQLGlot 方言名。"""
    return DRIVER_TO_DIALECT[driver]


def _workflow_model_profiles(config: WorkflowConfig) -> dict[str, ModelProfile]:
    """把 workflow 模型 alias 配置转换为节点使用的 ModelProfile。"""
    return {
        alias: _workflow_model_profile(alias, model_config)
        for alias, model_config in config.models.aliases.items()
    }


def _workflow_model_profile(alias: str, model_config: ModelAliasConfig) -> ModelProfile:
    return ModelProfile(
        alias=alias,
        provider=model_config.provider,
        model_name=model_config.model,
        temperature=model_config.temperature,
        max_tokens=model_config.max_tokens,
    )


def _runtime_model_profile(alias: str, model_config: RuntimeModelConfig) -> ModelProfile:
    return ModelProfile(
        alias=alias,
        provider=model_config.provider,
        model_name=model_config.model,
        temperature=model_config.temperature,
        max_tokens=model_config.max_tokens,
    )


def _resolve_api_key(model_config: RuntimeModelConfig) -> str | None:
    if model_config.api_key is not None:
        return model_config.api_key.get_secret_value()
    if model_config.api_key_env:
        return os.getenv(model_config.api_key_env)
    return None


__all__ = [
    "DRIVER_TO_DIALECT",
    "ResolvedRuntimeConfig",
    "RuntimeConfigResolver",
    "driver_to_dialect",
]
