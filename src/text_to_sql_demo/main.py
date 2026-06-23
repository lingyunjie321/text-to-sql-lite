from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from text_to_sql_demo.api.models import ExecuteSQLRequest, QueryRequest, TranspileRequest
from text_to_sql_demo.api.service import ApiError, TextToSQLApiService
from text_to_sql_demo.config.loader import load_workflow_config
from text_to_sql_demo.exceptions import TextToSQLDemoError
from text_to_sql_demo.llm.client import LLMClient
from text_to_sql_demo.observability.events import (
    log_service_initialization_completed,
    log_service_initialization_failed,
    log_service_initialization_started,
)
from text_to_sql_demo.observability.logging import configure_logging
from text_to_sql_demo.observability.middleware import add_request_logging_middleware
from text_to_sql_demo.runtime.exceptions import RuntimeConnectionTestError
from text_to_sql_demo.runtime.models import RuntimeConfigCreateRequest
from text_to_sql_demo.runtime.store import RuntimeConfigStore
from text_to_sql_demo.sql.dialect import DialectRenderResult, DialectService


def create_app(
    *,
    config_path: str | Path = "workflow.yaml",
    database_url: str | None = None,
    llm_client: LLMClient | None = None,
    runtime_store: RuntimeConfigStore | None = None,
) -> FastAPI:
    """创建 demo 服务的 FastAPI 应用。"""
    app = FastAPI(title="Text-to-SQL Agent Demo", version="0.1.0")
    configure_logging(load_workflow_config(config_path).logging)
    add_request_logging_middleware(app)
    service: TextToSQLApiService | None = None

    def get_service() -> TextToSQLApiService:
        """按需创建应用服务，避免 import 阶段读取真实 LLM 凭据。"""
        nonlocal service
        if service is None:
            try:
                log_service_initialization_started()
                service = TextToSQLApiService(
                    config_path=config_path,
                    database_url=database_url,
                    llm_client=llm_client,
                    runtime_store=runtime_store,
                )
                log_service_initialization_completed()
            except (TextToSQLDemoError, ValueError) as exc:
                log_service_initialization_failed(error=exc)
                raise ApiError(
                    status_code=500,
                    code="service_config_error",
                    message=str(exc),
                ) from exc
        return service

    @app.exception_handler(ApiError)
    def handle_api_error(request: object, exc: ApiError) -> JSONResponse:
        """把应用服务异常转换为统一 API 错误响应。"""
        return _error_response(
            status_code=exc.status_code,
            code=exc.code,
            message=exc.message,
            details=exc.details,
        )

    @app.exception_handler(HTTPException)
    def handle_http_error(request: object, exc: HTTPException) -> JSONResponse:
        """把 FastAPI HTTPException 转换为统一 API 错误响应。"""
        return _error_response(
            status_code=exc.status_code,
            code="http_error",
            message=str(exc.detail),
        )

    @app.exception_handler(RequestValidationError)
    def handle_validation_error(request: object, exc: RequestValidationError) -> JSONResponse:
        """把请求校验错误转换为统一 API 错误响应。"""
        return _error_response(
            status_code=422,
            code="validation_error",
            message="请求参数校验失败",
            details={"errors": _sanitize_validation_detail(exc.errors())},
        )

    @app.exception_handler(RuntimeConnectionTestError)
    def handle_runtime_connection_error(
        request: object,
        exc: RuntimeConnectionTestError,
    ) -> JSONResponse:
        """把运行时连通性测试失败转换为稳定且脱敏的 API 响应。"""
        return _error_response(
            status_code=400,
            code="runtime_connection_failed",
            message=str(exc),
        )

    @app.get("/health")
    def health() -> dict[str, str]:
        """返回最小可用的存活检查响应。"""
        return {"status": "ok", "service": "text-to-sql-demo"}

    @app.post("/api/v1/query")
    def query(request: QueryRequest) -> dict[str, Any]:
        """执行可配置 Text-to-SQL 工作流。"""
        return get_service().run_query(request)

    @app.get("/api/v1/runs/{request_id}")
    def get_run(request_id: str) -> dict[str, Any]:
        """按 request_id 查询工作流运行记录。"""
        return get_service().get_run(request_id)

    @app.get("/api/v1/schema")
    def get_schema(runtime_config_id: str | None = None) -> dict[str, Any]:
        """返回当前 demo 数据库 Schema 元数据。"""
        return get_service().get_schema(runtime_config_id=runtime_config_id).model_dump(
            mode="python"
        )

    @app.get("/api/v1/runtime/options")
    def get_runtime_options() -> dict[str, Any]:
        """返回运行时配置可选项。"""
        return get_service().get_runtime_options()

    @app.post("/api/v1/runtime/configs")
    def create_runtime_config(request: RuntimeConfigCreateRequest) -> dict[str, Any]:
        """创建短生命周期运行时配置。"""
        return get_service().create_runtime_config(request)

    @app.post("/api/v1/sql/execute")
    def execute_sql(request: ExecuteSQLRequest) -> dict[str, Any]:
        """执行用户修改后的只读 SQL。"""
        return get_service().execute_sql(request)

    @app.post("/api/v1/transpile", response_model=DialectRenderResult)
    def transpile_v1(request: TranspileRequest) -> DialectRenderResult:
        """转换已有 SQL 到目标方言。"""
        return _transpile(request)

    @app.post("/transpile", response_model=DialectRenderResult)
    def transpile_legacy(request: TranspileRequest) -> DialectRenderResult:
        """保留旧路径，兼容已有测试和示例。"""
        return _transpile(request)

    return app


def _transpile(request: TranspileRequest) -> DialectRenderResult:
    try:
        return DialectService().transpile(
            sql=request.sql,
            source_dialect=request.source_dialect,
            target_dialect=request.target_dialect,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _error_response(
    *,
    status_code: int,
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": code,
                "message": message,
                "details": details,
            }
        },
    )


def _sanitize_validation_detail(value: object) -> object:
    """递归移除 FastAPI/Pydantic 校验错误中的原始输入值。"""
    if isinstance(value, dict):
        return {
            key: _sanitize_validation_detail(item)
            for key, item in value.items()
            if key != "input"
        }
    if isinstance(value, list):
        return [_sanitize_validation_detail(item) for item in value]
    if isinstance(value, tuple):
        return [_sanitize_validation_detail(item) for item in value]
    if value is None or isinstance(value, str | int | float | bool):
        return value
    return str(value)


app = create_app()
