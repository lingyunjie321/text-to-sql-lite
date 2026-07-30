from dataclasses import replace

import pytest
from pydantic import ValidationError

from app.api.models import QueryRequest
from app.generation import (
    GenerationResult,
    GeneratedSQL,
    ModelRoute,
    ModelRouteTable,
    ModelRoutingRuntime,
    ModelTarget,
    ProviderRegistry,
    RegisteredProvider,
)


class Provider:
    def generate(self, messages, *, timeout_seconds=None):
        del messages, timeout_seconds
        return GenerationResult(
            output=GeneratedSQL(sql="SELECT 1"),
            input_tokens=0,
            output_tokens=0,
            model="private-model-name",
            prompt_version="mvp-v1",
        )


@pytest.mark.parametrize(
    "injected",
    (
        {"model": "attacker-model"},
        {"complexity": "simple"},
        {"top_k": 20},
    ),
)
def test_request_cannot_select_model_complexity_or_top_k(
    injected: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        QueryRequest.model_validate(
            {
                "question": "List films",
                **injected,
            }
        )


def test_routing_runtime_repr_hides_provider_and_boundary() -> None:
    provider_key = "private-provider-key"
    boundary = "private-processing-boundary"
    target = ModelTarget(
        provider_key=provider_key,
        model_config_sha256="a" * 64,
        max_input_tokens=32_768,
        max_output_tokens=2_048,
        timeout_seconds=30,
        data_boundary_id=boundary,
    )
    runtime = ModelRoutingRuntime(
        provider_registry=ProviderRegistry(
            {
                provider_key: RegisteredProvider(
                    provider=Provider(),
                    model_config_sha256="a" * 64,
                    timeout_seconds=30,
                )
            }
        ),
        route_table=ModelRouteTable(
            routes=(
                ModelRoute(
                    route_id="simple_route",
                    primary=target,
                ),
                ModelRoute(
                    route_id="standard_route",
                    primary=target,
                ),
                ModelRoute(
                    route_id="complex_route",
                    primary=target,
                ),
            )
        ),
    )

    rendered = repr(runtime)
    assert provider_key not in rendered
    assert boundary not in rendered
    assert "private-model-name" not in rendered


def test_route_table_is_not_affected_by_source_tuple_replacement() -> None:
    target = ModelTarget(
        provider_key="primary",
        model_config_sha256="a" * 64,
        max_input_tokens=32_768,
        max_output_tokens=2_048,
        timeout_seconds=30,
        data_boundary_id="boundary",
    )
    routes = (
        ModelRoute(route_id="simple_route", primary=target),
        ModelRoute(route_id="standard_route", primary=target),
        ModelRoute(route_id="complex_route", primary=target),
    )
    table = ModelRouteTable(routes=routes)
    changed = replace(
        routes[0],
        route_id="complex_route",
    )

    assert table.select("simple") is routes[0]
    assert changed is not table.select("simple")
