"""FastAPI application assembly."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.api.bootstrap import ApplicationServices, build_production_services
from app.api.dependencies import authenticate as _authenticate
from app.api.dependencies import services_from_request as _services_from_request
from app.api.routes import API_PATH, create_query_router, system_router

IdFactory = Callable[[], str]


def create_app(
    *,
    services: ApplicationServices | None = None,
    id_factory: IdFactory | None = None,
) -> FastAPI:
    selected_id_factory = id_factory or (lambda: str(uuid4()))

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        active_services = services
        owns_services = active_services is None
        if active_services is None:
            active_services = build_production_services()
        app.state.services = active_services
        try:
            yield
        finally:
            app.state.services = None
            if owns_services and active_services.close is not None:
                active_services.close()

    app = FastAPI(
        title="Text-to-SQL Agent",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.include_router(system_router)
    app.include_router(create_query_router(selected_id_factory))

    @app.exception_handler(RequestValidationError)
    async def handle_request_validation_error(
        request: Request,
        error: RequestValidationError,
    ) -> JSONResponse:
        del request, error
        return JSONResponse(
            status_code=422,
            content={
                "detail": [
                    {
                        "type": "request_validation",
                        "loc": ["body"],
                        "msg": "Request validation failed.",
                    }
                ]
            },
        )

    return app
