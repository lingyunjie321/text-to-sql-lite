"""Process-local storage for model and datasource credentials."""

from __future__ import annotations

from dataclasses import dataclass, field
import threading

from pydantic import SecretStr


@dataclass(frozen=True, slots=True)
class ModelCredentials:
    generation_api_key: SecretStr | None = field(default=None, repr=False)
    embedding_api_key: SecretStr | None = field(default=None, repr=False)

    @property
    def is_empty(self) -> bool:
        return self.generation_api_key is None and self.embedding_api_key is None


@dataclass(frozen=True, slots=True)
class DatasourceCredentials:
    password: SecretStr | None = field(default=None, repr=False)

    @property
    def is_empty(self) -> bool:
        return self.password is None


class InMemoryCredentialStore:
    """Keep credentials only for the lifetime of the current process."""

    def __init__(self) -> None:
        self._model_credentials: dict[str, ModelCredentials] = {}
        self._datasource_credentials: dict[str, DatasourceCredentials] = {}
        self._lock = threading.RLock()

    def put_model(
        self,
        profile_id: str,
        credentials: ModelCredentials,
    ) -> None:
        with self._lock:
            if credentials.is_empty:
                self._model_credentials.pop(profile_id, None)
            else:
                self._model_credentials[profile_id] = credentials

    def get_model(self, profile_id: str) -> ModelCredentials | None:
        with self._lock:
            return self._model_credentials.get(profile_id)

    def has_model(self, profile_id: str) -> bool:
        with self._lock:
            return profile_id in self._model_credentials

    def discard_model(self, profile_id: str) -> None:
        with self._lock:
            self._model_credentials.pop(profile_id, None)

    def put_datasource(
        self,
        profile_id: str,
        credentials: DatasourceCredentials,
    ) -> None:
        with self._lock:
            if credentials.is_empty:
                self._datasource_credentials.pop(profile_id, None)
            else:
                self._datasource_credentials[profile_id] = credentials

    def get_datasource(self, profile_id: str) -> DatasourceCredentials | None:
        with self._lock:
            return self._datasource_credentials.get(profile_id)

    def has_datasource(self, profile_id: str) -> bool:
        with self._lock:
            return profile_id in self._datasource_credentials

    def discard_datasource(self, profile_id: str) -> None:
        with self._lock:
            self._datasource_credentials.pop(profile_id, None)

    def clear_all(self) -> None:
        with self._lock:
            self._model_credentials.clear()
            self._datasource_credentials.clear()
