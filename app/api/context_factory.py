"""Workflow context assembly at the API composition boundary."""

from __future__ import annotations

from app.connectors.base import DatabaseConnector
from app.generation.routing import ModelRoutingRuntime
from app.schema_linking import (
    EmbeddingIndexRegistry,
    EmbeddingProvider,
    RetrievalRuntime,
)
from app.workflow import WorkflowContext


class WorkflowContextFactory:
    """Build a context with one retrieval index registry per datasource."""

    def create(
        self,
        *,
        connector: DatabaseConnector,
        model_routing: ModelRoutingRuntime,
        datasource_id: str,
        allowed_schemas: tuple[str, ...],
        allowed_tables: tuple[str, ...],
        embedding_provider: EmbeddingProvider | None,
        embedding_registry: EmbeddingIndexRegistry | None = None,
        semantic_version: str,
    ) -> WorkflowContext:
        if embedding_provider is None and embedding_registry is not None:
            raise ValueError("embedding registry requires a provider")
        retrieval_runtime = (
            None
            if embedding_provider is None
            else RetrievalRuntime(
                provider=embedding_provider,
                registry=embedding_registry or EmbeddingIndexRegistry(),
                semantic_version=semantic_version,
            )
        )
        return WorkflowContext(
            connector=connector,
            model_routing=model_routing,
            datasource_id=datasource_id,
            allowed_schemas=allowed_schemas,
            allowed_tables=allowed_tables,
            retrieval_runtime=retrieval_runtime,
        )
