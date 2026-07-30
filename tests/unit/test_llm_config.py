from pathlib import Path

import pytest
from pydantic import ValidationError

from app.config import (
    LLMSettings,
    load_embedding_settings,
    load_llm_route_settings,
    load_llm_settings,
)


def test_default_loaders_read_project_dotenv(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / ".env").write_text(
        "LLM_BASE_URL=https://models.example.test/v1\n"
        "LLM_API_KEY=default-loader-test-secret\n"
        "LLM_MODEL=default-model\n"
        "EMBEDDING_BASE_URL=https://embedding.example.test/v1\n"
        "EMBEDDING_API_KEY=default-embedding-test-secret\n"
        "EMBEDDING_MODEL=text-embedding-v4\n"
        "EMBEDDING_DIMENSION=1024\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    routes = load_llm_route_settings()
    embedding = load_embedding_settings()

    assert routes.simple.model == "default-model"
    assert routes.standard.model == "default-model"
    assert routes.complex.model == "default-model"
    assert embedding.model == "text-embedding-v4"
    assert embedding.dimension == 1024


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
    assert settings.max_input_tokens == 32_768
    assert settings.max_output_tokens == 2_048
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


def test_route_settings_overlay_server_owned_models_without_copying_secret(
    tmp_path: Path,
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "LLM_BASE_URL=https://models.example.test/v1\n"
        "LLM_API_KEY=shared-test-secret\n"
        "LLM_MODEL=simple-model\n"
        "LLM_STANDARD_MODEL=standard-model\n"
        "LLM_COMPLEX_MODEL=complex-model\n"
        "LLM_FALLBACK_MODEL=fallback-model\n"
        "MODEL_ROUTING_COMPLEX_FALLBACK_ENABLED=true\n"
        "MODEL_ROUTING_DATA_BOUNDARY_ID=cn-approved-v1\n",
        encoding="utf-8",
    )

    settings = load_llm_route_settings(env_file)

    assert settings.simple.model == "simple-model"
    assert settings.standard.model == "standard-model"
    assert settings.complex.model == "complex-model"
    assert settings.fallback is not None
    assert settings.fallback.model == "fallback-model"
    assert settings.fallback_route_ids == ("complex_route",)
    assert settings.data_boundary_id == "cn-approved-v1"
    assert {
        route.api_key_value
        for route in (
            settings.simple,
            settings.standard,
            settings.complex,
            settings.fallback,
        )
    } == {"shared-test-secret"}
    assert "shared-test-secret" not in repr(settings)


def test_route_settings_default_all_routes_to_legacy_primary(
    tmp_path: Path,
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "LLM_BASE_URL=https://models.example.test/v1\n"
        "LLM_API_KEY=shared-test-secret\n"
        "LLM_MODEL=primary-model\n",
        encoding="utf-8",
    )

    settings = load_llm_route_settings(env_file)

    assert settings.simple == settings.standard == settings.complex
    assert settings.fallback is None
    assert settings.fallback_route_ids == ()


@pytest.mark.parametrize(
    "extra",
    (
        "LLM_FALLBACK_MODEL=fallback-model\n",
        "MODEL_ROUTING_SIMPLE_FALLBACK_ENABLED=true\n",
        (
            "LLM_FALLBACK_MODEL=fallback-model\n"
            "LLM_FALLBACK_MAX_INPUT_TOKENS=65536\n"
            "MODEL_ROUTING_SIMPLE_FALLBACK_ENABLED=true\n"
        ),
    ),
)
def test_route_settings_reject_incomplete_or_incompatible_fallback(
    tmp_path: Path,
    extra: str,
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "LLM_BASE_URL=https://models.example.test/v1\n"
        "LLM_API_KEY=shared-test-secret\n"
        "LLM_MODEL=primary-model\n"
        + extra,
        encoding="utf-8",
    )

    with pytest.raises(
        ValueError,
        match=r"^model routing settings are invalid$",
    ):
        load_llm_route_settings(env_file)


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
        ("max_input_tokens", True),
        ("max_output_tokens", False),
        ("max_input_tokens", 0),
        ("max_output_tokens", 0),
        ("max_input_tokens", 2_048),
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
    if field == "max_input_tokens" and value == 2_048:
        values["max_output_tokens"] = 2_048

    with pytest.raises(ValidationError):
        LLMSettings(**values)
