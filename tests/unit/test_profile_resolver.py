from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock

import pytest

from app.config import DatabaseSettings, LLMRouteSettings, LLMSettings
from app.local.credential_store import InMemoryCredentialStore
from app.local.datasource_service import DatasourceProfileService
from app.local.model_service import ModelProfileService
from app.local.profile_models import DatasourceProfile, ModelProfile
from app.local.profile_resolver import (
    ProfileResolutionError,
    StaticProfileResolver,
    build_static_datasource_profile,
    build_static_model_profile,
)
from app.local.profile_store import LocalProfileStore
from app.workflow import WorkflowContext
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


def _resolver(
    tmp_path: Path,
) -> tuple[
    StaticProfileResolver,
    ModelProfileService,
    DatasourceProfileService,
]:
    store = LocalProfileStore(tmp_path / "config.db")
    credentials = InMemoryCredentialStore()
    models = ModelProfileService(store, credentials)
    datasources = DatasourceProfileService(store, credentials)
    models.create(_stored_model())
    datasources.create(_stored_datasource())
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
    )
    return resolver, models, datasources


def test_resolver_returns_only_explicitly_matching_static_context(
    tmp_path: Path,
) -> None:
    resolver, _, _ = _resolver(tmp_path)

    context = resolver.resolve(
        datasource_profile_id="pagila",
        model_profile_id="local-model",
    )

    assert context.datasource_id == "pagila"


def test_resolver_returns_specific_not_found_error_without_echoing_id(
    tmp_path: Path,
) -> None:
    resolver, _, _ = _resolver(tmp_path)

    with pytest.raises(ProfileResolutionError) as exc_info:
        resolver.resolve(
            datasource_profile_id="missing-database",
            model_profile_id="local-model",
        )

    assert exc_info.value.code == "DATASOURCE_PROFILE_NOT_FOUND"
    assert exc_info.value.status_code == 404
    assert "missing-database" not in str(exc_info.value)


@pytest.mark.parametrize(
    ("profile_kind", "expected_code"),
    [
        ("datasource", "PROFILE_RUNTIME_UNAVAILABLE"),
        ("model", "PROFILE_RUNTIME_UNAVAILABLE"),
    ],
)
def test_resolver_rejects_profiles_that_do_not_match_static_runtime(
    tmp_path: Path,
    profile_kind: str,
    expected_code: str,
) -> None:
    resolver, models, datasources = _resolver(tmp_path)
    if profile_kind == "datasource":
        datasources.replace(_stored_datasource(host="localhost"))
    else:
        models.replace(_stored_model(base_url="https://other.example.test/v1"))

    with pytest.raises(ProfileResolutionError) as exc_info:
        resolver.resolve(
            datasource_profile_id="pagila",
            model_profile_id="local-model",
        )

    assert exc_info.value.code == expected_code
    assert exc_info.value.status_code == 409


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
