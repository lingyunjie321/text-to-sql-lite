from typing import Any

from pydantic import BaseModel, Field

from text_to_sql_demo.sql.dialect import DialectName


class QueryRequest(BaseModel):
    """Text-to-SQL 查询请求。"""

    question: str = Field(min_length=1)
    target_dialect: DialectName = "sqlite"
    max_attempts: int = Field(default=3, ge=0, le=3)
    debug: bool = False
    runtime_config_id: str | None = None


class TranspileRequest(BaseModel):
    """已有 SQL 的跨方言转换请求。"""

    sql: str = Field(min_length=1)
    source_dialect: DialectName
    target_dialect: DialectName


class ExecuteSQLRequest(BaseModel):
    """执行用户编辑后的只读 SQL。"""

    sql: str = Field(min_length=1)
    target_dialect: DialectName = "sqlite"
    max_rows: int = Field(default=100, ge=1, le=500)
    runtime_config_id: str | None = None


class ErrorBody(BaseModel):
    """统一 API 错误体。"""

    code: str
    message: str
    details: dict[str, Any] | list[Any] | None = None


class ErrorResponse(BaseModel):
    """统一 API 错误响应。"""

    error: ErrorBody
