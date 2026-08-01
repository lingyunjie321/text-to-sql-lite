"""Text-to-SQL query HTTP route."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.api.bootstrap import ApplicationServices, RequestIdentity
from app.api.dependencies import authenticate, services_from_request
from app.api.models import PublicError, QueryRequest, QueryResponse
from app.api.overrides import OverrideError, resolve_request_context
from app.api.response import build_query_response
from app.connectors.errors import ErrorType
from app.workflow import FinalStatus, new_task_state

API_PATH = "/api/v1/text-to-sql"
IdFactory = Callable[[], str]
logger = logging.getLogger(__name__)


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


def create_query_router(id_factory: IdFactory) -> APIRouter:
    router = APIRouter()

    @router.post(
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
            Depends(services_from_request),
        ],
        identity: Annotated[
            RequestIdentity,
            Depends(authenticate),
        ],
    ) -> QueryResponse | JSONResponse:
        request_id = str(uuid4())
        trace_id = str(uuid4())
        try:
            selected_request_id = str(id_factory()).strip()
            selected_trace_id = str(id_factory()).strip()
            if not selected_request_id or not selected_trace_id:
                raise RuntimeError("request identifiers are unavailable")
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
            context = resolve_request_context(query, active_services)
            terminal_state = await asyncio.to_thread(
                active_services.runner,
                initial_state,
                context=context,
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
            logger.warning(
                "api_query_unexpected_error",
                extra={
                    "request_id": request_id,
                    "trace_id": trace_id,
                    "error_category": "unexpected",
                },
            )
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

    return router
