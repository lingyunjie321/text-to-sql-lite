import os
from pathlib import Path

import pytest

from text_to_sql_demo.config.env import load_env_files
from text_to_sql_demo.config.models import WorkflowConfig
from text_to_sql_demo.llm.client import MockLLMClient
from text_to_sql_demo.llm.factory import build_llm_client
from text_to_sql_demo.llm.providers import OpenAICompatibleLLMClient


def make_config(provider: str = "mock") -> WorkflowConfig:
    return WorkflowConfig.model_validate(
        {
            "workflow": {
                "name": "test",
                "start_node": "sql_generation",
                "max_steps": 10,
                "max_repair_attempts": 3,
            },
            "database": {
                "default": "demo",
                "connections": {
                    "demo": {
                        "driver": "sqlite",
                        "fallback_url": "sqlite:///demo.db",
                    }
                },
            },
            "models": {
                "aliases": {
                    "light": {
                        "provider": provider,
                        "model": "light-model",
                        "temperature": 0.0,
                        "max_tokens": 256,
                    },
                    "strong": {
                        "provider": provider,
                        "model": "strong-model",
                        "temperature": 0.0,
                        "max_tokens": 512,
                    },
                }
            },
            "nodes": {"sql_generation": {"type": "sql_generation"}},
        }
    )


def test_build_llm_client_returns_mock_by_default() -> None:
    client = build_llm_client(make_config())

    assert isinstance(client, MockLLMClient)


def test_build_openai_compatible_client_requires_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    config = make_config(provider="openai_compatible")

    with pytest.raises(ValueError) as exc_info:
        build_llm_client(config)

    message = str(exc_info.value)
    assert "OPENAI_API_KEY" in message
    assert "sk-" not in message


def test_build_openai_compatible_client_reads_env_without_printing_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-secret-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.test/v1/chat/completions")
    config = make_config(provider="openai_compatible")

    client = build_llm_client(config)

    assert isinstance(client, OpenAICompatibleLLMClient)
    assert client.base_url == "https://example.test/v1/chat/completions"
    assert client.timeout_seconds == 30


def test_load_env_files_reads_local_file_without_overriding_existing_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env_file = tmp_path / ".env.local"
    env_file.write_text(
        "\n".join(
            [
                "OPENAI_API_KEY=file-secret",
                "OPENAI_BASE_URL=https://file.example/v1/chat/completions",
                "TEXT_TO_SQL_WORKFLOW_CONFIG=workflow.yaml",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("OPENAI_API_KEY", "existing-secret")
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)

    load_env_files([env_file])

    assert os.environ["OPENAI_API_KEY"] == "existing-secret"
    assert os.environ["OPENAI_BASE_URL"] == "https://file.example/v1/chat/completions"
