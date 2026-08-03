"""Datasource profile CRUD and in-memory credential coordination."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, cast

from pydantic import SecretStr

from app.connectors.catalog import DiscoveredMetadata
from app.local.credential_store import (
    DatasourceCredentials,
    InMemoryCredentialStore,
)
from app.local.datasource_runtime import (
    DatasourceRuntimeError,
    DatasourceRuntimeService,
)
from app.local.profile_models import DatasourceProfile
from app.local.profile_store import (
    LocalProfileStore,
    ProfileAlreadyExistsError,
)
from app.local.runtime_registry import RuntimeRegistry

_NOT_PROVIDED = object()


class DatasourceProfileNotFoundError(RuntimeError):
    code = "DATASOURCE_PROFILE_NOT_FOUND"

    def __init__(self) -> None:
        super().__init__("datasource profile was not found")


@dataclass(frozen=True, slots=True)
class DatasourceProfileView:
    profile: DatasourceProfile
    password_status: Literal["configured", "missing"]


class DatasourceProfileService:
    """Coordinate non-sensitive datasource profiles and process-local keys."""

    def __init__(
        self,
        store: LocalProfileStore,
        credentials: InMemoryCredentialStore,
        *,
        runtime_service: DatasourceRuntimeService,
        runtime_registry: RuntimeRegistry,
    ) -> None:
        self._store = store
        self._credentials = credentials
        self._runtime_service = runtime_service
        self._runtime_registry = runtime_registry

    def create(
        self,
        profile: DatasourceProfile,
        *,
        password: SecretStr | None = None,
    ) -> DatasourceProfileView:
        if self._store.get_datasource(profile.id) is not None:
            raise ProfileAlreadyExistsError()
        if password is None:
            raise _credential_missing_error()
        self._runtime_service.validate_profile(profile, password)
        created = self._store.create_datasource(profile)
        self._credentials.put_datasource(
            profile.id,
            DatasourceCredentials(password=password),
        )
        return self._view(created)

    def get(self, profile_id: str) -> DatasourceProfileView:
        profile = self._store.get_datasource(profile_id)
        if profile is None:
            raise DatasourceProfileNotFoundError()
        return self._view(profile)

    def list(self) -> tuple[DatasourceProfileView, ...]:
        return tuple(
            self._view(profile) for profile in self._store.list_datasources()
        )

    def discover_metadata(self, profile_id: str) -> DiscoveredMetadata:
        profile = self._store.get_datasource(profile_id)
        if profile is None:
            raise DatasourceProfileNotFoundError()
        credentials = self._credentials.get_datasource(profile_id)
        if credentials is None or credentials.password is None:
            raise _credential_missing_error()
        return self._runtime_service.discover_profile(
            profile,
            credentials.password,
        )

    def replace(
        self,
        profile: DatasourceProfile,
        *,
        password: SecretStr | None | object = _NOT_PROVIDED,
    ) -> DatasourceProfileView:
        current = self._store.get_datasource(profile.id)
        if current is None:
            raise DatasourceProfileNotFoundError()
        existing = (
            self._credentials.get_datasource(profile.id)
            or DatasourceCredentials()
        )
        identity_changed = (
            current.database_type != profile.database_type
            or current.host != profile.host
            or current.port != profile.port
            or current.database != profile.database
            or current.username != profile.username
        )
        allowlist_changed = (
            current.allowed_schemas != profile.allowed_schemas
            or current.allowed_tables != profile.allowed_tables
        )
        protected_configuration_changed = (
            identity_changed or allowlist_changed
        )

        if password is None:
            if protected_configuration_changed:
                raise _credential_missing_error()
            self._runtime_registry.invalidate(profile.id)
            replaced = self._store.replace_datasource(profile)
            self._credentials.discard_datasource(profile.id)
            return self._view(replaced)

        next_password = (
            existing.password
            if password is _NOT_PROVIDED
            else cast(SecretStr, password)
        )
        should_validate = (
            protected_configuration_changed
            or password is not _NOT_PROVIDED
        )
        if should_validate:
            if next_password is None:
                raise _credential_missing_error()
            self._runtime_service.validate_profile(profile, next_password)
            self._runtime_registry.invalidate(profile.id)

        replaced = self._store.replace_datasource(profile)
        self._credentials.put_datasource(
            profile.id,
            DatasourceCredentials(
                password=cast(SecretStr | None, next_password)
            ),
        )
        return self._view(replaced)

    def delete(self, profile_id: str) -> None:
        if self._store.get_datasource(profile_id) is None:
            raise DatasourceProfileNotFoundError()
        self._runtime_registry.invalidate(profile_id)
        if not self._store.delete_datasource(profile_id):
            raise DatasourceProfileNotFoundError()
        self._credentials.discard_datasource(profile_id)

    def _view(self, profile: DatasourceProfile) -> DatasourceProfileView:
        credentials = self._credentials.get_datasource(profile.id)
        status: Literal["configured", "missing"] = (
            "configured"
            if credentials is not None and credentials.password is not None
            else "missing"
        )
        return DatasourceProfileView(profile=profile, password_status=status)


def _credential_missing_error() -> DatasourceRuntimeError:
    return DatasourceRuntimeError(
        code="DATASOURCE_CREDENTIAL_MISSING",
        public_message="The datasource password is not available.",
        status_code=409,
    )
