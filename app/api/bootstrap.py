from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol

from app.config import (
    load_database_settings,
    load_llm_settings,
)
from app.connectors.postgresql import PostgreSQLConnector
from app.connectors.view_semantics import (
    FrozenSemanticConnector,
    load_view_semantic_manifest,
)
from app.connectors.view_semantics_lock import (
    PAGILA_DATABASE_SCHEMA_SHA256,
    VIEW_SEMANTIC_MANIFEST_PATH,
    VIEW_SEMANTIC_MANIFEST_SHA256,
)
from app.generation import OpenAICompatibleLLMProvider
from app.observability import default_traced_runner
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


class WorkflowRunner(Protocol):
    def __call__(
        self,
        state: SQLTaskState,
        *,
        context: WorkflowContext,
    ) -> SQLTaskState: ...


@dataclass(frozen=True, slots=True)
class ApplicationServices:
    context: WorkflowContext
    runner: WorkflowRunner = field(
        default=run_workflow,
        repr=False,
    )
    close: Callable[[], None] | None = field(
        default=None,
        repr=False,
    )

    def __post_init__(self) -> None:
        if (
            not isinstance(self.context, WorkflowContext)
            or not callable(self.runner)
            or (
                self.close is not None
                and not callable(self.close)
            )
        ):
            raise ValueError("application services are invalid")


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


def build_production_services() -> ApplicationServices:
    database_settings = load_database_settings()
    if database_settings.datasource_id != "pagila":
        raise ValueError(
            "production datasource must be pagila"
        )
    connector = PostgreSQLConnector(database_settings)
    connector.open()
    try:
        snapshot = connector.read_metadata(
            PAGILA_MVP_ALLOWED_SCHEMAS,
            PAGILA_MVP_ALLOWED_TABLES,
        )
        manifest = load_view_semantic_manifest(
            VIEW_SEMANTIC_MANIFEST_PATH,
            expected_sha256=VIEW_SEMANTIC_MANIFEST_SHA256,
            snapshot=snapshot,
            datasource_id=database_settings.datasource_id,
            database_schema_sha256=(
                PAGILA_DATABASE_SCHEMA_SHA256
            ),
            allowed_schemas=PAGILA_MVP_ALLOWED_SCHEMAS,
            allowed_tables=PAGILA_MVP_ALLOWED_TABLES,
        )
        semantic_connector = FrozenSemanticConnector(
            connector,
            manifest,
        )
        llm_settings = load_llm_settings()
        provider = OpenAICompatibleLLMProvider(llm_settings)
        context = WorkflowContext(
            provider=provider,
            connector=semantic_connector,
            datasource_id=database_settings.datasource_id,
            allowed_schemas=PAGILA_MVP_ALLOWED_SCHEMAS,
            allowed_tables=PAGILA_MVP_ALLOWED_TABLES,
        )
        return ApplicationServices(
            context=context,
            runner=default_traced_runner(),
            close=connector.close,
        )
    except Exception:
        connector.close()
        raise
