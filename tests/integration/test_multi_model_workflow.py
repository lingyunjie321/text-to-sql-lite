from dataclasses import dataclass

import pytest

import app.workflow.nodes as workflow_nodes
import app.workflow.nodes.generate_sql as gen_sql_module
from app.connectors.errors import ErrorType
from app.generation import (
    GenerationResult,
    LLMError,
    LLMMessage,
    LLMProviderError,
    ModelRoute,
    ModelRouteTable,
    ModelRoutingRuntime,
    ModelTarget,
    ProviderRegistry,
    RegisteredProvider,
)
from app.observability import build_trace_record
from app.workflow import (
    FinalStatus,
    WorkflowContext,
    new_task_state,
    run_workflow,
)
from tests.unit.test_workflow_graph import (
    StubConnector,
    _generation,
)


@dataclass
class RoutingProvider:
    outcome: GenerationResult | LLMProviderError

    def __post_init__(self) -> None:
        self.calls: list[tuple[LLMMessage, ...]] = []
        self.timeouts: list[float | None] = []

    def generate(
        self,
        messages,
        *,
        timeout_seconds: float | None = None,
    ) -> GenerationResult:
        self.calls.append(tuple(messages))
        self.timeouts.append(timeout_seconds)
        if isinstance(self.outcome, LLMProviderError):
            raise self.outcome
        return self.outcome


def _provider_error(code: str) -> LLMProviderError:
    error_type = {
        "LLM_TIMEOUT": ErrorType.TIMEOUT,
        "LLM_INVALID_RESPONSE": ErrorType.UNKNOWN,
        "LLM_CAPACITY_ERROR": ErrorType.RESOURCE_RISK,
    }[code]
    return LLMProviderError(
        LLMError(
            error_type=error_type,
            code=code,
            retryable=code
            in {"LLM_TIMEOUT", "LLM_CAPACITY_ERROR"},
            public_message="The model request failed.",
        )
    )


def _target(
    provider_key: str,
    *,
    max_input_tokens: int = 32_768,
    max_output_tokens: int = 2_048,
) -> ModelTarget:
    return ModelTarget(
        provider_key=provider_key,
        model_config_sha256={
            "simple": "a" * 64,
            "standard": "b" * 64,
            "complex": "c" * 64,
            "fallback": "d" * 64,
        }[provider_key],
        max_input_tokens=max_input_tokens,
        max_output_tokens=max_output_tokens,
        timeout_seconds=30,
        data_boundary_id="cn-boundary",
    )


def _routing_runtime(
    providers: dict[str, RoutingProvider],
    *,
    max_input_tokens: int = 32_768,
    max_output_tokens: int = 2_048,
    simple_fallback: str | None = None,
) -> ModelRoutingRuntime:
    targets = {
        key: _target(
            key,
            max_input_tokens=max_input_tokens,
            max_output_tokens=max_output_tokens,
        )
        for key in providers
    }
    routes = (
        ModelRoute(
            route_id="simple_route",
            primary=targets["simple"],
            fallback=(
                targets[simple_fallback]
                if simple_fallback is not None
                else None
            ),
        ),
        ModelRoute(
            route_id="standard_route",
            primary=targets.get("standard", targets["simple"]),
        ),
        ModelRoute(
            route_id="complex_route",
            primary=targets.get("complex", targets["simple"]),
        ),
    )
    return ModelRoutingRuntime(
        provider_registry=ProviderRegistry(
            {
                key: RegisteredProvider(
                    provider=provider,
                    model_config_sha256=targets[
                        key
                    ].model_config_sha256,
                    timeout_seconds=30,
                )
                for key, provider in providers.items()
            }
        ),
        route_table=ModelRouteTable(routes=routes),
    )


def _run(
    question: str,
    runtime: ModelRoutingRuntime,
    *,
    clock=lambda: 0.0,
    workflow_started_at: float | None = None,
):
    connector = StubConnector()
    state = new_task_state(
        request_id="req-routing",
        trace_id="trace-routing",
        question=question,
        datasource_id="pagila",
    )
    if workflow_started_at is not None:
        state = state.model_copy(
            update={
                "workflow_started_at": workflow_started_at,
            }
        )
    return run_workflow(
        state,
        context=WorkflowContext(
            connector=connector,
            model_routing=runtime,
            datasource_id="pagila",
            allowed_schemas=("public",),
            allowed_tables=("public.film",),
            clock=clock,
        ),
    )


@pytest.mark.parametrize(
    ("question", "selected_key"),
    (
        ("List film titles", "simple"),
        ("Count film titles", "standard"),
        ("Rank films by title", "complex"),
    ),
)
def test_workflow_selects_provider_from_server_complexity(
    question: str,
    selected_key: str,
) -> None:
    providers = {
        key: RoutingProvider(
            _generation(sql="SELECT title FROM film")
        )
        for key in ("simple", "standard", "complex")
    }
    terminal = _run(question, _routing_runtime(providers))

    assert terminal.final_status is FinalStatus.SUCCEEDED_FIRST_PASS
    assert len(providers[selected_key].calls) == 1
    assert sum(len(provider.calls) for provider in providers.values()) == 1
    assert terminal.model_routing_observations[0].route_id == {
        "simple": "simple_route",
        "standard": "standard_route",
        "complex": "complex_route",
    }[selected_key]
    assert (
        terminal.context_selection_observations[0].outcome
        == "selected"
    )


def test_workflow_uses_declared_fallback_without_repair() -> None:
    providers = {
        "simple": RoutingProvider(
            _provider_error("LLM_TIMEOUT")
        ),
        "fallback": RoutingProvider(
            _generation(sql="SELECT title FROM film")
        ),
    }
    terminal = _run(
        "List film titles",
        _routing_runtime(
            providers,
            simple_fallback="fallback",
        ),
    )

    assert terminal.final_status is FinalStatus.SUCCEEDED_FIRST_PASS
    assert terminal.repair_count == 0
    assert len(providers["simple"].calls) == 1
    assert len(providers["fallback"].calls) == 1
    observation = terminal.model_routing_observations[0]
    assert observation.fallback_used is True
    assert observation.provider_call_count == 2
    assert observation.primary_model_config_sha256 == "a" * 64
    assert observation.model_config_sha256 == "d" * 64
    assert observation.primary_error_code == "LLM_TIMEOUT"
    trace = build_trace_record(terminal)
    assert trace.model_routes[0].primary_model_config_hash == (
        "a" * 64
    )
    assert trace.model_routes[0].model_config_hash == "d" * 64
    assert trace.model_routes[0].primary_error_code == "LLM_TIMEOUT"
    assert trace.model_routes[0].fallback_used is True
    serialized = trace.model_dump_json()
    for private_value in (
        '"fallback"',
        "cn-boundary",
        "List film titles",
        "public.film",
    ):
        assert private_value not in serialized


def test_workflow_does_not_fallback_on_invalid_response() -> None:
    providers = {
        "simple": RoutingProvider(
            _provider_error("LLM_INVALID_RESPONSE")
        ),
        "fallback": RoutingProvider(
            _generation(sql="SELECT title FROM film")
        ),
    }
    terminal = _run(
        "List film titles",
        _routing_runtime(
            providers,
            simple_fallback="fallback",
        ),
    )

    assert terminal.final_status is FinalStatus.FAILED_INTERNAL
    assert terminal.public_error is not None
    assert terminal.public_error.code == "LLM_INVALID_RESPONSE"
    assert len(providers["simple"].calls) == 1
    assert providers["fallback"].calls == []
    observation = terminal.model_routing_observations[0]
    assert observation.outcome == "failed"
    assert observation.error_code == "LLM_INVALID_RESPONSE"
    assert observation.provider_call_count == 1


def test_workflow_records_bounded_fallback_failure() -> None:
    providers = {
        "simple": RoutingProvider(
            _provider_error("LLM_TIMEOUT")
        ),
        "fallback": RoutingProvider(
            _provider_error("LLM_CAPACITY_ERROR")
        ),
    }
    terminal = _run(
        "List film titles",
        _routing_runtime(
            providers,
            simple_fallback="fallback",
        ),
    )

    assert terminal.final_status is FinalStatus.FAILED_RESOURCE_RISK
    assert len(providers["simple"].calls) == 1
    assert len(providers["fallback"].calls) == 1
    observation = terminal.model_routing_observations[0]
    assert observation.outcome == "failed"
    assert observation.fallback_used is True
    assert observation.provider_call_count == 2
    assert observation.error_code == "LLM_CAPACITY_ERROR"
    assert observation.primary_error_code == "LLM_TIMEOUT"
    assert observation.failure_stage == "provider"
    trace = build_trace_record(terminal)
    assert trace.model_routes[0].outcome == "failed"
    assert trace.model_routes[0].error_code == (
        "LLM_CAPACITY_ERROR"
    )
    assert trace.model_routes[0].primary_error_code == "LLM_TIMEOUT"


def test_workflow_caps_model_timeout_to_remaining_request_deadline() -> None:
    provider = RoutingProvider(
        _generation(sql="SELECT title FROM film")
    )

    terminal = _run(
        "List film titles",
        _routing_runtime({"simple": provider}),
        clock=lambda: 119.5,
        workflow_started_at=0.0,
    )

    assert terminal.final_status is FinalStatus.SUCCEEDED_FIRST_PASS
    assert provider.timeouts == [0.5]


def test_unexpected_provider_failure_has_safe_routing_trace() -> None:
    class UnexpectedProvider(RoutingProvider):
        def generate(
            self,
            messages,
            *,
            timeout_seconds: float | None = None,
        ) -> GenerationResult:
            self.calls.append(tuple(messages))
            self.timeouts.append(timeout_seconds)
            raise RuntimeError("private provider implementation detail")

    provider = UnexpectedProvider(
        _generation(sql="SELECT title FROM film")
    )
    terminal = _run(
        "List film titles",
        _routing_runtime({"simple": provider}),
    )

    assert terminal.final_status is FinalStatus.FAILED_INTERNAL
    observation = terminal.model_routing_observations[0]
    assert observation.error_code == "LLM_INTERNAL_ERROR"
    assert observation.primary_error_code == "LLM_INTERNAL_ERROR"
    assert observation.failure_stage == "provider"
    serialized = build_trace_record(terminal).model_dump_json()
    assert "private provider implementation detail" not in serialized


def test_unknown_provider_code_has_safe_routing_trace() -> None:
    provider = RoutingProvider(
        LLMProviderError(
            LLMError(
                error_type=ErrorType.UNKNOWN,
                code="PRIVATE_VENDOR_CODE",
                retryable=True,
                public_message="private vendor detail",
            )
        )
    )
    terminal = _run(
        "List film titles",
        _routing_runtime({"simple": provider}),
    )

    assert terminal.final_status is FinalStatus.FAILED_INTERNAL
    observation = terminal.model_routing_observations[0]
    assert observation.error_code == "LLM_INTERNAL_ERROR"
    assert observation.primary_error_code == "LLM_INTERNAL_ERROR"
    serialized = build_trace_record(terminal).model_dump_json()
    assert "PRIVATE_VENDOR_CODE" not in serialized
    assert "private vendor detail" not in serialized


def test_normalization_failure_is_observed_and_sanitized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = RoutingProvider(
        _generation(sql="SELECT title FROM film")
    )
    monkeypatch.setattr(
        gen_sql_module,
        "normalize_generation_result",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            RuntimeError("private normalization detail")
        ),
    )

    terminal = _run(
        "List film titles",
        _routing_runtime({"simple": provider}),
    )

    assert terminal.final_status is FinalStatus.FAILED_INTERNAL
    observation = terminal.model_routing_observations[0]
    assert observation.provider_call_count == 1
    assert observation.error_code == "LLM_INTERNAL_ERROR"
    assert observation.primary_error_code is None
    assert observation.failure_stage == "normalization"
    serialized = build_trace_record(terminal).model_dump_json()
    assert "private normalization detail" not in serialized


def test_required_context_overflow_calls_no_provider() -> None:
    providers = {
        "simple": RoutingProvider(
            _generation(sql="SELECT title FROM film")
        ),
        "fallback": RoutingProvider(
            _generation(sql="SELECT title FROM film")
        ),
    }
    terminal = _run(
        "List film titles",
        _routing_runtime(
            providers,
            max_input_tokens=100,
            max_output_tokens=10,
            simple_fallback="fallback",
        ),
    )

    assert terminal.final_status is FinalStatus.FAILED_RESOURCE_RISK
    assert terminal.public_error is not None
    assert terminal.public_error.code == (
        "WORKFLOW_CONTEXT_REQUIRED_OVERFLOW"
    )
    assert providers["simple"].calls == []
    assert providers["fallback"].calls == []
    route_observation = terminal.model_routing_observations[0]
    context_observation = (
        terminal.context_selection_observations[0]
    )
    assert route_observation.provider_call_count == 0
    assert route_observation.outcome == "context_rejected"
    assert context_observation.outcome == "required_overflow"
    assert (
        context_observation.estimated_tokens
        > context_observation.usable_input_tokens
    )
    trace = build_trace_record(terminal)
    assert trace.model_routes[0].provider_call_count == 0
    assert trace.context_selections[0].outcome == (
        "required_overflow"
    )


def test_repair_context_is_rebudgeted_before_a_second_call() -> None:
    oversized_identifier = "missing_" + "x" * 8_000
    provider = RoutingProvider(
        _generation(
            sql=(
                f'SELECT "{oversized_identifier}" '
                "FROM film"
            )
        )
    )
    providers = {"simple": provider}
    terminal = _run(
        "List film titles",
        _routing_runtime(
            providers,
            max_input_tokens=2_048,
            max_output_tokens=128,
        ),
    )

    assert terminal.final_status is FinalStatus.FAILED_RESOURCE_RISK
    assert terminal.public_error is not None
    assert terminal.public_error.code == (
        "WORKFLOW_CONTEXT_REQUIRED_OVERFLOW"
    )
    assert len(provider.calls) == 1
    assert tuple(
        observation.outcome
        for observation in terminal.context_selection_observations
    ) == ("selected", "required_overflow")
    assert tuple(
        observation.provider_call_count
        for observation in terminal.model_routing_observations
    ) == (1, 0)
