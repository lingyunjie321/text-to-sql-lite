from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from app.config import (
    DatabaseSettings,
    load_database_settings,
    load_datasource_allowlist,
    load_datasources_from_file,
    load_embedding_settings,
    load_llm_route_settings,
)
from app.connectors.base import DatabaseConnector
from app.connectors.postgresql import PostgreSQLConnector
from app.connectors.mysql import MySQLConnector
from app.connectors.starrocks import StarRocksConnector
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
from app.generation import (
    OpenAICompatibleLLMProvider,
    build_configured_model_routing_runtime,
)
from app.observability import default_traced_runner
from app.schema_linking import (
    EmbeddingIndexRegistry,
    OpenAICompatibleEmbeddingProvider,
    RetrievalRuntime,
)
from app.workflow import (
    SQLTaskState,
    WorkflowContext,
    run_workflow,
)

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

    Constructor (keyword-only)::

        ApplicationServices(context=ctx)           # single datasource
        ApplicationServices(contexts={"a": ctx1})  # multi-datasource
    """

    __slots__ = ("contexts", "runner", "close")

    def __init__(
        self,
        *,
        context: WorkflowContext | None = None,
        contexts: dict[str, WorkflowContext] | None = None,
        runner: WorkflowRunner = run_workflow,
        close: Callable[[], None] | None = None,
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
    2. If extra_configs has this datasource with _extra → use those
    3. Fall back to env vars (TEXT_TO_SQL_ALLOWED_SCHEMAS/TABLES)
    """
    # Pagila: hardcoded security boundary
    if datasource_id == "pagila":
        return PAGILA_MVP_ALLOWED_SCHEMAS, PAGILA_MVP_ALLOWED_TABLES, "postgresql"

    # Extra configs from datasources.json
    if extra_configs:
        cfg = extra_configs.get(datasource_id)
        if cfg is not None:
            extra = getattr(cfg, "_extra", None)
            if extra and extra.get("allowed_schemas") and extra.get("allowed_tables"):
                return (
                    extra["allowed_schemas"],
                    extra["allowed_tables"],
                    cfg.type,
                )

    # Fallback: env-based allowlist
    try:
        schemas, tables = load_datasource_allowlist()
        if schemas and tables:
            return schemas, tables, (
                db_settings.type if db_settings else "mysql"
            )
    except Exception:
        pass

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
    """Create a raw connector based on database type."""
    db_type = db_settings.type

    if db_type == "postgresql":
        return PostgreSQLConnector(db_settings)
    elif db_type == "mysql":
        return MySQLConnector(
            host=db_settings.host,
            port=db_settings.port,
            user=db_settings.username,
            password=(
                db_settings.password_value
                if db_settings.password_value
                else ""
            ),
            database=db_settings.database,
            min_pool_size=db_settings.min_pool_size,
            max_pool_size=db_settings.max_pool_size,
            pool_timeout_seconds=db_settings.pool_timeout_seconds,
            statement_timeout_seconds=db_settings.statement_timeout_seconds,
            max_result_rows=db_settings.max_result_rows,
            connection_retry_count=db_settings.connection_retry_count,
        )
    elif db_type == "starrocks":
        return StarRocksConnector(
            host=db_settings.host,
            port=db_settings.port,
            user=db_settings.username,
            password=(
                db_settings.password_value
                if db_settings.password_value
                else ""
            ),
            database=db_settings.database,
            min_pool_size=db_settings.min_pool_size,
            max_pool_size=db_settings.max_pool_size,
            pool_timeout_seconds=db_settings.pool_timeout_seconds,
            statement_timeout_seconds=db_settings.statement_timeout_seconds,
            max_result_rows=db_settings.max_result_rows,
            connection_retry_count=db_settings.connection_retry_count,
        )
    else:
        raise ValueError(f"Unsupported database type: {db_type!r}")


# ── Context builder ──────────────────────────────────────────────


def _setup_pagila_connector(
    raw_connector: DatabaseConnector,
    *,
    datasource_id: str,
    allowed_schemas: tuple[str, ...],
    allowed_tables: tuple[str, ...],
) -> tuple[WorkflowContext, str]:
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


def build_production_services() -> ApplicationServices:
    """Bootstrap all configured datasources into an ApplicationServices.

    Loads the primary datasource from env vars (TEXT_TO_SQL_DATABASE_*),
    optionally loads extra datasources from ``datasources.json``, and
    builds a WorkflowContext for each.
    """
    registry = ConnectorRegistry()
    contexts: dict[str, WorkflowContext] = {}

    # ── Phase 1: Load & connect to all datasources ─────────────
    # Pagila manifest is validated here (before LLM credentials).
    pending: list[
        tuple[
            str,  # datasource_id
            object,  # connector (raw or FrozenSemanticConnector)
            tuple[str, ...],  # allowed_schemas
            tuple[str, ...],  # allowed_tables
            str,  # semantic_version
        ]
    ] = []

    try:
        primary_settings = load_database_settings()
        primary_ds_id = primary_settings.datasource_id

        allowed_schemas, allowed_tables, _ = _get_datasource_allowed_config(
            primary_ds_id, db_settings=primary_settings
        )
        raw_conn = _create_raw_connector(primary_settings)
        raw_conn.open()
        registry.register(primary_ds_id, raw_conn)

        if primary_ds_id == "pagila":
            wrapped_conn, sem_ver = _setup_pagila_connector(
                raw_conn,
                datasource_id=primary_ds_id,
                allowed_schemas=allowed_schemas,
                allowed_tables=allowed_tables,
            )
            pending.append(
                (primary_ds_id, wrapped_conn, allowed_schemas, allowed_tables, sem_ver)
            )
        else:
            pending.append(
                (primary_ds_id, raw_conn, allowed_schemas, allowed_tables, "0.0.0")
            )
    except Exception:
        registry.close_all()
        raise

    # Extra datasources from datasources.json (optional)
    extra_configs: dict[str, DatabaseSettings] = {}
    try:
        extra_configs = load_datasources_from_file(_DEFAULT_DATASOURCES_JSON)
    except Exception:
        pass

    registered_ids = {item[0] for item in pending}
    for ds_id, ds_settings in extra_configs.items():
        if ds_id in registered_ids:
            continue
        try:
            allowed_schemas, allowed_tables, _ = _get_datasource_allowed_config(
                ds_id, db_settings=ds_settings, extra_configs=extra_configs
            )
            raw_conn = _create_raw_connector(ds_settings)
            raw_conn.open()
            registry.register(ds_id, raw_conn)

            if ds_id == "pagila":
                wrapped_conn, sem_ver = _setup_pagila_connector(
                    raw_conn,
                    datasource_id=ds_id,
                    allowed_schemas=allowed_schemas,
                    allowed_tables=allowed_tables,
                )
                pending.append(
                    (ds_id, wrapped_conn, allowed_schemas, allowed_tables, sem_ver)
                )
            else:
                pending.append(
                    (ds_id, raw_conn, allowed_schemas, allowed_tables, "0.0.0")
                )
        except Exception:
            registry.close_all()
            raise

    # ── Phase 2: Shared infrastructure (LLM / Embedding) ───────
    llm_route_settings = load_llm_route_settings()
    declared_llm_settings = {
        "simple": llm_route_settings.simple,
        "standard": llm_route_settings.standard,
        "complex": llm_route_settings.complex,
    }
    if llm_route_settings.fallback is not None:
        declared_llm_settings["fallback"] = llm_route_settings.fallback
    providers = {
        key: OpenAICompatibleLLMProvider(settings)
        for key, settings in declared_llm_settings.items()
    }
    model_routing = build_configured_model_routing_runtime(
        settings=llm_route_settings,
        providers=providers,
    )
    embedding_provider = OpenAICompatibleEmbeddingProvider(
        load_embedding_settings()
    )

    # ── Phase 3: Build contexts for all datasources ────────────
    for ds_id, connector, allowed_schemas, allowed_tables, sem_ver in pending:
        try:
            contexts[ds_id] = WorkflowContext(
                connector=connector,
                model_routing=model_routing,
                datasource_id=ds_id,
                allowed_schemas=allowed_schemas,
                allowed_tables=allowed_tables,
                retrieval_runtime=RetrievalRuntime(
                    provider=embedding_provider,
                    registry=EmbeddingIndexRegistry(),
                    semantic_version=sem_ver,
                ),
            )
        except Exception:
            registry.close_all()
            raise

    return ApplicationServices(
        contexts=contexts,
        runner=default_traced_runner(),
        close=registry.close_all,
    )
