from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

ErrorCategory = Literal[
    "syntax_error",
    "unknown_table",
    "unknown_column",
    "ambiguous_column",
    "type_mismatch",
    "dialect_error",
    "execution_error",
]


class SQLError(BaseModel):
    """统一 SQL 错误结构。"""

    category: ErrorCategory
    message: str
    raw_message: str | None = None
    table: str | None = None
    column: str | None = None


class SQLValidationResult(BaseModel):
    """SQL 校验结果。"""

    success: bool
    normalized_sql: str | None = None
    rendered_sql: str | None = None
    error: SQLError | None = None


class SQLExecutionResult(BaseModel):
    """SQL 执行结果。"""

    success: bool
    columns: list[str] = Field(default_factory=list)
    rows: list[dict[str, object]] = Field(default_factory=list)
    duration_ms: int = 0
    error: SQLError | None = None


class RepairStrategy(BaseModel):
    """按 SQL 错误类型生成的定向修复策略。"""

    name: str
    focus: str
    instructions: list[str] = Field(default_factory=list)
    avoid: list[str] = Field(default_factory=list)


class RepairInstruction(BaseModel):
    """反思节点输出的结构化修复指令。"""

    original_question: str
    current_sql: str
    error_category: ErrorCategory
    original_error: str
    related_schema: dict
    repair_history: list[dict[str, object]] = Field(default_factory=list)
    reason: str
    strategy: RepairStrategy | None = None
