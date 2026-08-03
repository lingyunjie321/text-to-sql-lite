"""System read-only HTTP routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.api.bootstrap import ApplicationServices
from app.api.dependencies import services_from_request

system_router = APIRouter()


def _model_summary(
    services: ApplicationServices,
    tier: str,
) -> dict[str, str]:
    model_routing = services.model_routing
    if model_routing is None:
        return {"base_url": "unknown", "model_name": "unknown"}
    try:
        provider = model_routing.provider_registry.resolve(tier).provider
    except ValueError:
        return {"base_url": "unknown", "model_name": "unknown"}
    endpoint_summary = getattr(provider, "endpoint_summary", None)
    model_id = getattr(provider, "model_id", None)
    if not isinstance(endpoint_summary, str) or not isinstance(model_id, str):
        return {"base_url": "unknown", "model_name": "unknown"}
    return {"base_url": endpoint_summary, "model_name": model_id}


@system_router.get("/health")
async def health() -> dict[str, object]:
    return {"status": "healthy"}


@system_router.get("/api/v1/config")
async def get_config(
    active_services: Annotated[
        ApplicationServices,
        Depends(services_from_request),
    ],
) -> JSONResponse:
    datasources = {
        datasource_id: {
            "datasource_id": context.datasource_id,
            "schemas": list(context.allowed_schemas),
            "tables": list(context.allowed_tables),
        }
        for datasource_id, context in active_services.contexts.items()
    }
    return JSONResponse(
        content={
            "datasources": datasources,
            "models": {
                "simple": _model_summary(active_services, "simple"),
                "standard": _model_summary(active_services, "standard"),
                "complex": _model_summary(active_services, "complex"),
                "fallback": _model_summary(active_services, "fallback"),
            },
        }
    )
