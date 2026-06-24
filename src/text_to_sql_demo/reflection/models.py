from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class ReflectionStrategy(StrEnum):
    """反思决策可选择的轻量策略。"""

    FIX_SQL = "FIX_SQL"
    RELINK_SCHEMA = "RELINK_SCHEMA"
    RETRIEVE_CONTEXT = "RETRIEVE_CONTEXT"
    REASONING_REWRITE = "REASONING_REWRITE"
    HITL = "HITL"
    STOP = "STOP"
    # COLUMN_EXPLORATION 作为后续能力预留，当前阶段不实现节点。


class ReflectionDecision(BaseModel):
    """反思节点输出的策略决策。"""

    strategy: ReflectionStrategy
    reason: str
    confidence: float = Field(ge=0.0, le=1.0)
    error_category: str | None
    attempt_count: int
    max_attempts: int
    next_hint: str | None = None


class SQLAttemptContext(BaseModel):
    """本次 workflow 内的 SQL 尝试工作记忆。"""

    attempt: int
    sql: str | None = None
    validation_error: dict[str, Any] | None = None
    execution_error: dict[str, Any] | None = None
    result_summary: dict[str, Any] | None = None
    reflection_strategy: str | None = None
    reflection_reason: str | None = None
