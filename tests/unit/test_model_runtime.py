from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.connectors.errors import ErrorType
from app.generation.models import (
    PROMPT_VERSION,
    GeneratedSQL,
    GenerationResult,
    LLMError,
    LLMProviderError,
)
from app.generation.factory import ModelProviderFactory
from app.local.credential_store import ModelCredentials
from app.local.profile_models import ModelProfile
from app.schema_linking import (
    EmbeddingError,
    EmbeddingIndexRegistry,
    EmbeddingProviderError,
)


class _GenerationProvider:
    def __init__(self, error: LLMProviderError | None = None) -> None:
        self.error = error
        self.calls: list[tuple[object, ...]] = []

    def generate(
        self,
        messages,
        *,
        timeout_seconds=None,
    ):  # type: ignore[no-untyped-def]
        self.calls.append(tuple(messages))
        if self.error is not None:
            raise self.error
        return GenerationResult(
            output=GeneratedSQL(sql="SELECT 1"),
            input_tokens=1,
            output_tokens=1,
            model="local-model",
            prompt_version=PROMPT_VERSION,
        )


@dataclass
class _EmbeddingProvider:
    error: EmbeddingProviderError | None = None
    model_id: str = "embedding-model"
    dimension: int = 3
    provider_config_sha256: str = "a" * 64

    def embed(
        self,
        texts,
        *,
        timeout_seconds=None,
    ):  # type: ignore[no-untyped-def]
        if self.error is not None:
            raise self.error
        return ((1.0, 0.0, 0.0),)


def _profile(*, embedding: bool = False) -> ModelProfile:
    values: dict[str, object] = {
        "id": "local-model",
        "name": "Local Model",
        "provider_type": "openai_compatible",
        "base_url": "http://localhost:11434/v1",
        "model_name": "local-model",
    }
    if embedding:
        values.update(
            embedding_base_url="http://localhost:11434/v1",
            embedding_model="embedding-model",
            embedding_dimension=3,
        )
    return ModelProfile(**values)


def _service(
    generation_provider: _GenerationProvider,
    embedding_provider: _EmbeddingProvider | None = None,
):
    from app.local.model_runtime import ModelRuntimeService

    return ModelRuntimeService(
        model_factory=ModelProviderFactory(
            provider_builder=lambda settings: generation_provider
        ),
        embedding_builder=(
            (lambda settings: embedding_provider)
            if embedding_provider is not None
            else None
        ),
    )


def test_runtime_maps_one_generation_provider_without_embedding() -> None:
    generation_provider = _GenerationProvider()

    runtime = _service(generation_provider).build_runtime(
        _profile(),
        ModelCredentials(),
    )

    routes = runtime.model_routing.route_table.routes
    assert {route.primary.provider_key for route in routes} == {"primary"}
    assert all(route.fallback is None for route in routes)
    assert runtime.embedding_provider is None
    assert isinstance(runtime.embedding_registry, EmbeddingIndexRegistry)


def test_runtime_builds_configured_embedding_provider() -> None:
    embedding_provider = _EmbeddingProvider()

    runtime = _service(
        _GenerationProvider(),
        embedding_provider,
    ).build_runtime(_profile(embedding=True), ModelCredentials())

    assert runtime.embedding_provider is embedding_provider
    assert runtime.profile.embedding_dimension == 3


def test_connection_test_reports_generation_and_optional_embedding() -> None:
    generation_provider = _GenerationProvider()
    service = _service(generation_provider)

    result = service.test_connection(_profile(), ModelCredentials())

    assert result.generation_status == "connected"
    assert result.embedding_status == "not_configured"
    assert result.embedding_error_code is None
    assert len(generation_provider.calls) == 1
    assert tuple(message.role for message in generation_provider.calls[0]) == (
        "system",
        "user",
    )


def test_connection_test_keeps_generation_success_on_embedding_failure() -> None:
    embedding_provider = _EmbeddingProvider(
        error=EmbeddingProviderError(
            EmbeddingError(
                error_type=ErrorType.TIMEOUT,
                code="EMBEDDING_TIMEOUT",
                retryable=False,
                public_message="The embedding request timed out.",
            )
        )
    )

    result = _service(
        _GenerationProvider(),
        embedding_provider,
    ).test_connection(_profile(embedding=True), ModelCredentials())

    assert result.generation_status == "connected"
    assert result.embedding_status == "unavailable"
    assert result.embedding_error_code == "EMBEDDING_TIMEOUT"


@pytest.mark.parametrize(
    ("provider_code", "expected_code", "status_code"),
    [
        ("LLM_TIMEOUT", "MODEL_TEST_TIMEOUT", 504),
        ("LLM_INVALID_OUTPUT", "MODEL_TEST_INVALID_OUTPUT", 422),
        ("LLM_CONNECTION_ERROR", "MODEL_CONNECTION_FAILED", 503),
    ],
)
def test_connection_test_maps_generation_errors(
    provider_code: str,
    expected_code: str,
    status_code: int,
) -> None:
    from app.local.model_runtime import ModelRuntimeError

    error = LLMProviderError(
        LLMError(
            error_type=ErrorType.UNKNOWN,
            code=provider_code,
            retryable=False,
            public_message="provider detail must not escape",
        )
    )

    with pytest.raises(ModelRuntimeError) as exc_info:
        _service(_GenerationProvider(error)).test_connection(
            _profile(),
            ModelCredentials(),
        )

    assert exc_info.value.code == expected_code
    assert exc_info.value.status_code == status_code
    assert "provider detail" not in exc_info.value.public_message
