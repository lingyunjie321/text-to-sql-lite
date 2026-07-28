from pathlib import Path

import pytest
from pydantic import ValidationError

from app.config import LLMSettings, load_llm_settings


def test_llm_settings_are_strict_and_secret_safe() -> None:
    settings = LLMSettings(
        base_url="https://models.example.test/v1",
        api_key="stage5-test-secret",
        model="  model-a  ",
    )

    assert str(settings.base_url) == "https://models.example.test/v1"
    assert settings.model == "model-a"
    assert settings.timeout_seconds == 30
    assert settings.temperature == 0
    assert settings.api_key_value == "stage5-test-secret"
    assert "stage5-test-secret" not in repr(settings)


def test_load_llm_settings_reads_an_explicit_env_file(
    tmp_path: Path,
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "LLM_BASE_URL=https://models.example.test/v1\n"
        "LLM_API_KEY=stage5-test-secret\n"
        "LLM_MODEL=model-a\n",
        encoding="utf-8",
    )

    settings = load_llm_settings(env_file)

    assert settings.model == "model-a"
    assert settings.api_key_value == "stage5-test-secret"


def test_llm_settings_require_all_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in ("LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL"):
        monkeypatch.delenv(name, raising=False)

    with pytest.raises(ValidationError):
        LLMSettings()


@pytest.mark.parametrize(
    "base_url",
    [
        "ftp://models.example.test/v1",
        "http://models.example.test/v1",
        "https://user:password@models.example.test/v1",
        "https://models.example.test/v1?debug=true",
        "https://models.example.test/v1#fragment",
    ],
)
def test_llm_settings_reject_unsafe_base_urls(base_url: str) -> None:
    with pytest.raises(ValidationError):
        LLMSettings(
            base_url=base_url,
            api_key="stage5-test-secret",
            model="model-a",
        )


@pytest.mark.parametrize(
    "base_url",
    [
        "http://localhost:8000/v1",
        "http://127.0.0.1:8000/v1",
        "http://[::1]:8000/v1",
    ],
)
def test_llm_settings_allow_http_only_for_loopback(
    base_url: str,
) -> None:
    settings = LLMSettings(
        base_url=base_url,
        api_key="stage5-test-secret",
        model="model-a",
    )

    assert settings.base_url.scheme == "http"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("api_key", "   "),
        ("api_key", "secret\nInjected: value"),
        ("api_key", "secret-🔒"),
        ("model", "   "),
        ("timeout_seconds", 0),
        ("timeout_seconds", 31),
        ("temperature", 0.1),
    ],
)
def test_llm_settings_reject_invalid_values(
    field: str,
    value: object,
) -> None:
    values: dict[str, object] = {
        "base_url": "https://models.example.test/v1",
        "api_key": "stage5-test-secret",
        "model": "model-a",
    }
    values[field] = value

    with pytest.raises(ValidationError):
        LLMSettings(**values)
