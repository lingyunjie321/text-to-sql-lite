from __future__ import annotations

import os

from text_to_sql_demo.config.env import load_env_files
from text_to_sql_demo.config.models import ModelAliasConfig, WorkflowConfig
from text_to_sql_demo.llm.client import LLMClient, MockLLMClient
from text_to_sql_demo.llm.providers import OpenAICompatibleLLMClient

DEFAULT_OPENAI_CHAT_COMPLETIONS_URL = "https://api.openai.com/v1/chat/completions"
DEFAULT_OPENAI_API_KEY_ENV = "OPENAI_API_KEY"
DEFAULT_OPENAI_BASE_URL_ENV = "OPENAI_BASE_URL"
MOCK_PROVIDER = "mock"
OPENAI_COMPATIBLE_PROVIDER = "openai_compatible"


def build_llm_client(config: WorkflowConfig) -> LLMClient:
    """根据 workflow 配置构造默认 LLM client。"""
    load_env_files()
    aliases = list(config.models.aliases.values())
    providers = {alias.provider for alias in aliases}

    if not aliases or providers == {MOCK_PROVIDER}:
        return MockLLMClient()

    if providers == {OPENAI_COMPATIBLE_PROVIDER}:
        provider_config = aliases[0]
        api_key_env = provider_config.api_key_env or DEFAULT_OPENAI_API_KEY_ENV
        api_key = os.getenv(api_key_env)
        if not api_key:
            raise ValueError(
                f"启用 openai_compatible provider 需要设置环境变量 {api_key_env}"
            )

        return OpenAICompatibleLLMClient(
            api_key=api_key,
            base_url=_resolve_base_url(provider_config),
            timeout_seconds=provider_config.timeout_seconds,
        )

    supported = ", ".join(sorted({MOCK_PROVIDER, OPENAI_COMPATIBLE_PROVIDER}))
    configured = ", ".join(sorted(providers)) or "空"
    raise ValueError(f"不支持混合或未知 LLM provider: {configured}; 支持: {supported}")


def _resolve_base_url(config: ModelAliasConfig) -> str:
    """按显式配置、环境变量、默认 endpoint 的顺序解析 base_url。"""
    if config.base_url:
        return config.base_url

    base_url_env = config.base_url_env or DEFAULT_OPENAI_BASE_URL_ENV
    return os.getenv(base_url_env) or DEFAULT_OPENAI_CHAT_COMPLETIONS_URL
