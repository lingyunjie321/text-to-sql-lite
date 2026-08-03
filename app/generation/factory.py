"""Construction of configured model providers and routing runtime."""

from __future__ import annotations

from collections.abc import Callable

from app.config import LLMRouteSettings, LLMSettings
from app.generation.provider import LLMProvider, OpenAICompatibleLLMProvider
from app.generation.routing import (
    ModelRoutingRuntime,
    build_configured_model_routing_runtime,
    build_single_provider_routing_runtime,
    model_config_sha256,
)


class ModelProviderFactory:
    """Create configured model providers and a routing runtime."""

    def __init__(
        self,
        *,
        provider_builder: Callable[[LLMSettings], LLMProvider] | None = None,
    ) -> None:
        self._provider_builder = (
            OpenAICompatibleLLMProvider
            if provider_builder is None
            else provider_builder
        )

    def create(self, settings: LLMRouteSettings) -> ModelRoutingRuntime:
        if not isinstance(settings, LLMRouteSettings):
            raise ValueError("model routing settings are invalid")
        configured: dict[str, LLMSettings] = {
            "simple": settings.simple,
            "standard": settings.standard,
            "complex": settings.complex,
        }
        if settings.fallback is not None:
            configured["fallback"] = settings.fallback
        providers = {
            key: self._provider_builder(provider_settings)
            for key, provider_settings in configured.items()
        }
        return build_configured_model_routing_runtime(
            settings=settings,
            providers=providers,
        )

    def create_single(
        self,
        settings: LLMSettings,
        *,
        data_boundary_id: str,
    ) -> ModelRoutingRuntime:
        if (
            not isinstance(settings, LLMSettings)
            or not isinstance(data_boundary_id, str)
            or not data_boundary_id
            or data_boundary_id != data_boundary_id.strip()
        ):
            raise ValueError("model routing settings are invalid")
        provider = self._provider_builder(settings)
        return build_single_provider_routing_runtime(
            provider=provider,
            model_config_sha256_value=model_config_sha256(settings),
            max_input_tokens=settings.max_input_tokens,
            max_output_tokens=settings.max_output_tokens,
            timeout_seconds=settings.timeout_seconds,
            data_boundary_id=data_boundary_id,
        )
