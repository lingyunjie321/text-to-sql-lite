"""Model profile CRUD and in-memory credential coordination."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, cast

from pydantic import SecretStr

from app.local.credential_store import (
    InMemoryCredentialStore,
    ModelCredentials,
)
from app.local.profile_models import ModelProfile
from app.local.profile_store import LocalProfileStore

_NOT_PROVIDED = object()


class ModelProfileNotFoundError(RuntimeError):
    code = "MODEL_PROFILE_NOT_FOUND"

    def __init__(self) -> None:
        super().__init__("model profile was not found")


@dataclass(frozen=True, slots=True)
class ModelProfileView:
    profile: ModelProfile
    generation_credential_status: Literal["configured", "missing"]
    embedding_credential_status: Literal[
        "configured",
        "missing",
        "not_applicable",
    ]


class ModelProfileService:
    """Coordinate non-sensitive model profiles and process-local keys."""

    def __init__(
        self,
        store: LocalProfileStore,
        credentials: InMemoryCredentialStore,
    ) -> None:
        self._store = store
        self._credentials = credentials

    def create(
        self,
        profile: ModelProfile,
        *,
        generation_api_key: SecretStr | None = None,
        embedding_api_key: SecretStr | None = None,
    ) -> ModelProfileView:
        created = self._store.create_model(profile)
        self._credentials.put_model(
            profile.id,
            ModelCredentials(
                generation_api_key=generation_api_key,
                embedding_api_key=(
                    embedding_api_key
                    if profile.embedding_base_url is not None
                    else None
                ),
            ),
        )
        return self._view(created)

    def get(self, profile_id: str) -> ModelProfileView:
        profile = self._store.get_model(profile_id)
        if profile is None:
            raise ModelProfileNotFoundError()
        return self._view(profile)

    def list(self) -> tuple[ModelProfileView, ...]:
        return tuple(self._view(profile) for profile in self._store.list_models())

    def replace(
        self,
        profile: ModelProfile,
        *,
        generation_api_key: SecretStr | None | object = _NOT_PROVIDED,
        embedding_api_key: SecretStr | None | object = _NOT_PROVIDED,
    ) -> ModelProfileView:
        current = self._store.get_model(profile.id)
        if current is None:
            raise ModelProfileNotFoundError()
        existing = self._credentials.get_model(profile.id) or ModelCredentials()

        generation_identity_changed = (
            current.provider_type != profile.provider_type
            or current.base_url != profile.base_url
        )
        if generation_api_key is _NOT_PROVIDED:
            next_generation_key = (
                None
                if generation_identity_changed
                else existing.generation_api_key
            )
        else:
            next_generation_key = generation_api_key

        embedding_identity_changed = (
            current.embedding_base_url != profile.embedding_base_url
            or current.embedding_model != profile.embedding_model
        )
        if profile.embedding_base_url is None:
            next_embedding_key = None
        elif embedding_api_key is _NOT_PROVIDED:
            next_embedding_key = (
                None
                if embedding_identity_changed
                else existing.embedding_api_key
            )
        else:
            next_embedding_key = embedding_api_key

        replaced = self._store.replace_model(profile)
        self._credentials.put_model(
            profile.id,
            ModelCredentials(
                generation_api_key=cast(
                    SecretStr | None,
                    next_generation_key,
                ),
                embedding_api_key=cast(
                    SecretStr | None,
                    next_embedding_key,
                ),
            ),
        )
        return self._view(replaced)

    def delete(self, profile_id: str) -> None:
        if not self._store.delete_model(profile_id):
            raise ModelProfileNotFoundError()
        self._credentials.discard_model(profile_id)

    def _view(self, profile: ModelProfile) -> ModelProfileView:
        credentials = self._credentials.get_model(profile.id)
        generation_status: Literal["configured", "missing"] = (
            "configured"
            if credentials is not None
            and credentials.generation_api_key is not None
            else "missing"
        )
        if profile.embedding_base_url is None:
            embedding_status: Literal[
                "configured", "missing", "not_applicable"
            ] = "not_applicable"
        elif (
            credentials is not None
            and credentials.embedding_api_key is not None
        ):
            embedding_status = "configured"
        else:
            embedding_status = "missing"
        return ModelProfileView(
            profile=profile,
            generation_credential_status=generation_status,
            embedding_credential_status=embedding_status,
        )
