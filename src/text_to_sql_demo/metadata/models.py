from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    """返回带 UTC 时区的当前时间，便于测试替换固定时间。"""
    return datetime.now(UTC)


class TraceEventRecord(BaseModel):
    """内部 metadata store 中保存的节点 Trace 摘要。"""

    request_id: str
    step: int
    node_name: str
    node_type: str
    status: str
    outcome: str
    duration_ms: int
    input_summary: dict[str, Any] = Field(default_factory=dict)
    output_summary: dict[str, Any] = Field(default_factory=dict)
    error: dict[str, Any] | None = None
    started_at: datetime
    ended_at: datetime


class QueryRunRecord(BaseModel):
    """一次自然语言查询运行的可持久化摘要。"""

    request_id: str
    question: str
    status: str
    final_sql: str | None = None
    attempts: int = 0
    selected_model: str | None = None
    routing_reason: str | None = None
    target_dialect: str
    runtime_config_id: str | None = None
    row_count: int | None = None
    error_message: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class StoredQueryRun(BaseModel):
    """运行记录和对应 Trace 的组合视图。"""

    query_run: QueryRunRecord
    trace_events: list[TraceEventRecord] = Field(default_factory=list)


class QueryRunList(BaseModel):
    """运行记录列表响应。"""

    items: list[QueryRunRecord]
    total: int


class SavedQueryRecord(BaseModel):
    """运营或分析师收藏沉淀的 SQL。"""

    id: str
    name: str
    question: str
    sql: str
    created_from_run_id: str | None = None
    tags: list[str] = Field(default_factory=list)
    status: Literal["draft", "approved", "deprecated"] = "draft"
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class SavedQueryList(BaseModel):
    """收藏 SQL 列表响应。"""

    items: list[SavedQueryRecord]
    total: int


class FeedbackRecord(BaseModel):
    """用户对一次查询运行的轻量反馈。"""

    id: str
    request_id: str
    rating: Literal["up", "down", "neutral"]
    issue_type: str | None = None
    comment: str | None = None
    created_at: datetime = Field(default_factory=utc_now)


class FeedbackList(BaseModel):
    """反馈列表响应。"""

    items: list[FeedbackRecord]
    total: int
