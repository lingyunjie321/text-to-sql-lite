from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import logging
from pathlib import Path
from typing import Literal, Protocol

from app.config import (
    DatabaseSettings,
    load_database_settings,
    load_datasource_allowlist,
    load_datasources_from_file,
    load_embedding_settings,
    load_llm_route_settings,
)
from app.connectors.base import DatabaseConnector
from app.connectors.errors import DatabaseConnectorError
from app.connectors.factory import ConnectorFactory
from app.connectors.registry import ConnectorRegistry
from app.connectors.view_semantics import (
    FrozenSemanticConnector,
    load_view_semantic_manifest,
)
from app.connectors.view_semantics_lock import (
    PAGILA_DATABASE_SCHEMA_SHA256,
    VIEW_SEMANTIC_MANIFEST_PATH,
    VIEW_SEMANTIC_MANIFEST_SHA256,
)
from app.generation.factory import ModelProviderFactory
from app.local.credential_store import InMemoryCredentialStore
from app.local.datasource_service import DatasourceProfileService
from app.local.model_service import ModelProfileService
from app.local.profile_models import DatasourceProfile
from app.local.profile_resolver import (
    StaticProfileResolver,
    build_static_datasource_profile,
    build_static_model_profile,
)
from app.local.profile_store import LocalProfileStore
from app.observability import default_traced_runner
from app.schema_linking import OpenAICompatibleEmbeddingProvider
from app.workflow import (
    SQLTaskState,
    WorkflowContext,
    run_workflow,
)
from app.api.context_factory import WorkflowContextFactory

PAGILA_MVP_ALLOWED_SCHEMAS = ("public",)
PAGILA_MVP_ALLOWED_TABLES = (
    "public.actor",
    "public.address",
    "public.category",
    "public.city",
    "public.country",
    "public.customer",
    "public.film",
    "public.film_actor",
    "public.film_category",
    "public.inventory",
    "public.language",
    "public.payment",
    "public.rental",
)

_DEFAULT_DATASOURCES_JSON = Path("datasources.json")
logger = logging.getLogger(__name__)

BootstrapStage = Literal[
    "profiles",
    "configuration",
    "connector",
    "model",
    "embedding",
    "context",
    "runner",
    "services",
]


class ApplicationBootstrapError(RuntimeError):
    """Public-safe error returned when generic startup work fails."""

    code = "APP_BOOTSTRAP_FAILED"
    public_message = "Application startup failed."

    def __init__(self, stage: BootstrapStage) -> None:
        super().__init__(self.public_message)
        self.stage = stage


class WorkflowRunner(Protocol):
    def __call__(
        self,
        state: SQLTaskState,
        *,
        context: WorkflowContext,
    ) -> SQLTaskState: ...


class ApplicationServices:
    """Application-level service container supporting multiple datasources.

    ``contexts`` maps datasource_id -> WorkflowContext.  For backward
    compatibility, the ``context`` keyword maps to a single-entry dict
    keyed by ``"default"``.

    ``llm_route_settings`` 保存原始路由配置，供请求级 model_overrides
    覆盖重建使用（可选；测试中可省略）。

    Constructor (keyword-only)::

        ApplicationServices(context=ctx)           # single datasource
        ApplicationServices(contexts={"a": ctx1})  # multi-datasource
    """

    __slots__ = (
        "contexts",
        "runner",
        "close",
        "llm_route_settings",
        "model_profiles",
        "datasource_profiles",
        "credential_store",
        "profile_resolver",
    )

    def __init__(
        self,
        *,
        context: WorkflowContext | None = None,
        contexts: dict[str, WorkflowContext] | None = None,
        runner: WorkflowRunner = run_workflow,
        close: Callable[[], None] | None = None,
        llm_route_settings: object | None = None,
        model_profiles: ModelProfileService | None = None,
        datasource_profiles: DatasourceProfileService | None = None,
        credential_store: InMemoryCredentialStore | None = None,
        profile_resolver: StaticProfileResolver | None = None,
    ) -> None:
        if context is None and contexts is None:
            raise ValueError("either 'context' or 'contexts' is required")
        if context is not None and contexts is not None:
            raise ValueError("cannot specify both 'context' and 'contexts'")

        resolved: dict[str, WorkflowContext] = (
            contexts if contexts is not None else {"default": context}  # type: ignore[dict-item]
        )
        if (
            not isinstance(resolved, dict)
            or not resolved
            or not all(
                isinstance(ctx, WorkflowContext) for ctx in resolved.values()
            )
            or not callable(runner)
            or (close is not None and not callable(close))
        ):
            raise ValueError("application services are invalid")

        object.__setattr__(self, "contexts", resolved)
        object.__setattr__(self, "runner", runner)
        object.__setattr__(self, "close", close)
        object.__setattr__(self, "llm_route_settings", llm_route_settings)
        object.__setattr__(self, "model_profiles", model_profiles)
        object.__setattr__(self, "datasource_profiles", datasource_profiles)
        object.__setattr__(self, "credential_store", credential_store)
        object.__setattr__(self, "profile_resolver", profile_resolver)

    @property
    def context(self) -> WorkflowContext:
        """Primary context (backward-compatible shortcut)."""
        if not self.contexts:
            raise RuntimeError("no datasource contexts registered")
        return next(iter(self.contexts.values()))

    def context_for(self, datasource_id: str) -> WorkflowContext:
        """Retrieve the WorkflowContext for *datasource_id*.

        Falls back to the ``"default"`` context when *datasource_id* is
        not found (backward compatibility for single-datasource setups).

        Raises ValueError if no context matches.
        """
        ctx = self.contexts.get(datasource_id)
        if ctx is not None:
            return ctx
        # Fallback: single-context backward compat
        ctx = self.contexts.get("default")
        if ctx is not None:
            return ctx
        raise ValueError(
            f"Unknown datasource: {datasource_id!r}"
        )


@dataclass(frozen=True, slots=True)
class RequestIdentity:
    subject: str
    can_debug: bool = False

    def __post_init__(self) -> None:
        if (
            not isinstance(self.subject, str)
            or not self.subject.strip()
            or type(self.can_debug) is not bool
        ):
            raise ValueError("request identity is invalid")


def default_request_identity() -> RequestIdentity:
    return RequestIdentity(
        subject="mvp-fixed-user",
        can_debug=False,
    )


# ── Datasource allowlist resolution ──────────────────────────────


def _get_datasource_allowed_config(
    datasource_id: str,
    db_settings: DatabaseSettings | None = None,
    extra_configs: dict[str, DatabaseSettings] | None = None,
) -> tuple[tuple[str, ...], tuple[str, ...], str]:
    """Return (allowed_schemas, allowed_tables, dialect) for a datasource.

    Resolution order:
    1. If datasource_id == "pagila" → hardcoded Pagila allowlist
    2. If extra_configs has this datasource with an explicit allowlist → use it
    3. Fall back to env vars (TEXT_TO_SQL_ALLOWED_SCHEMAS/TABLES)
    """
    # Pagila: hardcoded security boundary
    if datasource_id == "pagila":
        return PAGILA_MVP_ALLOWED_SCHEMAS, PAGILA_MVP_ALLOWED_TABLES, "postgresql"

    # Extra configs from datasources.json
    if extra_configs:
        cfg = extra_configs.get(datasource_id)
        if cfg is not None:
            if cfg.allowed_schemas and cfg.allowed_tables:
                return (
                    cfg.allowed_schemas,
                    cfg.allowed_tables,
                    cfg.type,
                )

    # Fallback: env-based allowlist
    schemas, tables = load_datasource_allowlist()
    if schemas and tables:
        return schemas, tables, (
            db_settings.type if db_settings else "mysql"
        )

    raise ValueError(
        f"Datasource '{datasource_id}' has no configured allowlist. "
        "For non-Pagila datasources, configure via datasources.json with "
        "'allowed_schemas' and 'allowed_tables' fields, or set "
        "TEXT_TO_SQL_ALLOWED_SCHEMAS / TEXT_TO_SQL_ALLOWED_TABLES env vars."
    )


# ── Connector factory ────────────────────────────────────────────


def _create_raw_connector(
    db_settings: DatabaseSettings,
) -> DatabaseConnector:
    """Backward-compatible wrapper for the explicit connector factory."""
    return ConnectorFactory().create(db_settings)


# ── Context builder ──────────────────────────────────────────────


def _setup_pagila_connector(
    raw_connector: DatabaseConnector,
    *,
    datasource_id: str,
    allowed_schemas: tuple[str, ...],
    allowed_tables: tuple[str, ...],
) -> tuple[DatabaseConnector, str]:
    """Wrap a raw connector in FrozenSemanticConnector for Pagila.

    Returns (connector, semantic_version).  This reads metadata and loads
    the locked Pagila manifest — must be called early so manifest drift is
    detected before LLM credentials are loaded.
    """
    snapshot = raw_connector.read_metadata(allowed_schemas, allowed_tables)
    manifest = load_view_semantic_manifest(
        VIEW_SEMANTIC_MANIFEST_PATH,
        expected_sha256=VIEW_SEMANTIC_MANIFEST_SHA256,
        snapshot=snapshot,
        datasource_id=datasource_id,
        database_schema_sha256=PAGILA_DATABASE_SCHEMA_SHA256,
        allowed_schemas=allowed_schemas,
        allowed_tables=allowed_tables,
    )
    wrapped = FrozenSemanticConnector(raw_connector, manifest)
    return wrapped, manifest.enriched_schema_version


# ── Production bootstrap ─────────────────────────────────────────


class ApplicationBootstrap:
    """Coordinate configuration, connection, model and context startup."""

    def __init__(self) -> None:
        self._connector_factory = ConnectorFactory()
        self._model_factory = ModelProviderFactory()
        self._context_factory = WorkflowContextFactory()

    def build(self) -> ApplicationServices:
        registry = ConnectorRegistry()
        credential_store = InMemoryCredentialStore()
        owned_connectors: list[tuple[str, DatabaseConnector]] = []
        pending: list[
            tuple[
                str,
                DatabaseConnector,
                tuple[str, ...],
                tuple[str, ...],
                str,
            ]
        ] = []
        active_datasource_profiles: dict[str, DatasourceProfile] = {}
        stage: BootstrapStage = "configuration"
        try:
            stage = "profiles"
            profile_store = LocalProfileStore()
            model_profiles = ModelProfileService(
                profile_store,
                credential_store,
            )
            datasource_profiles = DatasourceProfileService(
                profile_store,
                credential_store,
            )
            stage = "configuration"
            primary_settings = load_database_settings()
            extra_configs = load_datasources_from_file(
                _DEFAULT_DATASOURCES_JSON
            )
            configured_datasources = [
                (primary_settings.datasource_id, primary_settings),
                *extra_configs.items(),
            ]
            configured_ids: set[str] = set()
            for datasource_id, settings in configured_datasources:
                stage = "configuration"
                if datasource_id in configured_ids:
                    raise ValueError("duplicate datasource_id is configured")
                configured_ids.add(datasource_id)
                allowed_schemas, allowed_tables, _ = (
                    _get_datasource_allowed_config(
                        datasource_id,
                        db_settings=settings,
                        extra_configs=extra_configs,
                    )
                )
                static_profile = build_static_datasource_profile(
                    settings,
                    allowed_schemas=allowed_schemas,
                    allowed_tables=allowed_tables,
                )
                if static_profile is not None:
                    active_datasource_profiles[datasource_id] = static_profile
                stage = "connector"
                raw_connector = self._connector_factory.create(settings)
                owned_connectors.append((datasource_id, raw_connector))
                registry.register(datasource_id, raw_connector)
                raw_connector.open()
                if datasource_id == "pagila":
                    connector, semantic_version = _setup_pagila_connector(
                        raw_connector,
                        datasource_id=datasource_id,
                        allowed_schemas=allowed_schemas,
                        allowed_tables=allowed_tables,
                    )
                else:
                    connector = raw_connector
                    semantic_version = "0.0.0"
                pending.append(
                    (
                        datasource_id,
                        connector,
                        allowed_schemas,
                        allowed_tables,
                        semantic_version,
                    )
                )

            stage = "model"
            llm_route_settings = load_llm_route_settings()
            active_model_profile = build_static_model_profile(
                llm_route_settings
            )
            model_routing = self._model_factory.create(llm_route_settings)
            stage = "embedding"
            embedding_provider = OpenAICompatibleEmbeddingProvider(
                load_embedding_settings()
            )
            stage = "context"
            contexts = {
                datasource_id: self._context_factory.create(
                    connector=connector,
                    model_routing=model_routing,
                    datasource_id=datasource_id,
                    allowed_schemas=allowed_schemas,
                    allowed_tables=allowed_tables,
                    embedding_provider=embedding_provider,
                    semantic_version=semantic_version,
                )
                for (
                    datasource_id,
                    connector,
                    allowed_schemas,
                    allowed_tables,
                    semantic_version,
                ) in pending
            }
            stage = "runner"
            runner = default_traced_runner()
            stage = "services"
            profile_resolver = StaticProfileResolver(
                model_profiles=model_profiles,
                datasource_profiles=datasource_profiles,
                contexts=contexts,
                active_model=active_model_profile,
                active_datasources=active_datasource_profiles,
            )
            services = ApplicationServices(
                contexts=contexts,
                runner=runner,
                close=lambda: _close_application_resources(
                    registry,
                    credential_store,
                ),
                llm_route_settings=llm_route_settings,
                model_profiles=model_profiles,
                datasource_profiles=datasource_profiles,
                credential_store=credential_store,
                profile_resolver=profile_resolver,
            )
        except DatabaseConnectorError:
            _close_connectors(owned_connectors)
            credential_store.clear_all()
            raise
        except Exception:
            _close_connectors(owned_connectors)
            credential_store.clear_all()
            raise ApplicationBootstrapError(stage) from None
        except BaseException:
            _close_connectors(owned_connectors)
            credential_store.clear_all()
            raise
        return services


def _close_connectors(
    connectors: list[tuple[str, DatabaseConnector]],
) -> None:
    """Best-effort cleanup that never replaces the startup failure."""
    for datasource_id, connector in reversed(connectors):
        try:
            connector.close()
        except Exception:
            logger.warning(
                "bootstrap_connector_close_failed",
                extra={"datasource_id": datasource_id},
            )


def _close_application_resources(
    registry: ConnectorRegistry,
    credential_store: InMemoryCredentialStore,
) -> None:
    try:
        registry.close_all()
    finally:
        credential_store.clear_all()


def build_production_services() -> ApplicationServices:
    """Build configured production services with explicit ownership."""
    return ApplicationBootstrap().build()
