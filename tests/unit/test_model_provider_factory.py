from app.config import LLMRouteSettings, LLMSettings


class _Provider:
    def generate(
        self,
        messages,
        *,
        timeout_seconds=None,
    ):  # type: ignore[no-untyped-def]
        raise AssertionError("generation is outside this construction test")


def _settings() -> LLMRouteSettings:
    values = {
        key: LLMSettings(
            base_url="https://models.example.test/v1",
            api_key="test-secret",
            model=f"model-{key}",
        )
        for key in ("simple", "standard", "complex", "fallback")
    }
    return LLMRouteSettings(
        simple=values["simple"],
        standard=values["standard"],
        complex=values["complex"],
        fallback=values["fallback"],
        fallback_route_ids=("simple_route",),
        data_boundary_id="test-boundary",
    )


def test_factory_preserves_declared_routes_fallback_and_boundary(
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    from app.generation import factory

    monkeypatch.setattr(
        factory,
        "OpenAICompatibleLLMProvider",
        lambda settings: _Provider(),
    )

    runtime = factory.ModelProviderFactory().create(_settings())

    simple = runtime.route_table.select("simple")
    standard = runtime.route_table.select("medium")
    complex_route = runtime.route_table.select("complex")
    assert simple.primary.provider_key == "simple"
    assert simple.fallback is not None
    assert simple.fallback.provider_key == "fallback"
    assert standard.fallback is None
    assert complex_route.fallback is None
    assert {
        target.data_boundary_id
        for route in runtime.route_table.routes
        for target in (route.primary, route.fallback)
        if target is not None
    } == {"test-boundary"}


def test_factory_maps_one_provider_to_all_primary_routes() -> None:
    from app.generation.factory import ModelProviderFactory

    factory = ModelProviderFactory(provider_builder=lambda settings: _Provider())
    runtime = factory.create_single(
        LLMSettings(
            base_url="http://localhost:11434/v1",
            api_key=None,
            model="local-model",
        ),
        data_boundary_id="local-profile:local-model",
    )

    routes = runtime.route_table.routes
    assert tuple(route.route_id for route in routes) == (
        "simple_route",
        "standard_route",
        "complex_route",
    )
    assert {route.primary.provider_key for route in routes} == {"primary"}
    assert len(
        {route.primary.model_config_sha256 for route in routes}
    ) == 1
    assert all(route.fallback is None for route in routes)
    assert {
        route.primary.data_boundary_id for route in routes
    } == {"local-profile:local-model"}
