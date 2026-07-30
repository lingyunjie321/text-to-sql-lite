from dataclasses import dataclass
import asyncio

import pytest

from app.connectors.errors import ErrorType
from app.generation import (
    GenerationResult,
    GeneratedSQL,
    LLMError,
    LLMMessage,
    LLMProviderError,
)


@dataclass
class StubProvider:
    outcome: GenerationResult | LLMProviderError

    def __post_init__(self) -> None:
        self.calls: list[tuple[LLMMessage, ...]] = []
        self.timeouts: list[float | None] = []

    def generate(
        self,
        messages: tuple[LLMMessage, ...],
        *,
        timeout_seconds: float | None = None,
    ) -> GenerationResult:
        self.calls.append(messages)
        self.timeouts.append(timeout_seconds)
        if isinstance(self.outcome, LLMProviderError):
            raise self.outcome
        return self.outcome


def _result(model: str) -> GenerationResult:
    return GenerationResult(
        output=GeneratedSQL(sql="SELECT 1"),
        input_tokens=10,
        output_tokens=2,
        model=model,
        prompt_version="mvp-v1",
    )


def _error(code: str) -> LLMProviderError:
    mapping = {
        "LLM_TIMEOUT": ErrorType.TIMEOUT,
        "LLM_CONNECTION_ERROR": ErrorType.CONNECTION_ERROR,
        "LLM_RATE_LIMITED": ErrorType.RESOURCE_RISK,
        "LLM_CAPACITY_ERROR": ErrorType.RESOURCE_RISK,
        "LLM_INVALID_RESPONSE": ErrorType.UNKNOWN,
        "LLM_INVALID_OUTPUT": ErrorType.UNKNOWN,
        "LLM_HTTP_ERROR": ErrorType.UNKNOWN,
    }
    return LLMProviderError(
        LLMError(
            error_type=mapping[code],
            code=code,
            retryable=code
            in {
                "LLM_TIMEOUT",
                "LLM_CONNECTION_ERROR",
                "LLM_RATE_LIMITED",
                "LLM_CAPACITY_ERROR",
            },
            public_message="Fixed public model failure.",
        )
    )


def _target(
    provider_key: str,
    *,
    boundary: str = "cn-boundary",
    max_input_tokens: int = 32_768,
    max_output_tokens: int = 2_048,
):
    from app.generation.routing import ModelTarget

    return ModelTarget(
        provider_key=provider_key,
        model_config_sha256=(
            "a" * 64
            if provider_key == "primary"
            else "b" * 64
        ),
        max_input_tokens=max_input_tokens,
        max_output_tokens=max_output_tokens,
        timeout_seconds=30,
        data_boundary_id=boundary,
    )


def _runtime(
    *,
    primary: StubProvider,
    fallback: StubProvider | None = None,
):
    from app.generation.routing import (
        ModelRoute,
        ModelRouteTable,
        ModelRoutingRuntime,
        ProviderRegistry,
        RegisteredProvider,
    )

    primary_target = _target("primary")
    fallback_target = (
        _target("fallback")
        if fallback is not None
        else None
    )
    table = ModelRouteTable(
        routes=(
            ModelRoute(
                route_id="simple_route",
                primary=primary_target,
                fallback=fallback_target,
            ),
            ModelRoute(
                route_id="standard_route",
                primary=primary_target,
                fallback=fallback_target,
            ),
            ModelRoute(
                route_id="complex_route",
                primary=primary_target,
                fallback=fallback_target,
            ),
        )
    )
    providers = {
        "primary": RegisteredProvider(
            provider=primary,
            model_config_sha256="a" * 64,
            timeout_seconds=30,
        )
    }
    if fallback is not None:
        providers["fallback"] = RegisteredProvider(
            provider=fallback,
            model_config_sha256="b" * 64,
            timeout_seconds=30,
        )
    return ModelRoutingRuntime(
        provider_registry=ProviderRegistry(providers),
        route_table=table,
    )


@pytest.mark.parametrize(
    ("complexity", "route_id"),
    (
        ("simple", "simple_route"),
        ("medium", "standard_route"),
        ("complex", "complex_route"),
    ),
)
def test_route_table_maps_only_server_complexity(
    complexity: str,
    route_id: str,
) -> None:
    runtime = _runtime(primary=StubProvider(_result("primary")))

    assert (
        runtime.route_table.select(complexity).route_id
        == route_id
    )


@pytest.mark.parametrize(
    "code",
    (
        "LLM_TIMEOUT",
        "LLM_CONNECTION_ERROR",
        "LLM_RATE_LIMITED",
        "LLM_CAPACITY_ERROR",
    ),
)
def test_declared_infrastructure_failure_falls_back_once(
    code: str,
) -> None:
    from app.generation.routing import generate_with_model_route

    primary = StubProvider(_error(code))
    fallback = StubProvider(_result("fallback"))
    runtime = _runtime(primary=primary, fallback=fallback)
    route = runtime.route_table.select("simple")
    messages = (LLMMessage(role="user", content="{}"),)

    routed = generate_with_model_route(
        runtime=runtime,
        route=route,
        messages=messages,
    )

    assert routed.result.model == "fallback"
    assert routed.target.provider_key == "fallback"
    assert routed.fallback_used is True
    assert routed.provider_call_count == 2
    assert routed.primary_error_code == code
    assert len(primary.calls) == len(fallback.calls) == 1
    assert primary.timeouts == [30]
    assert fallback.timeouts == [30]


@pytest.mark.parametrize(
    "error_code",
    (
        "LLM_INVALID_RESPONSE",
        "LLM_INVALID_OUTPUT",
        "LLM_HTTP_ERROR",
    ),
)
def test_non_infrastructure_provider_error_never_uses_fallback(
    error_code: str,
) -> None:
    from app.generation.routing import (
        RoutedGenerationError,
        generate_with_model_route,
    )

    primary = StubProvider(_error(error_code))
    fallback = StubProvider(_result("fallback"))
    runtime = _runtime(primary=primary, fallback=fallback)

    with pytest.raises(RoutedGenerationError) as captured:
        generate_with_model_route(
            runtime=runtime,
            route=runtime.route_table.select("complex"),
            messages=(LLMMessage(role="user", content="{}"),),
        )

    assert captured.value.details.code == error_code
    assert captured.value.fallback_used is False
    assert captured.value.provider_call_count == 1
    assert captured.value.primary_error_code == (
        error_code
    )
    assert len(primary.calls) == 1
    assert fallback.calls == []


def test_fallback_failure_is_bounded_and_sanitized() -> None:
    from app.generation.routing import (
        RoutedGenerationError,
        generate_with_model_route,
    )

    primary = StubProvider(_error("LLM_TIMEOUT"))
    fallback = StubProvider(_error("LLM_CAPACITY_ERROR"))
    runtime = _runtime(primary=primary, fallback=fallback)

    with pytest.raises(RoutedGenerationError) as captured:
        generate_with_model_route(
            runtime=runtime,
            route=runtime.route_table.select("medium"),
            messages=(LLMMessage(role="user", content="private"),),
        )

    assert captured.value.details.code == "LLM_CAPACITY_ERROR"
    assert captured.value.fallback_used is True
    assert captured.value.provider_call_count == 2
    assert captured.value.primary_error_code == "LLM_TIMEOUT"
    assert len(primary.calls) == len(fallback.calls) == 1
    assert "private" not in (
        str(captured.value) + repr(captured.value)
    )


def test_unexpected_provider_exception_is_sanitized_without_fallback() -> None:
    from app.generation.routing import (
        RoutedGenerationError,
        generate_with_model_route,
    )

    class BrokenProvider(StubProvider):
        def generate(
            self,
            messages,
            *,
            timeout_seconds=None,
        ):
            self.calls.append(tuple(messages))
            raise RuntimeError("private programming failure")

    primary = BrokenProvider(_result("unused"))
    fallback = StubProvider(_result("fallback"))
    runtime = _runtime(primary=primary, fallback=fallback)

    with pytest.raises(RoutedGenerationError) as captured:
        generate_with_model_route(
            runtime=runtime,
            route=runtime.route_table.select("simple"),
            messages=(LLMMessage(role="user", content="{}"),),
        )

    assert captured.value.details.code == "LLM_INTERNAL_ERROR"
    assert captured.value.primary_error_code == "LLM_INTERNAL_ERROR"
    assert "private programming failure" not in (
        str(captured.value) + repr(captured.value)
    )
    assert len(primary.calls) == 1
    assert fallback.calls == []


def test_unknown_provider_error_is_normalized_without_fallback() -> None:
    from app.generation.routing import (
        RoutedGenerationError,
        generate_with_model_route,
    )

    primary = StubProvider(
        LLMProviderError(
            LLMError(
                error_type=ErrorType.UNKNOWN,
                code="PRIVATE_VENDOR_FAILURE",
                retryable=True,
                public_message="private vendor detail",
            )
        )
    )
    fallback = StubProvider(_result("fallback"))
    runtime = _runtime(primary=primary, fallback=fallback)

    with pytest.raises(RoutedGenerationError) as captured:
        generate_with_model_route(
            runtime=runtime,
            route=runtime.route_table.select("simple"),
            messages=(LLMMessage(role="user", content="{}"),),
        )

    assert captured.value.details.code == "LLM_INTERNAL_ERROR"
    assert captured.value.primary_error_code == "LLM_INTERNAL_ERROR"
    assert "PRIVATE_VENDOR_FAILURE" not in (
        str(captured.value) + repr(captured.value)
    )
    assert fallback.calls == []


def test_route_caps_primary_and_fallback_to_remaining_deadline() -> None:
    from app.generation.routing import generate_with_model_route

    primary = StubProvider(_error("LLM_TIMEOUT"))
    fallback = StubProvider(_result("fallback"))
    runtime = _runtime(primary=primary, fallback=fallback)
    times = iter((90.0, 96.5))

    routed = generate_with_model_route(
        runtime=runtime,
        route=runtime.route_table.select("simple"),
        messages=(LLMMessage(role="user", content="{}"),),
        deadline_at=100.0,
        clock=lambda: next(times),
    )

    assert routed.fallback_used is True
    assert primary.timeouts == [10.0]
    assert fallback.timeouts == [3.5]


def test_expired_deadline_calls_no_provider_or_fallback() -> None:
    from app.generation.routing import (
        RoutedGenerationError,
        generate_with_model_route,
    )

    primary = StubProvider(_result("primary"))
    fallback = StubProvider(_result("fallback"))
    runtime = _runtime(primary=primary, fallback=fallback)

    with pytest.raises(RoutedGenerationError) as captured:
        generate_with_model_route(
            runtime=runtime,
            route=runtime.route_table.select("simple"),
            messages=(LLMMessage(role="user", content="{}"),),
            deadline_at=10.0,
            clock=lambda: 10.0,
        )

    assert captured.value.details.code == "LLM_TIMEOUT"
    assert captured.value.provider_call_count == 0
    assert captured.value.fallback_used is False
    assert primary.calls == []
    assert fallback.calls == []


def test_cancellation_is_never_normalized_or_fallback_routed() -> None:
    from app.generation.routing import generate_with_model_route

    class CancelledProvider(StubProvider):
        def generate(
            self,
            messages,
            *,
            timeout_seconds=None,
        ):
            self.calls.append(tuple(messages))
            raise asyncio.CancelledError

    primary = CancelledProvider(_result("unused"))
    fallback = StubProvider(_result("fallback"))
    runtime = _runtime(primary=primary, fallback=fallback)

    with pytest.raises(asyncio.CancelledError):
        generate_with_model_route(
            runtime=runtime,
            route=runtime.route_table.select("simple"),
            messages=(LLMMessage(role="user", content="{}"),),
        )

    assert len(primary.calls) == 1
    assert fallback.calls == []


@pytest.mark.parametrize(
    "fallback",
    (
        lambda: _target("fallback", boundary="other-boundary"),
        lambda: _target(
            "fallback",
            max_input_tokens=16_384,
        ),
        lambda: _target(
            "fallback",
            max_output_tokens=1_024,
        ),
        lambda: _target(
            "fallback",
            max_input_tokens=65_536,
        ),
    ),
)
def test_route_rejects_incompatible_fallback(fallback) -> None:
    from app.generation.routing import ModelRoute

    with pytest.raises(
        ValueError,
        match=r"^model route is invalid$",
    ):
        ModelRoute(
            route_id="simple_route",
            primary=_target("primary"),
            fallback=fallback(),
        )


def test_runtime_rejects_unknown_provider_key() -> None:
    from app.generation.routing import (
        ModelRoute,
        ModelRouteTable,
        ModelRoutingRuntime,
        ProviderRegistry,
        RegisteredProvider,
    )

    primary = _target("primary")
    table = ModelRouteTable(
        routes=(
            ModelRoute(route_id="simple_route", primary=primary),
            ModelRoute(route_id="standard_route", primary=primary),
            ModelRoute(route_id="complex_route", primary=primary),
        )
    )

    with pytest.raises(
        ValueError,
        match=r"^model routing runtime is invalid$",
    ):
        ModelRoutingRuntime(
            provider_registry=ProviderRegistry(
                {
                    "different": RegisteredProvider(
                        provider=StubProvider(_result("other")),
                        model_config_sha256="c" * 64,
                        timeout_seconds=30,
                    )
                }
            ),
            route_table=table,
        )


def test_generation_rejects_route_not_declared_by_runtime() -> None:
    from dataclasses import replace

    from app.generation.routing import (
        generate_with_model_route,
    )

    primary = StubProvider(_result("primary"))
    runtime = _runtime(primary=primary)
    approved = runtime.route_table.select("simple")
    forged = replace(
        approved,
        primary=replace(
            approved.primary,
            data_boundary_id="forged-boundary",
        ),
    )

    with pytest.raises(
        ValueError,
        match=r"^model route is invalid$",
    ):
        generate_with_model_route(
            runtime=runtime,
            route=forged,
            messages=(LLMMessage(role="user", content="{}"),),
        )

    assert primary.calls == []


@pytest.mark.parametrize(
    "changes",
    (
        {"model_config_sha256": "A" * 64},
        {"model_config_sha256": "a" * 63},
        {"max_input_tokens": True},
        {"max_output_tokens": False},
        {"timeout_seconds": True},
        {"data_boundary_id": "  "},
        {"output_contract_version": "forged"},
    ),
)
def test_target_rejects_open_or_coerced_values(
    changes: dict[str, object],
) -> None:
    from dataclasses import replace

    with pytest.raises(
        ValueError,
        match=r"^model target is invalid$",
    ):
        replace(_target("primary"), **changes)


def test_provider_registry_copies_input_and_hides_keys() -> None:
    from app.generation.routing import (
        ProviderRegistry,
        RegisteredProvider,
    )

    primary = StubProvider(_result("primary"))
    providers = {
        "private-provider-key": RegisteredProvider(
            provider=primary,
            model_config_sha256="a" * 64,
            timeout_seconds=30,
        )
    }
    registry = ProviderRegistry(providers)
    providers.clear()

    assert (
        registry.resolve("private-provider-key").provider
        is primary
    )
    assert "private-provider-key" not in repr(registry)


def test_model_config_hash_excludes_secret_and_includes_limits() -> None:
    from app.config import LLMSettings
    from app.generation.routing import model_config_sha256

    first = LLMSettings(
        base_url="https://models.example.test/v1",
        api_key="first-secret",
        model="model-a",
    )
    secret_only_change = LLMSettings(
        base_url="https://models.example.test/v1",
        api_key="second-secret",
        model="model-a",
    )
    limit_change = LLMSettings(
        base_url="https://models.example.test/v1",
        api_key="first-secret",
        model="model-a",
        max_input_tokens=65_536,
    )

    assert model_config_sha256(first) == model_config_sha256(
        secret_only_change
    )
    assert model_config_sha256(first) != model_config_sha256(
        limit_change
    )
    assert "first-secret" not in model_config_sha256(first)


def test_configured_runtime_registers_each_declared_server_route() -> None:
    from app.config import LLMRouteSettings, LLMSettings
    from app.generation.routing import (
        build_configured_model_routing_runtime,
        model_config_sha256,
    )

    route_settings = {
        name: LLMSettings(
            base_url="https://models.example.test/v1",
            api_key="shared-test-secret",
            model=f"{name}-model",
        )
        for name in ("simple", "standard", "complex", "fallback")
    }
    settings = LLMRouteSettings(
        simple=route_settings["simple"],
        standard=route_settings["standard"],
        complex=route_settings["complex"],
        fallback=route_settings["fallback"],
        fallback_route_ids=("complex_route",),
        data_boundary_id="cn-approved-v1",
    )
    providers = {
        name: StubProvider(_result(name))
        for name in route_settings
    }

    runtime = build_configured_model_routing_runtime(
        settings=settings,
        providers=providers,
    )

    assert runtime.provider_registry.provider_keys == frozenset(
        providers
    )
    assert (
        runtime.route_table.select(
            "simple"
        ).primary.model_config_sha256
        == model_config_sha256(route_settings["simple"])
    )
    assert (
        runtime.route_table.select("medium").primary.provider_key
        == "standard"
    )
    complex_route = runtime.route_table.select("complex")
    assert complex_route.primary.provider_key == "complex"
    assert complex_route.fallback is not None
    assert complex_route.fallback.provider_key == "fallback"


def test_configured_runtime_rejects_missing_declared_provider() -> None:
    from app.config import LLMRouteSettings, LLMSettings
    from app.generation.routing import (
        build_configured_model_routing_runtime,
    )

    primary = LLMSettings(
        base_url="https://models.example.test/v1",
        api_key="shared-test-secret",
        model="primary-model",
    )
    settings = LLMRouteSettings(
        simple=primary,
        standard=primary,
        complex=primary,
        fallback=None,
        fallback_route_ids=(),
        data_boundary_id="cn-approved-v1",
    )

    with pytest.raises(
        ValueError,
        match=r"^model routing runtime is invalid$",
    ):
        build_configured_model_routing_runtime(
            settings=settings,
            providers={
                "simple": StubProvider(_result("simple")),
                "standard": StubProvider(_result("standard")),
            },
        )
