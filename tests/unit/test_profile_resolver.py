from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from pydantic import SecretStr

from app.config import DatabaseSettings, LLMRouteSettings, LLMSettings
from app.local.credential_store import InMemoryCredentialStore
from app.local.datasource_service import DatasourceProfileService
from app.local.model_service import ModelProfileService
from app.local.model_runtime import ModelRuntimeError
from app.local.profile_models import DatasourceProfile, ModelProfile
from app.local.profile_resolver import (
    ProfileResolutionError,
    StaticProfileResolver,
    build_static_datasource_profile,
    build_static_model_profile,
)
from app.local.profile_store import LocalProfileStore
from app.local.datasource_runtime import DatasourceRuntimeError
from app.workflow import WorkflowContext
from app.schema_linking import EmbeddingIndexRegistry
from tests.routing_support import single_provider_test_routing


def _stored_model(*, base_url: str = "https://models.example.test/v1") -> ModelProfile:
    return ModelProfile(
        id="local-model",
        name="Selected Model",
        provider_type="openai_compatible",
        base_url=base_url,
        model_name="text-to-sql-model",
    )


def _stored_datasource(*, host: str = "127.0.0.1") -> DatasourceProfile:
    return DatasourceProfile(
        id="pagila",
        name="Selected Database",
        database_type="postgresql",
        host=host,
        port=55432,
        database="pagila",
        username="reader",
        allowed_schemas=("public",),
        allowed_tables=("public.film",),
    )


def _context() -> WorkflowContext:
    return WorkflowContext(
        connector=Mock(),
        model_routing=single_provider_test_routing(Mock()),
        datasource_id="pagila",
        allowed_schemas=("public",),
        allowed_tables=("public.film",),
    )


class _RuntimeService:
    def validate_profile(self, profile, password):  # type: ignore[no-untyped-def]
        del profile, password


class _RuntimeRegistry:
    def __init__(self) -> None:
        self.get_calls: list[DatasourceProfile] = []
        self.invalidated: list[str] = []
        self.error: Exception | None = None
        self.context = _context()

    def get_or_create(self, profile):  # type: ignore[no-untyped-def]
        self.get_calls.append(profile)
        if self.error is not None:
            raise self.error
        return SimpleNamespace(
            context=self.context,
            semantic_version="0.0.0",
        )

    def invalidate(
        self,
        profile_id: str,
        *,
        expected_profile=None,
    ) -> None:
        del expected_profile
        self.invalidated.append(profile_id)


class _ModelRuntimeRegistry:
    def __init__(self) -> None:
        self.get_calls: list[ModelProfile] = []
        self.error: Exception | None = None
        self.model_routing = single_provider_test_routing(Mock())
        self.embedding_registry = EmbeddingIndexRegistry()

    def get_or_create(self, profile):  # type: ignore[no-untyped-def]
        self.get_calls.append(profile)
        if self.error is not None:
            raise self.error
        return SimpleNamespace(
            model_routing=self.model_routing,
            embedding_provider=None,
            embedding_registry=self.embedding_registry,
        )


def _resolver(
    tmp_path: Path,
) -> tuple[
    StaticProfileResolver,
    ModelProfileService,
    DatasourceProfileService,
    _RuntimeRegistry,
]:
    store = LocalProfileStore(tmp_path / "config.db")
    credentials = InMemoryCredentialStore()
    models = ModelProfileService(store, credentials)
    runtime_registry = _RuntimeRegistry()
    datasources = DatasourceProfileService(
        store,
        credentials,
        runtime_service=_RuntimeService(),
        runtime_registry=runtime_registry,
    )
    models.create(_stored_model())
    datasources.create(_stored_datasource(), password=SecretStr("secret"))
    resolver = StaticProfileResolver(
        model_profiles=models,
        datasource_profiles=datasources,
        contexts={"pagila": _context()},
        active_model=ModelProfile(
            id="environment-model",
            name="Environment Model",
            provider_type="openai_compatible",
            base_url="https://models.example.test/v1",
            model_name="text-to-sql-model",
        ),
        active_datasources={
            "pagila": DatasourceProfile(
                id="pagila",
                name="Environment Database",
                database_type="postgresql",
                host="127.0.0.1",
                port=55432,
                database="pagila",
                username="reader",
                allowed_schemas=("public",),
                allowed_tables=("public.film",),
            )
        },
        runtime_registry=runtime_registry,
    )
    return resolver, models, datasources, runtime_registry


def test_resolver_returns_only_explicitly_matching_static_context(
    tmp_path: Path,
) -> None:
    resolver, _, _, runtime_registry = _resolver(tmp_path)

    context = resolver.resolve(
        datasource_profile_id="pagila",
        model_profile_id="local-model",
    )

    assert context.datasource_id == "pagila"
    assert runtime_registry.get_calls == []


def test_resolver_returns_specific_not_found_error_without_echoing_id(
    tmp_path: Path,
) -> None:
    resolver, _, _, _ = _resolver(tmp_path)

    with pytest.raises(ProfileResolutionError) as exc_info:
        resolver.resolve(
            datasource_profile_id="missing-database",
            model_profile_id="local-model",
        )

    assert exc_info.value.code == "DATASOURCE_PROFILE_NOT_FOUND"
    assert exc_info.value.status_code == 404
    assert "missing-database" not in str(exc_info.value)


def test_resolver_uses_dynamic_runtime_for_non_static_datasource(
    tmp_path: Path,
) -> None:
    resolver, _, datasources, runtime_registry = _resolver(tmp_path)
    changed = _stored_datasource(host="localhost")
    datasources.replace(changed)

    context = resolver.resolve(
        datasource_profile_id="pagila",
        model_profile_id="local-model",
    )

    assert context is runtime_registry.context
    assert runtime_registry.get_calls == [changed]


def test_resolver_rejects_model_that_does_not_match_static_runtime(
    tmp_path: Path,
) -> None:
    resolver, models, _, runtime_registry = _resolver(tmp_path)
    models.replace(_stored_model(base_url="https://other.example.test/v1"))

    with pytest.raises(ProfileResolutionError) as exc_info:
        resolver.resolve(
            datasource_profile_id="pagila",
            model_profile_id="local-model",
        )

    assert exc_info.value.code == "PROFILE_RUNTIME_UNAVAILABLE"
    assert exc_info.value.status_code == 409
    assert runtime_registry.get_calls == []


def test_resolver_composes_dynamic_model_with_static_datasource(
    tmp_path: Path,
) -> None:
    from app.api.context_factory import WorkflowContextFactory

    _, models, datasources, runtime_registry = _resolver(tmp_path)
    models.replace(_stored_model(base_url="https://other.example.test/v1"))
    model_registry = _ModelRuntimeRegistry()
    static_context = _context()
    resolver = StaticProfileResolver(
        model_profiles=models,
        datasource_profiles=datasources,
        contexts={"pagila": static_context},
        active_model=None,
        active_datasources={"pagila": _stored_datasource()},
        runtime_registry=runtime_registry,
        model_runtime_registry=model_registry,  # type: ignore[arg-type]
        context_factory=WorkflowContextFactory(),
    )

    context = resolver.resolve(
        datasource_profile_id="pagila",
        model_profile_id="local-model",
    )

    assert context.connector is static_context.connector
    assert context.model_routing is model_registry.model_routing
    assert context.retrieval_runtime is None
    assert model_registry.get_calls == [
        _stored_model(base_url="https://other.example.test/v1")
    ]


def test_resolver_maps_dynamic_model_runtime_failure_without_fallback(
    tmp_path: Path,
) -> None:
    from app.api.context_factory import WorkflowContextFactory

    _, models, datasources, runtime_registry = _resolver(tmp_path)
    model_registry = _ModelRuntimeRegistry()
    model_registry.error = ModelRuntimeError(
        code="MODEL_RUNTIME_UNAVAILABLE",
        public_message="The model runtime is unavailable.",
        status_code=503,
    )
    resolver = StaticProfileResolver(
        model_profiles=models,
        datasource_profiles=datasources,
        contexts={"pagila": _context()},
        active_model=None,
        active_datasources={"pagila": _stored_datasource()},
        runtime_registry=runtime_registry,
        model_runtime_registry=model_registry,  # type: ignore[arg-type]
        context_factory=WorkflowContextFactory(),
    )

    with pytest.raises(ProfileResolutionError) as exc_info:
        resolver.resolve(
            datasource_profile_id="pagila",
            model_profile_id="local-model",
        )

    assert exc_info.value.code == "MODEL_RUNTIME_UNAVAILABLE"
    assert exc_info.value.status_code == 503


def test_dynamic_runtime_error_is_preserved_without_static_fallback(
    tmp_path: Path,
) -> None:
    resolver, _, datasources, runtime_registry = _resolver(tmp_path)
    datasources.replace(_stored_datasource(host="localhost"))
    runtime_registry.error = DatasourceRuntimeError(
        code="DATASOURCE_CONNECTION_FAILED",
        public_message="The datasource connection failed.",
        status_code=503,
    )

    with pytest.raises(ProfileResolutionError) as exc_info:
        resolver.resolve(
            datasource_profile_id="pagila",
            model_profile_id="local-model",
        )

    assert exc_info.value.code == "DATASOURCE_CONNECTION_FAILED"
    assert exc_info.value.status_code == 503


def test_static_datasource_profile_parses_postgres_dsn_without_password() -> None:
    settings = DatabaseSettings(
        datasource_id="pagila",
        dsn=(
            "postgresql://reader:stage2-secret@127.0.0.1:55432/pagila"
            "?sslmode=disable"
        ),
    )

    profile = build_static_datasource_profile(
        settings,
        allowed_schemas=("public",),
        allowed_tables=("public.film",),
    )

    assert profile is not None
    assert profile.id == "pagila"
    assert profile.host == "127.0.0.1"
    assert profile.port == 55432
    assert profile.database == "pagila"
    assert profile.username == "reader"
    assert "stage2-secret" not in repr(profile)
    assert "stage2-secret" not in str(profile.model_dump())


def test_static_model_profile_requires_one_common_primary_model() -> None:
    common = LLMSettings(
        base_url="https://models.example.test/v1",
        api_key="stage2-secret",
        model="text-to-sql-model",
    )
    common_routes = LLMRouteSettings(
        simple=common,
        standard=common,
        complex=common,
        data_boundary_id="test-boundary",
    )
    split_routes = LLMRouteSettings(
        simple=common,
        standard=common,
        complex=LLMSettings(
            base_url="https://models.example.test/v1",
            api_key="stage2-secret",
            model="complex-model",
        ),
        data_boundary_id="test-boundary",
    )

    profile = build_static_model_profile(common_routes)

    assert profile is not None
    assert profile.model_name == "text-to-sql-model"
    assert "stage2-secret" not in repr(profile)
    assert build_static_model_profile(split_routes) is None
