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
