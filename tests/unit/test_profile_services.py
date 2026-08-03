from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import SecretStr

from app.local.credential_store import InMemoryCredentialStore
from app.local.datasource_service import (
    DatasourceProfileNotFoundError,
    DatasourceProfileService,
)
from app.local.datasource_runtime import DatasourceRuntimeError
from app.local.model_service import ModelProfileNotFoundError, ModelProfileService
from app.local.profile_models import DatasourceProfile, ModelProfile
from app.local.profile_store import (
    LocalProfileStore,
    ProfileAlreadyExistsError,
)


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
    allowed_tables: tuple[str, ...] = ("public.orders",),
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
        allowed_tables=allowed_tables,
    )


class _DatasourceRuntimeService:
    def __init__(self) -> None:
        self.validations: list[tuple[DatasourceProfile, str]] = []
        self.error: Exception | None = None
        self.discoveries: list[tuple[DatasourceProfile, str]] = []
        self.discovered = object()

    def validate_profile(
        self,
        profile: DatasourceProfile,
        password: SecretStr,
    ) -> object:
        self.validations.append((profile, password.get_secret_value()))
        if self.error is not None:
            raise self.error
        return object()

    def discover_profile(
        self,
        profile: DatasourceProfile,
        password: SecretStr,
    ) -> object:
        self.discoveries.append((profile, password.get_secret_value()))
        if self.error is not None:
            raise self.error
        return self.discovered


class _RuntimeRegistry:
    def __init__(self) -> None:
        self.invalidated: list[str] = []

    def invalidate(self, profile_id: str) -> None:
        self.invalidated.append(profile_id)


def _datasource_service(
    database_path: Path,
    credentials: InMemoryCredentialStore | None = None,
) -> tuple[
    DatasourceProfileService,
    _DatasourceRuntimeService,
    _RuntimeRegistry,
]:
    runtime_service = _DatasourceRuntimeService()
    registry = _RuntimeRegistry()
    service = DatasourceProfileService(
        LocalProfileStore(database_path),
        credentials or InMemoryCredentialStore(),
        runtime_service=runtime_service,
        runtime_registry=registry,
    )
    return service, runtime_service, registry


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
    service, runtime_service, _ = _datasource_service(
        database_path,
        credentials,
    )

    view = service.create(
        _datasource(),
        password=SecretStr("stage2-database-secret"),
    )

    assert view.profile == _datasource()
    assert view.password_status == "configured"
    assert b"stage2-database-secret" not in database_path.read_bytes()
    assert runtime_service.validations == [
        (_datasource(), "stage2-database-secret")
    ]


def test_datasource_service_only_clears_password_for_identity_changes(
    tmp_path: Path,
) -> None:
    service, runtime_service, registry = _datasource_service(
        tmp_path / "config.db"
    )
    service.create(_datasource(), password=SecretStr("secret"))
    runtime_service.validations.clear()

    renamed = service.replace(_datasource(name="Renamed"))
    assert renamed.password_status == "configured"
    assert runtime_service.validations == []
    assert registry.invalidated == []

    moved = service.replace(_datasource(name="Renamed", host="localhost"))
    assert moved.password_status == "configured"
    assert runtime_service.validations == [
        (_datasource(name="Renamed", host="localhost"), "secret")
    ]
    assert registry.invalidated == ["local-postgres"]


def test_datasource_service_delete_clears_password_and_reports_missing(
    tmp_path: Path,
) -> None:
    credentials = InMemoryCredentialStore()
    service, _, registry = _datasource_service(
        tmp_path / "config.db",
        credentials,
    )
    service.create(_datasource(), password=SecretStr("secret"))

    service.delete("local-postgres")

    assert credentials.get_datasource("local-postgres") is None
    assert registry.invalidated == ["local-postgres"]
    with pytest.raises(DatasourceProfileNotFoundError) as exc_info:
        service.get("local-postgres")
    assert exc_info.value.code == "DATASOURCE_PROFILE_NOT_FOUND"


def test_datasource_create_requires_password_and_does_not_persist(
    tmp_path: Path,
) -> None:
    service, runtime_service, _ = _datasource_service(
        tmp_path / "config.db"
    )

    with pytest.raises(DatasourceRuntimeError) as captured:
        service.create(_datasource())

    assert captured.value.code == "DATASOURCE_CREDENTIAL_MISSING"
    assert runtime_service.validations == []
    with pytest.raises(DatasourceProfileNotFoundError):
        service.get("local-postgres")


def test_invalid_allowlist_create_does_not_persist_profile_or_password(
    tmp_path: Path,
) -> None:
    credentials = InMemoryCredentialStore()
    service, runtime_service, registry = _datasource_service(
        tmp_path / "config.db",
        credentials,
    )
    runtime_service.error = DatasourceRuntimeError(
        code="DATASOURCE_ALLOWLIST_INVALID",
        public_message="The datasource allowlist is invalid.",
        status_code=409,
    )

    with pytest.raises(DatasourceRuntimeError):
        service.create(_datasource(), password=SecretStr("private-secret"))

    assert credentials.get_datasource("local-postgres") is None
    assert registry.invalidated == []
    with pytest.raises(DatasourceProfileNotFoundError):
        service.get("local-postgres")


def test_duplicate_datasource_is_rejected_without_second_connection_test(
    tmp_path: Path,
) -> None:
    service, runtime_service, _ = _datasource_service(
        tmp_path / "config.db"
    )
    service.create(_datasource(), password=SecretStr("secret"))

    with pytest.raises(ProfileAlreadyExistsError):
        service.create(_datasource(), password=SecretStr("other-secret"))

    assert runtime_service.validations == [(_datasource(), "secret")]


def test_failed_update_preserves_profile_password_and_runtime(
    tmp_path: Path,
) -> None:
    credentials = InMemoryCredentialStore()
    service, runtime_service, registry = _datasource_service(
        tmp_path / "config.db",
        credentials,
    )
    service.create(_datasource(), password=SecretStr("old-secret"))
    runtime_service.error = DatasourceRuntimeError(
        code="DATASOURCE_CONNECTION_FAILED",
        public_message="The datasource connection failed.",
        status_code=503,
    )

    with pytest.raises(DatasourceRuntimeError):
        service.replace(
            _datasource(host="localhost"),
            password=SecretStr("new-secret"),
        )

    assert service.get("local-postgres").profile == _datasource()
    stored = credentials.get_datasource("local-postgres")
    assert stored is not None and stored.password is not None
    assert stored.password.get_secret_value() == "old-secret"
    assert registry.invalidated == []


def test_allowlist_update_uses_existing_password_before_invalidation(
    tmp_path: Path,
) -> None:
    service, runtime_service, registry = _datasource_service(
        tmp_path / "config.db"
    )
    service.create(_datasource(), password=SecretStr("secret"))
    runtime_service.validations.clear()
    changed = _datasource(
        allowed_tables=("public.orders", "public.customers")
    )

    view = service.replace(changed)

    assert view.profile == changed
    assert runtime_service.validations == [(changed, "secret")]
    assert registry.invalidated == ["local-postgres"]


def test_explicit_null_password_clears_credential_and_runtime_without_connecting(
    tmp_path: Path,
) -> None:
    service, runtime_service, registry = _datasource_service(
        tmp_path / "config.db"
    )
    service.create(_datasource(), password=SecretStr("secret"))
    runtime_service.validations.clear()

    view = service.replace(_datasource(name="Password cleared"), password=None)

    assert view.password_status == "missing"
    assert runtime_service.validations == []
    assert registry.invalidated == ["local-postgres"]


def test_metadata_discovery_uses_profile_credential_without_query_registry(
    tmp_path: Path,
) -> None:
    service, runtime_service, registry = _datasource_service(
        tmp_path / "config.db"
    )
    service.create(_datasource(), password=SecretStr("secret"))
    runtime_service.error = None

    discovered = service.discover_metadata("local-postgres")

    assert discovered is runtime_service.discovered
    assert runtime_service.discoveries == [(_datasource(), "secret")]
    assert registry.invalidated == []
