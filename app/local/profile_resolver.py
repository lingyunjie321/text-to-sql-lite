"""Resolve stored Profile IDs to already-created static workflow runtimes."""

from __future__ import annotations

from urllib.parse import unquote, urlsplit

from pydantic import ValidationError

from app.config import DatabaseSettings, LLMRouteSettings
from app.local.datasource_service import (
    DatasourceProfileNotFoundError,
    DatasourceProfileService,
)
from app.local.datasource_runtime import DatasourceRuntimeError
from app.local.model_service import (
    ModelProfileNotFoundError,
    ModelProfileService,
)
from app.local.model_runtime import ModelRuntimeError
from app.local.model_runtime_registry import ModelRuntimeRegistry
from app.local.profile_models import DatasourceProfile, ModelProfile
from app.local.profile_store import ProfileStoreError
from app.local.runtime_registry import RuntimeRegistry
from app.workflow import WorkflowContext


class _ContextFactory:
    def create(self, **kwargs: object) -> WorkflowContext:
        raise NotImplementedError


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
        runtime_registry: RuntimeRegistry | None = None,
        model_runtime_registry: ModelRuntimeRegistry | None = None,
        context_factory: _ContextFactory | None = None,
    ) -> None:
        self._model_profiles = model_profiles
        self._datasource_profiles = datasource_profiles
        self._contexts = contexts
        self._active_model = active_model
        self._active_datasources = active_datasources
        self._runtime_registry = runtime_registry
        self._model_runtime_registry = model_runtime_registry
        self._context_factory = context_factory

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

        if self._model_runtime_registry is not None:
            return self._resolve_dynamic_model_context(
                datasource=datasource,
                model=model,
            )

        context = self._contexts.get(datasource_profile_id)
        active_datasource = self._active_datasources.get(
            datasource_profile_id
        )
        if (
            self._active_model is None
            or _model_identity(model) != _model_identity(self._active_model)
        ):
            raise ProfileResolutionError(
                code="PROFILE_RUNTIME_UNAVAILABLE",
                status_code=409,
                message="The selected profiles are not active.",
            )
        if (
            context is not None
            and active_datasource is not None
            and context.datasource_id == datasource_profile_id
            and _datasource_identity(datasource)
            == _datasource_identity(active_datasource)
        ):
            return context
        if self._runtime_registry is None:
            raise ProfileResolutionError(
                code="PROFILE_RUNTIME_UNAVAILABLE",
                status_code=409,
                message="The selected profiles are not active.",
            )
        try:
            return self._runtime_registry.get_or_create(datasource).context
        except DatasourceRuntimeError as error:
            raise ProfileResolutionError(
                code=error.code,
                status_code=error.status_code,
                message=error.public_message,
            ) from None
        except Exception:
            raise ProfileResolutionError(
                code="DATASOURCE_RUNTIME_UNAVAILABLE",
                status_code=503,
                message="The datasource runtime is unavailable.",
            ) from None

    def _resolve_dynamic_model_context(
        self,
        *,
        datasource: DatasourceProfile,
        model: ModelProfile,
    ) -> WorkflowContext:
        if self._context_factory is None:
            raise ProfileResolutionError(
                code="MODEL_RUNTIME_UNAVAILABLE",
                status_code=503,
                message="The model runtime is unavailable.",
            )
        assert self._model_runtime_registry is not None
        try:
            model_runtime = self._model_runtime_registry.get_or_create(model)
        except ModelRuntimeError as error:
            raise ProfileResolutionError(
                code=error.code,
                status_code=error.status_code,
                message=error.public_message,
            ) from None
        except Exception:
            raise ProfileResolutionError(
                code="MODEL_RUNTIME_UNAVAILABLE",
                status_code=503,
                message="The model runtime is unavailable.",
            ) from None

        base_context = self._matching_static_context(datasource)
        semantic_version = "0.0.0"
        if base_context is None:
            if self._runtime_registry is None:
                raise ProfileResolutionError(
                    code="PROFILE_RUNTIME_UNAVAILABLE",
                    status_code=409,
                    message="The selected profiles are not active.",
                )
            try:
                datasource_runtime = self._runtime_registry.get_or_create(
                    datasource
                )
            except DatasourceRuntimeError as error:
                raise ProfileResolutionError(
                    code=error.code,
                    status_code=error.status_code,
                    message=error.public_message,
                ) from None
            except Exception:
                raise ProfileResolutionError(
                    code="DATASOURCE_RUNTIME_UNAVAILABLE",
                    status_code=503,
                    message="The datasource runtime is unavailable.",
                ) from None
            runtime_context = datasource_runtime.context
            workflow_connector = datasource_runtime.workflow_connector
            if workflow_connector is None and runtime_context is not None:
                workflow_connector = runtime_context.connector
            if workflow_connector is None:
                raise ProfileResolutionError(
                    code="DATASOURCE_RUNTIME_UNAVAILABLE",
                    status_code=503,
                    message="The datasource runtime is unavailable.",
                )
            base_context = runtime_context
            semantic_version = datasource_runtime.semantic_version
        else:
            workflow_connector = base_context.connector
        if (
            base_context is not None
            and base_context.retrieval_runtime is not None
        ):
            semantic_version = (
                base_context.retrieval_runtime.semantic_version
            )

        try:
            return self._context_factory.create(
                connector=workflow_connector,
                model_routing=model_runtime.model_routing,
                datasource_id=datasource.id,
                allowed_schemas=datasource.allowed_schemas,
                allowed_tables=datasource.allowed_tables,
                embedding_provider=model_runtime.embedding_provider,
                embedding_registry=(
                    model_runtime.embedding_registry
                    if model_runtime.embedding_provider is not None
                    else None
                ),
                semantic_version=semantic_version,
            )
        except Exception:
            raise ProfileResolutionError(
                code="MODEL_RUNTIME_UNAVAILABLE",
                status_code=503,
                message="The model runtime is unavailable.",
            ) from None

    def _matching_static_context(
        self,
        datasource: DatasourceProfile,
    ) -> WorkflowContext | None:
        context = self._contexts.get(datasource.id)
        active_datasource = self._active_datasources.get(datasource.id)
        if (
            context is not None
            and active_datasource is not None
            and context.datasource_id == datasource.id
            and _datasource_identity(datasource)
            == _datasource_identity(active_datasource)
        ):
            return context
        return None


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
