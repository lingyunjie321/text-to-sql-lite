from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import SecretStr

from app.local.credential_store import InMemoryCredentialStore
from app.local.datasource_service import (
    DatasourceProfileNotFoundError,
    DatasourceProfileService,
)
from app.local.model_service import ModelProfileNotFoundError, ModelProfileService
from app.local.profile_models import DatasourceProfile, ModelProfile
from app.local.profile_store import LocalProfileStore


def _model(
    *,
    name: str = "Local Model",
    base_url: str = "http://localhost:11434/v1",
) -> ModelProfile:
    return ModelProfile(
        id="local-model",
        name=name,
        provider_type="openai_compatible",
        base_url=base_url,
        model_name="qwen2.5-coder",
    )


def _datasource(
    *,
    name: str = "Local PostgreSQL",
    host: str = "127.0.0.1",
) -> DatasourceProfile:
    return DatasourceProfile(
        id="local-postgres",
        name=name,
        database_type="postgresql",
        host=host,
        port=5432,
        database="analytics",
        username="reader",
        allowed_schemas=("public",),
        allowed_tables=("public.orders",),
    )


def test_model_service_persists_profile_but_not_api_key(tmp_path: Path) -> None:
    database_path = tmp_path / "config.db"
    credentials = InMemoryCredentialStore()
    service = ModelProfileService(LocalProfileStore(database_path), credentials)

    view = service.create(
        _model(),
        generation_api_key=SecretStr("stage2-generation-secret"),
    )

    assert view.profile == _model()
    assert view.generation_credential_status == "configured"
    assert view.embedding_credential_status == "not_applicable"
    assert b"stage2-generation-secret" not in database_path.read_bytes()


def test_model_service_reports_missing_credentials_after_restart(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "config.db"
    first = ModelProfileService(
        LocalProfileStore(database_path),
        InMemoryCredentialStore(),
    )
    first.create(_model(), generation_api_key=SecretStr("secret"))

    restarted = ModelProfileService(
        LocalProfileStore(database_path),
        InMemoryCredentialStore(),
    )

    view = restarted.get("local-model")
    assert view.profile == _model()
    assert view.generation_credential_status == "missing"


def test_model_service_preserves_or_clears_key_by_update_semantics(
    tmp_path: Path,
) -> None:
    credentials = InMemoryCredentialStore()
    service = ModelProfileService(
        LocalProfileStore(tmp_path / "config.db"),
        credentials,
    )
    service.create(_model(), generation_api_key=SecretStr("secret"))

    renamed = service.replace(_model(name="Renamed"))
    assert renamed.generation_credential_status == "configured"

    moved = service.replace(_model(name="Renamed", base_url="http://localhost:1234/v1"))
    assert moved.generation_credential_status == "missing"

    service.replace(
        _model(name="Renamed", base_url="http://localhost:1234/v1"),
        generation_api_key=SecretStr("replacement"),
    )
    cleared = service.replace(
        _model(name="Renamed", base_url="http://localhost:1234/v1"),
        generation_api_key=None,
    )
    assert cleared.generation_credential_status == "missing"


def test_model_service_delete_clears_credentials_and_reports_missing(
    tmp_path: Path,
) -> None:
    credentials = InMemoryCredentialStore()
    service = ModelProfileService(
        LocalProfileStore(tmp_path / "config.db"),
        credentials,
    )
    service.create(_model(), generation_api_key=SecretStr("secret"))

    service.delete("local-model")

    assert credentials.get_model("local-model") is None
    with pytest.raises(ModelProfileNotFoundError) as exc_info:
        service.get("local-model")
    assert exc_info.value.code == "MODEL_PROFILE_NOT_FOUND"


def test_datasource_service_persists_profile_but_not_password(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "config.db"
    credentials = InMemoryCredentialStore()
    service = DatasourceProfileService(
        LocalProfileStore(database_path),
        credentials,
    )

    view = service.create(
        _datasource(),
        password=SecretStr("stage2-database-secret"),
    )

    assert view.profile == _datasource()
    assert view.password_status == "configured"
    assert b"stage2-database-secret" not in database_path.read_bytes()


def test_datasource_service_only_clears_password_for_identity_changes(
    tmp_path: Path,
) -> None:
    service = DatasourceProfileService(
        LocalProfileStore(tmp_path / "config.db"),
        InMemoryCredentialStore(),
    )
    service.create(_datasource(), password=SecretStr("secret"))

    renamed = service.replace(_datasource(name="Renamed"))
    assert renamed.password_status == "configured"

    moved = service.replace(_datasource(name="Renamed", host="localhost"))
    assert moved.password_status == "missing"


def test_datasource_service_delete_clears_password_and_reports_missing(
    tmp_path: Path,
) -> None:
    credentials = InMemoryCredentialStore()
    service = DatasourceProfileService(
        LocalProfileStore(tmp_path / "config.db"),
        credentials,
    )
    service.create(_datasource(), password=SecretStr("secret"))

    service.delete("local-postgres")

    assert credentials.get_datasource("local-postgres") is None
    with pytest.raises(DatasourceProfileNotFoundError) as exc_info:
        service.get("local-postgres")
    assert exc_info.value.code == "DATASOURCE_PROFILE_NOT_FOUND"
