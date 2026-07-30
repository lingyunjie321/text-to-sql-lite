from __future__ import annotations

import hashlib
import json
import math
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Callable, Literal, TypeAlias

from app.config import LLMRouteSettings, LLMSettings
from app.connectors.errors import ErrorType
from app.generation.models import (
    PROMPT_VERSION,
    GenerationResult,
    LLMError,
    LLMMessage,
    LLMProviderError,
)
from app.generation.provider import (
    LLMProvider,
    PROVIDER_CONTRACT_VERSION,
    normalize_llm_provider_error,
)

MODEL_ROUTE_TABLE_VERSION = "model-routes-v1"
FALLBACK_ERROR_CODES = frozenset(
    {
        "LLM_TIMEOUT",
        "LLM_CONNECTION_ERROR",
        "LLM_RATE_LIMITED",
        "LLM_CAPACITY_ERROR",
    }
)
_INTERNAL_PROVIDER_ERROR = LLMError(
    error_type=ErrorType.UNKNOWN,
    code="LLM_INTERNAL_ERROR",
    retryable=False,
    public_message="The model request failed.",
)
_DEADLINE_ERROR = LLMError(
    error_type=ErrorType.TIMEOUT,
    code="LLM_TIMEOUT",
    retryable=True,
    public_message="The model request timed out.",
)

ModelRouteId: TypeAlias = Literal[
    "simple_route",
    "standard_route",
    "complex_route",
]
ComplexityLevel: TypeAlias = Literal[
    "simple",
    "medium",
    "complex",
]

_ROUTE_BY_COMPLEXITY: dict[ComplexityLevel, ModelRouteId] = {
    "simple": "simple_route",
    "medium": "standard_route",
    "complex": "complex_route",
}
_ROUTE_ORDER: tuple[ModelRouteId, ...] = (
    "simple_route",
    "standard_route",
    "complex_route",
)


def _valid_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(
            character in "0123456789abcdef"
            for character in value
        )
    )


@dataclass(frozen=True, slots=True)
class ModelTarget:
    provider_key: str = field(repr=False)
    model_config_sha256: str
    max_input_tokens: int
    max_output_tokens: int
    timeout_seconds: float
    data_boundary_id: str = field(repr=False)
    output_contract_version: Literal[
        "openai-compatible-json-v1"
    ] = PROVIDER_CONTRACT_VERSION

    def __post_init__(self) -> None:
        if (
            not self.provider_key
            or self.provider_key != self.provider_key.strip()
            or not _valid_sha256(self.model_config_sha256)
            or type(self.max_input_tokens) is not int
            or self.max_input_tokens <= 0
            or type(self.max_output_tokens) is not int
            or self.max_output_tokens <= 0
            or self.max_output_tokens >= self.max_input_tokens
            or type(self.timeout_seconds) not in (int, float)
            or self.timeout_seconds <= 0
            or self.timeout_seconds > 120
            or not self.data_boundary_id
            or self.data_boundary_id
            != self.data_boundary_id.strip()
            or self.output_contract_version
            != PROVIDER_CONTRACT_VERSION
        ):
            raise ValueError("model target is invalid")

    @property
    def data_boundary_sha256(self) -> str:
        return hashlib.sha256(
            self.data_boundary_id.encode("utf-8")
        ).hexdigest()


@dataclass(frozen=True, slots=True)
class ModelRoute:
    route_id: ModelRouteId
    primary: ModelTarget
    fallback: ModelTarget | None = None

    def __post_init__(self) -> None:
        if (
            self.route_id not in _ROUTE_ORDER
            or not isinstance(self.primary, ModelTarget)
            or (
                self.fallback is not None
                and (
                    not isinstance(
                        self.fallback,
                        ModelTarget,
                    )
                    or (
                        self.fallback.provider_key,
                        self.fallback.model_config_sha256,
                    )
                    == (
                        self.primary.provider_key,
                        self.primary.model_config_sha256,
                    )
                    or self.fallback.data_boundary_id
                    != self.primary.data_boundary_id
                    or self.fallback.max_input_tokens
                    != self.primary.max_input_tokens
                    or self.fallback.max_output_tokens
                    != self.primary.max_output_tokens
                    or self.fallback.output_contract_version
                    != self.primary.output_contract_version
                )
            )
        ):
            raise ValueError("model route is invalid")


@dataclass(frozen=True, slots=True)
class ModelRouteTable:
    routes: tuple[ModelRoute, ...]
    version: Literal[
        "model-routes-v1"
    ] = MODEL_ROUTE_TABLE_VERSION

    def __post_init__(self) -> None:
        if (
            type(self.routes) is not tuple
            or tuple(route.route_id for route in self.routes)
            != _ROUTE_ORDER
            or self.version != MODEL_ROUTE_TABLE_VERSION
        ):
            raise ValueError("model route table is invalid")

    def select(self, complexity: str) -> ModelRoute:
        if type(complexity) is not str:
            raise ValueError("model complexity is invalid")
        try:
            route_id = _ROUTE_BY_COMPLEXITY[complexity]  # type: ignore[index]
        except KeyError:
            raise ValueError("model complexity is invalid") from None
        return next(
            route
            for route in self.routes
            if route.route_id == route_id
        )


@dataclass(frozen=True, slots=True)
class RegisteredProvider:
    provider: LLMProvider = field(repr=False, compare=False)
    model_config_sha256: str
    timeout_seconds: float
    output_contract_version: Literal[
        "openai-compatible-json-v1"
    ] = PROVIDER_CONTRACT_VERSION

    def __post_init__(self) -> None:
        if (
            not callable(getattr(self.provider, "generate", None))
            or not _valid_sha256(self.model_config_sha256)
            or type(self.timeout_seconds) not in (int, float)
            or self.timeout_seconds <= 0
            or self.timeout_seconds > 120
            or self.output_contract_version
            != PROVIDER_CONTRACT_VERSION
        ):
            raise ValueError("registered provider is invalid")


class ProviderRegistry:
    def __init__(
        self,
        providers: Mapping[str, RegisteredProvider],
    ) -> None:
        if (
            not isinstance(providers, Mapping)
            or not providers
            or any(
                not isinstance(key, str)
                or not key
                or key != key.strip()
                or not isinstance(
                    registration,
                    RegisteredProvider,
                )
                for key, registration in providers.items()
            )
        ):
            raise ValueError("provider registry is invalid")
        self._providers = MappingProxyType(dict(providers))

    @property
    def provider_keys(self) -> frozenset[str]:
        return frozenset(self._providers)

    def resolve(self, provider_key: str) -> RegisteredProvider:
        try:
            return self._providers[provider_key]
        except KeyError:
            raise ValueError(
                "provider registry is invalid"
            ) from None

    def __repr__(self) -> str:
        return (
            "ProviderRegistry("
            f"provider_count={len(self._providers)})"
        )


@dataclass(frozen=True, slots=True)
class ModelRoutingRuntime:
    provider_registry: ProviderRegistry = field(repr=False)
    route_table: ModelRouteTable

    def __post_init__(self) -> None:
        try:
            targets = tuple(
                target
                for route in self.route_table.routes
                for target in (
                    route.primary,
                    route.fallback,
                )
                if target is not None
            )
            for target in targets:
                registration = self.provider_registry.resolve(
                    target.provider_key
                )
                if (
                    registration.model_config_sha256
                    != target.model_config_sha256
                    or registration.timeout_seconds
                    != target.timeout_seconds
                    or registration.output_contract_version
                    != target.output_contract_version
                ):
                    raise ValueError
        except Exception:
            raise ValueError(
                "model routing runtime is invalid"
            ) from None


@dataclass(frozen=True, slots=True)
class RoutedGeneration:
    result: GenerationResult
    target: ModelTarget
    fallback_used: bool
    provider_call_count: Literal[1, 2]
    primary_error_code: str | None


class RoutedGenerationError(RuntimeError):
    def __init__(
        self,
        *,
        details: LLMError,
        target: ModelTarget,
        fallback_used: bool,
        provider_call_count: Literal[0, 1, 2],
        primary_error_code: str,
    ) -> None:
        super().__init__(details.public_message)
        self.details = details
        self.target = target
        self.fallback_used = fallback_used
        self.provider_call_count = provider_call_count
        self.primary_error_code = primary_error_code


@dataclass(frozen=True, slots=True)
class _ProviderCallFailure(Exception):
    details: LLMError
    provider_called: bool


def model_config_sha256(settings: LLMSettings) -> str:
    payload = json.dumps(
        {
            "base_url": str(settings.base_url),
            "max_input_tokens": settings.max_input_tokens,
            "max_output_tokens": settings.max_output_tokens,
            "model": settings.model,
            "output_contract_version": (
                PROVIDER_CONTRACT_VERSION
            ),
            "prompt_version": PROMPT_VERSION,
            "temperature": settings.temperature,
            "timeout_seconds": settings.timeout_seconds,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def build_single_provider_routing_runtime(
    *,
    provider: LLMProvider,
    model_config_sha256_value: str,
    max_input_tokens: int,
    max_output_tokens: int,
    timeout_seconds: float,
    data_boundary_id: str,
    provider_key: str = "primary",
) -> ModelRoutingRuntime:
    target = ModelTarget(
        provider_key=provider_key,
        model_config_sha256=model_config_sha256_value,
        max_input_tokens=max_input_tokens,
        max_output_tokens=max_output_tokens,
        timeout_seconds=timeout_seconds,
        data_boundary_id=data_boundary_id,
    )
    return ModelRoutingRuntime(
        provider_registry=ProviderRegistry(
            {
                provider_key: RegisteredProvider(
                    provider=provider,
                    model_config_sha256=(
                        model_config_sha256_value
                    ),
                    timeout_seconds=timeout_seconds,
                )
            }
        ),
        route_table=ModelRouteTable(
            routes=tuple(
                ModelRoute(
                    route_id=route_id,
                    primary=target,
                )
                for route_id in _ROUTE_ORDER
            )
        ),
    )


def build_configured_model_routing_runtime(
    *,
    settings: LLMRouteSettings,
    providers: Mapping[str, LLMProvider],
) -> ModelRoutingRuntime:
    if (
        not isinstance(settings, LLMRouteSettings)
        or not isinstance(providers, Mapping)
    ):
        raise ValueError(
            "model routing runtime is invalid"
        )
    route_settings = {
        "simple": settings.simple,
        "standard": settings.standard,
        "complex": settings.complex,
    }
    expected_provider_keys = {
        *route_settings,
        *(
            ("fallback",)
            if settings.fallback is not None
            else ()
        ),
    }
    if (
        set(providers) != expected_provider_keys
        or any(
            not callable(getattr(provider, "generate", None))
            for provider in providers.values()
        )
    ):
        raise ValueError(
            "model routing runtime is invalid"
        )
    target_settings = dict(route_settings)
    if settings.fallback is not None:
        target_settings["fallback"] = settings.fallback
    targets = {
        key: ModelTarget(
            provider_key=key,
            model_config_sha256=model_config_sha256(
                provider_settings
            ),
            max_input_tokens=(
                provider_settings.max_input_tokens
            ),
            max_output_tokens=(
                provider_settings.max_output_tokens
            ),
            timeout_seconds=(
                provider_settings.timeout_seconds
            ),
            data_boundary_id=settings.data_boundary_id,
        )
        for key, provider_settings in target_settings.items()
    }
    fallback_routes = frozenset(
        settings.fallback_route_ids
    )
    route_keys = (
        ("simple_route", "simple"),
        ("standard_route", "standard"),
        ("complex_route", "complex"),
    )
    return ModelRoutingRuntime(
        provider_registry=ProviderRegistry(
            {
                key: RegisteredProvider(
                    provider=providers[key],
                    model_config_sha256=(
                        target.model_config_sha256
                    ),
                    timeout_seconds=target.timeout_seconds,
                )
                for key, target in targets.items()
            }
        ),
        route_table=ModelRouteTable(
            routes=tuple(
                ModelRoute(
                    route_id=route_id,  # type: ignore[arg-type]
                    primary=targets[key],
                    fallback=(
                        targets["fallback"]
                        if route_id in fallback_routes
                        else None
                    ),
                )
                for route_id, key in route_keys
            )
        ),
    )


def _call_provider(
    *,
    runtime: ModelRoutingRuntime,
    target: ModelTarget,
    messages: Sequence[LLMMessage],
    deadline_at: float | None,
    clock: Callable[[], float],
) -> GenerationResult:
    timeout_seconds = target.timeout_seconds
    if deadline_at is not None:
        remaining_seconds = deadline_at - clock()
        if remaining_seconds <= 0:
            raise _ProviderCallFailure(
                details=_DEADLINE_ERROR,
                provider_called=False,
            )
        timeout_seconds = min(
            timeout_seconds,
            remaining_seconds,
        )
    registration = runtime.provider_registry.resolve(
        target.provider_key
    )
    try:
        return registration.provider.generate(
            messages,
            timeout_seconds=timeout_seconds,
        )
    except LLMProviderError as error:
        raise _ProviderCallFailure(
            details=normalize_llm_provider_error(
                error.details
            ),
            provider_called=True,
        ) from None
    except Exception:
        raise _ProviderCallFailure(
            details=_INTERNAL_PROVIDER_ERROR,
            provider_called=True,
        ) from None


def generate_with_model_route(
    *,
    runtime: ModelRoutingRuntime,
    route: ModelRoute,
    messages: Sequence[LLMMessage],
    deadline_at: float | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> RoutedGeneration:
    if (
        not isinstance(runtime, ModelRoutingRuntime)
        or not isinstance(route, ModelRoute)
        or route not in runtime.route_table.routes
    ):
        raise ValueError("model route is invalid")
    if (
        (
            deadline_at is not None
            and (
                type(deadline_at) not in (int, float)
                or not math.isfinite(deadline_at)
            )
        )
        or not callable(clock)
    ):
        raise ValueError("model route deadline is invalid")
    try:
        result = _call_provider(
            runtime=runtime,
            target=route.primary,
            messages=messages,
            deadline_at=deadline_at,
            clock=clock,
        )
    except _ProviderCallFailure as error:
        primary_call_count = int(error.provider_called)
        primary_error_code = error.details.code
        if (
            error.details.code not in FALLBACK_ERROR_CODES
            or route.fallback is None
        ):
            raise RoutedGenerationError(
                details=error.details,
                target=route.primary,
                fallback_used=False,
                provider_call_count=primary_call_count,  # type: ignore[arg-type]
                primary_error_code=primary_error_code,
            ) from None
        try:
            result = _call_provider(
                runtime=runtime,
                target=route.fallback,
                messages=messages,
                deadline_at=deadline_at,
                clock=clock,
            )
        except _ProviderCallFailure as fallback_error:
            if not fallback_error.provider_called:
                raise RoutedGenerationError(
                    details=fallback_error.details,
                    target=route.primary,
                    fallback_used=False,
                    provider_call_count=primary_call_count,  # type: ignore[arg-type]
                    primary_error_code=primary_error_code,
                ) from None
            raise RoutedGenerationError(
                details=fallback_error.details,
                target=route.fallback,
                fallback_used=True,
                provider_call_count=2,
                primary_error_code=primary_error_code,
            ) from None
        return RoutedGeneration(
            result=result,
            target=route.fallback,
            fallback_used=True,
            provider_call_count=2,
            primary_error_code=primary_error_code,
        )
    return RoutedGeneration(
        result=result,
        target=route.primary,
        fallback_used=False,
        provider_call_count=1,
        primary_error_code=None,
    )
