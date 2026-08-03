"""Build and test dynamic model runtimes from local profiles."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

from app.config import EmbeddingSettings, LLMSettings
from app.generation import (
    LLMMessage,
    LLMProviderError,
    ModelProviderFactory,
    ModelRoutingRuntime,
)
from app.local.credential_store import ModelCredentials
from app.local.profile_models import ModelProfile
from app.schema_linking import (
    EmbeddingIndexRegistry,
    EmbeddingProvider,
    EmbeddingProviderError,
    OpenAICompatibleEmbeddingProvider,
)

EmbeddingBuilder = Callable[[EmbeddingSettings], EmbeddingProvider]


@dataclass(frozen=True, slots=True)
class ModelRuntime:
    profile: ModelProfile
    model_routing: ModelRoutingRuntime
    embedding_provider: EmbeddingProvider | None = field(
        default=None,
        repr=False,
        compare=False,
    )
    embedding_registry: EmbeddingIndexRegistry = field(
        default_factory=EmbeddingIndexRegistry,
        repr=False,
        compare=False,
    )


@dataclass(frozen=True, slots=True)
class ModelConnectionTestResult:
    generation_status: Literal["connected"] = "connected"
    embedding_status: Literal[
        "connected",
        "not_configured",
        "unavailable",
    ] = "not_configured"
    embedding_error_code: str | None = None

    def __post_init__(self) -> None:
        if (
            (self.embedding_status == "unavailable")
            != (self.embedding_error_code is not None)
        ):
            raise ValueError("model connection result is invalid")


class ModelRuntimeError(RuntimeError):
    def __init__(
        self,
        *,
        code: str,
        public_message: str,
        status_code: int,
    ) -> None:
        super().__init__(public_message)
        self.code = code
        self.public_message = public_message
        self.status_code = status_code


class ModelRuntimeService:
    """Create dynamic generation routing and optional Embedding providers."""

    def __init__(
        self,
        *,
        model_factory: ModelProviderFactory | None = None,
        embedding_builder: EmbeddingBuilder | None = None,
    ) -> None:
        self._model_factory = model_factory or ModelProviderFactory()
        self._embedding_builder = (
            embedding_builder or OpenAICompatibleEmbeddingProvider
        )

    def build_runtime(
        self,
        profile: ModelProfile,
        credentials: ModelCredentials,
    ) -> ModelRuntime:
        if (
            not isinstance(profile, ModelProfile)
            or not isinstance(credentials, ModelCredentials)
        ):
            raise ValueError("model runtime input is invalid")
        llm_settings = LLMSettings(
            base_url=profile.base_url,
            api_key=credentials.generation_api_key,
            model=profile.model_name,
            timeout_seconds=30,
            temperature=0,
            max_input_tokens=32_768,
            max_output_tokens=2_048,
        )
        routing = self._model_factory.create_single(
            llm_settings,
            data_boundary_id=f"local-profile:{profile.id}",
        )
        embedding_provider: EmbeddingProvider | None = None
        if profile.embedding_base_url is not None:
            assert profile.embedding_model is not None
            assert profile.embedding_dimension is not None
            embedding_provider = self._embedding_builder(
                EmbeddingSettings(
                    base_url=profile.embedding_base_url,
                    api_key=credentials.embedding_api_key,
                    model=profile.embedding_model,
                    dimension=profile.embedding_dimension,
                    timeout_seconds=10,
                    max_batch_documents=10,
                    max_response_bytes=4_194_304,
                )
            )
        return ModelRuntime(
            profile=profile,
            model_routing=routing,
            embedding_provider=embedding_provider,
        )

    def test_connection(
        self,
        profile: ModelProfile,
        credentials: ModelCredentials,
    ) -> ModelConnectionTestResult:
        runtime = self.build_runtime(profile, credentials)
        provider = runtime.model_routing.provider_registry.resolve(
            "primary"
        ).provider
        try:
            provider.generate(
                (
                    LLMMessage(
                        role="system",
                        content=(
                            "Return one JSON object with sql set to "
                            "SELECT 1 and clarification_reason set to null."
                        ),
                    ),
                    LLMMessage(
                        role="user",
                        content='{"question":"connection test"}',
                    ),
                ),
                timeout_seconds=30,
            )
        except LLMProviderError as error:
            raise _generation_test_error(error) from None

        embedding_provider = runtime.embedding_provider
        if embedding_provider is None:
            return ModelConnectionTestResult()
        try:
            embedding_provider.embed(
                ("connection test",),
                timeout_seconds=10,
            )
        except EmbeddingProviderError as error:
            return ModelConnectionTestResult(
                embedding_status="unavailable",
                embedding_error_code=error.details.code,
            )
        return ModelConnectionTestResult(
            embedding_status="connected",
        )


def _generation_test_error(error: LLMProviderError) -> ModelRuntimeError:
    if error.details.code == "LLM_TIMEOUT":
        return ModelRuntimeError(
            code="MODEL_TEST_TIMEOUT",
            public_message="The model connection test timed out.",
            status_code=504,
        )
    if error.details.code in {"LLM_INVALID_OUTPUT", "LLM_INVALID_RESPONSE"}:
        return ModelRuntimeError(
            code="MODEL_TEST_INVALID_OUTPUT",
            public_message="The model output is incompatible.",
            status_code=422,
        )
    return ModelRuntimeError(
        code="MODEL_CONNECTION_FAILED",
        public_message="The model service is unavailable.",
        status_code=503,
    )
