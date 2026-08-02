"""Resolve stored Profile IDs to already-created static workflow runtimes."""

from __future__ import annotations

from urllib.parse import unquote, urlsplit

from pydantic import ValidationError

from app.config import DatabaseSettings, LLMRouteSettings
from app.local.datasource_service import (
    DatasourceProfileNotFoundError,
    DatasourceProfileService,
)
from app.local.model_service import (
    ModelProfileNotFoundError,
    ModelProfileService,
)
from app.local.profile_models import DatasourceProfile, ModelProfile
from app.local.profile_store import ProfileStoreError
from app.workflow import WorkflowContext


class ProfileResolutionError(RuntimeError):
    """Public-safe Profile selection failure raised before workflow entry."""

    def __init__(self, *, code: str, status_code: int, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code
        self.message = message


class StaticProfileResolver:
    """Bind Profile IDs only to runtimes created during application startup."""

    def __init__(
        self,
        *,
        model_profiles: ModelProfileService,
        datasource_profiles: DatasourceProfileService,
        contexts: dict[str, WorkflowContext],
        active_model: ModelProfile | None,
        active_datasources: dict[str, DatasourceProfile],
    ) -> None:
        self._model_profiles = model_profiles
        self._datasource_profiles = datasource_profiles
        self._contexts = contexts
        self._active_model = active_model
        self._active_datasources = active_datasources

    def resolve(
        self,
        *,
        datasource_profile_id: str,
        model_profile_id: str,
    ) -> WorkflowContext:
        try:
            datasource = self._datasource_profiles.get(
                datasource_profile_id
            ).profile
        except DatasourceProfileNotFoundError:
            raise ProfileResolutionError(
                code="DATASOURCE_PROFILE_NOT_FOUND",
                status_code=404,
                message="The datasource profile was not found.",
            ) from None
        except ProfileStoreError:
            raise _store_unavailable_error() from None

        try:
            model = self._model_profiles.get(model_profile_id).profile
        except ModelProfileNotFoundError:
            raise ProfileResolutionError(
                code="MODEL_PROFILE_NOT_FOUND",
                status_code=404,
                message="The model profile was not found.",
            ) from None
        except ProfileStoreError:
            raise _store_unavailable_error() from None

        context = self._contexts.get(datasource_profile_id)
        active_datasource = self._active_datasources.get(
            datasource_profile_id
        )
        if (
            context is None
            or active_datasource is None
            or context.datasource_id != datasource_profile_id
            or _datasource_identity(datasource)
            != _datasource_identity(active_datasource)
            or self._active_model is None
            or _model_identity(model) != _model_identity(self._active_model)
        ):
            raise ProfileResolutionError(
                code="PROFILE_RUNTIME_UNAVAILABLE",
                status_code=409,
                message="The selected profiles are not active.",
            )
        return context


def build_static_datasource_profile(
    settings: DatabaseSettings,
    *,
    allowed_schemas: tuple[str, ...],
    allowed_tables: tuple[str, ...],
) -> DatasourceProfile | None:
    """Build a non-sensitive identity for an existing static datasource."""

    try:
        if settings.type == "postgresql":
            dsn = settings.dsn_value
            if dsn is None:
                return None
            parsed = urlsplit(dsn)
            host = parsed.hostname
            username = parsed.username
            database = unquote(parsed.path.lstrip("/"))
            if host is None or username is None or not database:
                return None
            port = parsed.port or 5432
            decoded_username = unquote(username)
        elif settings.type == "mysql":
            host = settings.host
            port = settings.port
            database = settings.database
            decoded_username = settings.username
        else:
            return None
        return DatasourceProfile(
            id=settings.datasource_id,
            name=settings.datasource_id,
            database_type=settings.type,
            host=host,
            port=port,
            database=database,
            username=decoded_username,
            allowed_schemas=allowed_schemas,
            allowed_tables=allowed_tables,
        )
    except (TypeError, ValueError, ValidationError):
        return None


def build_static_model_profile(
    settings: LLMRouteSettings,
) -> ModelProfile | None:
    """Return one model identity only when every primary route uses it."""

    if not isinstance(settings, LLMRouteSettings):
        return None
    identities = {
        (str(route.base_url), route.model)
        for route in (settings.simple, settings.standard, settings.complex)
    }
    if len(identities) != 1:
        return None
    base_url, model_name = identities.pop()
    try:
        return ModelProfile(
            id="environment-model",
            name="Environment model",
            provider_type="openai_compatible",
            base_url=base_url,
            model_name=model_name,
        )
    except ValidationError:
        return None


def _datasource_identity(profile: DatasourceProfile) -> tuple[object, ...]:
    return (
        profile.database_type,
        profile.host.casefold(),
        profile.port,
        profile.database,
        profile.username,
        profile.allowed_schemas,
        profile.allowed_tables,
    )


def _model_identity(profile: ModelProfile) -> tuple[str, str, str]:
    return (
        profile.provider_type,
        str(profile.base_url),
        profile.model_name,
    )


def _store_unavailable_error() -> ProfileResolutionError:
    return ProfileResolutionError(
        code="PROFILE_STORE_UNAVAILABLE",
        status_code=503,
        message="Profile storage is unavailable.",
    )
