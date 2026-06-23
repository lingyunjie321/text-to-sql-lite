from __future__ import annotations

from time import perf_counter
from uuid import uuid4

from fastapi import FastAPI, Request, Response

from text_to_sql_demo.observability.context import clear_context, set_request_context
from text_to_sql_demo.observability.events import (
    log_api_request_completed,
    log_api_request_failed,
    log_api_request_started,
)


def add_request_logging_middleware(app: FastAPI) -> None:
    """为 FastAPI 应用添加请求级日志中间件。"""

    @app.middleware("http")
    async def request_logging_middleware(request: Request, call_next: object) -> Response:
        request_id = request.headers.get("x-request-id") or str(uuid4())
        set_request_context(request_id=request_id)
        started = perf_counter()
        method = request.method
        path = request.url.path
        log_api_request_started(method=method, path=path, request_id=request_id)
        try:
            response = await call_next(request)  # type: ignore[misc]
            response.headers["x-request-id"] = request_id
            log_api_request_completed(
                method=method,
                path=path,
                request_id=request_id,
                status_code=response.status_code,
                duration_ms=int((perf_counter() - started) * 1000),
            )
            return response
        except Exception as exc:
            log_api_request_failed(
                method=method,
                path=path,
                request_id=request_id,
                duration_ms=int((perf_counter() - started) * 1000),
                error=exc,
            )
            raise
        finally:
            clear_context()

