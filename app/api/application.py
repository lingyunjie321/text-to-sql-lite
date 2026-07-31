from __future__ import annotations

import asyncio
from collections.abc import Callable
from contextlib import asynccontextmanager
from typing import Annotated
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.api.bootstrap import (
    ApplicationServices,
    RequestIdentity,
    build_production_services,
    default_request_identity,
)
from app.api.models import (
    PublicError,
    QueryRequest,
    QueryResponse,
)
from app.api.overrides import OverrideError, resolve_request_context
from app.api.response import build_query_response
from app.config import AuthSettings, load_auth_settings
from app.connectors.errors import ErrorType
from app.workflow import (
    FinalStatus,
    new_task_state,
)

API_PATH = "/api/v1/text-to-sql"
IdFactory = Callable[[], str]
_bearer_scheme = HTTPBearer(auto_error=False)


def _authenticate(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Depends(_bearer_scheme),
    ],
) -> RequestIdentity:
    auth = load_auth_settings()
    if auth.api_key_value is None:
        return default_request_identity()
    if credentials is None:
        raise HTTPException(status_code=401, detail="API key required")
    if credentials.credentials != auth.api_key_value:
        raise HTTPException(status_code=403, detail="Invalid API key")
    can_debug = (
        auth.debug_key_value is not None
        and credentials.credentials == auth.debug_key_value
    )
    return RequestIdentity(
        subject="api-key-user",
        can_debug=can_debug,
    )


def _services_from_request(
    request: Request,
) -> ApplicationServices:
    services = getattr(request.app.state, "services", None)
    if not isinstance(services, ApplicationServices):
        raise RuntimeError("application services are unavailable")
    return services


def _model_summary(
    services: ApplicationServices,
    tier: str,
) -> dict[str, str]:
    """从运行时提取非敏感模型元数据（base_url + model_name，不含 api_key）。"""
    try:
        registration = (
            services.context.model_routing.provider_registry.resolve(
                tier
            )
        )
        provider = registration.provider
        # 唯一的具体 provider 是 OpenAICompatibleLLMProvider；
        # 通过私有 _settings 暴露 base_url 和 model_name。
        settings = provider._settings  # type: ignore[attr-defined]
        return {
            "base_url": str(settings.base_url),
            "model_name": settings.model,
        }
    except Exception:
        return {"base_url": "unknown", "model_name": "unknown"}


def _error_response(
    *,
    request_id: str,
    trace_id: str,
    status: FinalStatus,
    error_type: ErrorType,
    code: str,
    message: str,
) -> QueryResponse:
    return QueryResponse(
        request_id=request_id,
        trace_id=trace_id,
        status=status,
        error=PublicError(
            error_type=error_type,
            code=code,
            message=message,
        ),
    )


def _json_response(
    response: QueryResponse,
    *,
    status_code: int,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=response.model_dump(mode="json", by_alias=True),
    )


def create_app(
    *,
    services: ApplicationServices | None = None,
    id_factory: IdFactory | None = None,
) -> FastAPI:
    selected_id_factory = id_factory or (
        lambda: str(uuid4())
    )

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

    @app.get("/health")
    async def health() -> dict[str, object]:
        return {"status": "healthy"}

    @app.get("/api/v1/config")
    async def get_config(
        active_services: Annotated[
            ApplicationServices,
            Depends(_services_from_request),
        ],
    ) -> JSONResponse:
        datasources = {}
        for ds_id, ctx in active_services.contexts.items():
            datasources[ds_id] = {
                "datasource_id": ctx.datasource_id,
                "schemas": list(ctx.allowed_schemas),
                "tables": list(ctx.allowed_tables),
            }
        return JSONResponse(
            content={
                "datasources": datasources,
                "models": {
                    "simple": _model_summary(
                        active_services, "simple"
                    ),
                    "standard": _model_summary(
                        active_services, "standard"
                    ),
                    "complex": _model_summary(
                        active_services, "complex"
                    ),
                    "fallback": _model_summary(
                        active_services, "fallback"
                    ),
                },
            }
        )

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

    @app.post(
        API_PATH,
        response_model=QueryResponse,
        responses={
            400: {"model": QueryResponse},
            403: {"model": QueryResponse},
            500: {"model": QueryResponse},
        },
    )
    async def query_text_to_sql(
        query: QueryRequest,
        active_services: Annotated[
            ApplicationServices,
            Depends(_services_from_request),
        ],
        identity: Annotated[
            RequestIdentity,
            Depends(_authenticate),
        ],
    ) -> QueryResponse | JSONResponse:
        request_id = str(uuid4())
        trace_id = str(uuid4())
        try:
            selected_request_id = str(
                selected_id_factory()
            ).strip()
            selected_trace_id = str(
                selected_id_factory()
            ).strip()
            if not selected_request_id or not selected_trace_id:
                raise RuntimeError(
                    "request identifiers are unavailable"
                )
            request_id = selected_request_id
            trace_id = selected_trace_id

            if query.debug and not identity.can_debug:
                return _json_response(
                    _error_response(
                        request_id=request_id,
                        trace_id=trace_id,
                        status=FinalStatus.REJECTED_SECURITY,
                        error_type=ErrorType.PERMISSION_DENIED,
                        code="API_DEBUG_FORBIDDEN",
                        message="The request is not permitted.",
                    ),
                    status_code=403,
                )

            initial_state = new_task_state(
                request_id=request_id,
                trace_id=trace_id,
                question=query.question,
                datasource_id=query.datasource_id,
                requested_schemas=query.schemas,
            )
            ctx = resolve_request_context(query, active_services)
            terminal_state = await asyncio.to_thread(
                active_services.runner,
                initial_state,
                context=ctx,
            )
            return build_query_response(terminal_state)
        except OverrideError as override_error:
            return _json_response(
                _error_response(
                    request_id=request_id,
                    trace_id=trace_id,
                    status=FinalStatus.REJECTED_SECURITY,
                    error_type=ErrorType.PERMISSION_DENIED,
                    code="OVERRIDE_REJECTED",
                    message=override_error.message,
                ),
                status_code=400,
            )
        except Exception:
            return _json_response(
                _error_response(
                    request_id=request_id,
                    trace_id=trace_id,
                    status=FinalStatus.FAILED_INTERNAL,
                    error_type=ErrorType.UNKNOWN,
                    code="API_INTERNAL_ERROR",
                    message="The request could not be completed.",
                ),
                status_code=500,
            )

    return app
