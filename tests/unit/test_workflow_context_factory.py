import pytest

from app.config import LLMRouteSettings, LLMSettings


class _Connector:
    def read_metadata(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("metadata is outside context construction")

    def execute(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("execution is outside context construction")


class _EmbeddingProvider:
    model_id = "embedding-test"
    dimension = 3
    provider_config_sha256 = "e" * 64

    def embed(self, texts, *, timeout_seconds=None):  # type: ignore[no-untyped-def]
        raise AssertionError("embedding is outside context construction")


class _LLMProvider:
    def generate(
        self,
        messages,
        *,
        timeout_seconds=None,
    ):  # type: ignore[no-untyped-def]
        raise AssertionError("generation is outside context construction")


def _runtime():  # type: ignore[no-untyped-def]
    from app.generation.factory import ModelProviderFactory

    settings = LLMSettings(
        base_url="https://models.example.test/v1",
        api_key="test-secret",
        model="model",
    )
    route_settings = LLMRouteSettings(
        simple=settings,
        standard=settings,
        complex=settings,
        data_boundary_id="test-boundary",
    )
    return ModelProviderFactory(
        provider_builder=lambda _: _LLMProvider()
    ).create(route_settings)


def test_factory_builds_isolated_retrieval_registries_per_datasource() -> None:
    from app.api.context_factory import WorkflowContextFactory

    factory = WorkflowContextFactory()
    first = factory.create(
        connector=_Connector(),
        model_routing=_runtime(),
        datasource_id="first",
        allowed_schemas=("public",),
        allowed_tables=("public.orders",),
        embedding_provider=_EmbeddingProvider(),
        semantic_version="semantic-v1",
    )
    second = factory.create(
        connector=_Connector(),
        model_routing=_runtime(),
        datasource_id="second",
        allowed_schemas=("analytics",),
        allowed_tables=("analytics.events",),
        embedding_provider=_EmbeddingProvider(),
        semantic_version="semantic-v2",
    )

    assert first.datasource_id == "first"
    assert first.allowed_tables == ("public.orders",)
    assert first.retrieval_runtime is not None
    assert second.retrieval_runtime is not None
    assert first.retrieval_runtime.semantic_version == "semantic-v1"
    assert first.retrieval_runtime.registry is not second.retrieval_runtime.registry


def test_factory_builds_bm25_only_context_without_embedding_provider() -> None:
    from app.api.context_factory import WorkflowContextFactory

    context = WorkflowContextFactory().create(
        connector=_Connector(),
        model_routing=_runtime(),
        datasource_id="first",
        allowed_schemas=("public",),
        allowed_tables=("public.orders",),
        embedding_provider=None,
        semantic_version="semantic-v1",
    )

    assert context.retrieval_runtime is None


def test_factory_reuses_injected_embedding_registry() -> None:
    from app.api.context_factory import WorkflowContextFactory
    from app.schema_linking import EmbeddingIndexRegistry

    registry = EmbeddingIndexRegistry()
    context = WorkflowContextFactory().create(
        connector=_Connector(),
        model_routing=_runtime(),
        datasource_id="first",
        allowed_schemas=("public",),
        allowed_tables=("public.orders",),
        embedding_provider=_EmbeddingProvider(),
        embedding_registry=registry,
        semantic_version="semantic-v1",
    )

    assert context.retrieval_runtime is not None
    assert context.retrieval_runtime.registry is registry


def test_factory_rejects_embedding_registry_without_provider() -> None:
    from app.api.context_factory import WorkflowContextFactory
    from app.schema_linking import EmbeddingIndexRegistry

    with pytest.raises(ValueError, match="embedding registry"):
        WorkflowContextFactory().create(
            connector=_Connector(),
            model_routing=_runtime(),
            datasource_id="first",
            allowed_schemas=("public",),
            allowed_tables=("public.orders",),
            embedding_provider=None,
            embedding_registry=EmbeddingIndexRegistry(),
            semantic_version="semantic-v1",
        )
