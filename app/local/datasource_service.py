"""Datasource profile CRUD and in-memory credential coordination."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, cast

from pydantic import SecretStr

from app.local.credential_store import (
    DatasourceCredentials,
    InMemoryCredentialStore,
)
from app.local.profile_models import DatasourceProfile
from app.local.profile_store import LocalProfileStore

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
    ) -> None:
        self._store = store
        self._credentials = credentials

    def create(
        self,
        profile: DatasourceProfile,
        *,
        password: SecretStr | None = None,
    ) -> DatasourceProfileView:
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
        if password is _NOT_PROVIDED:
            next_password = None if identity_changed else existing.password
        else:
            next_password = password

        replaced = self._store.replace_datasource(profile)
        self._credentials.put_datasource(
            profile.id,
            DatasourceCredentials(
                password=cast(SecretStr | None, next_password)
            ),
        )
        return self._view(replaced)

    def delete(self, profile_id: str) -> None:
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
