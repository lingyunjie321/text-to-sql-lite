from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class WorkflowError(BaseModel):
    """工作流执行期间捕获的结构化错误。"""

    node_name: str
    error_type: str
    message: str


class TraceEvent(BaseModel):
    """节点级执行 Trace 条目。"""

    request_id: str
    node_name: str
    node_type: str
    status: str
    outcome: str
    step: int
    started_at: datetime
    ended_at: datetime
    duration_ms: int
    input_summary: dict[str, Any] = Field(default_factory=dict)
    output_summary: dict[str, Any] = Field(default_factory=dict)
    error: dict[str, Any] | None = None
    error_message: str | None = None


class WorkflowState(BaseModel):
    """工作流节点共享的类型化状态。"""

    request_id: str = Field(default_factory=lambda: str(uuid4()))
    user_question: str = ""
    data: dict[str, Any] = Field(default_factory=dict)
    current_node: str | None = None
    next_node: str | None = None
    last_outcome: str | None = None
    step_count: int = 0
    terminated: bool = False
    termination_reason: str | None = None
    errors: list[WorkflowError] = Field(default_factory=list)
    trace: list[TraceEvent] = Field(default_factory=list)
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    def apply_patch(self, patch: dict[str, Any]) -> None:
        """把节点返回的 state patch 合并到当前状态。"""
        for key, value in patch.items():
            if key == "data" and isinstance(value, dict):
                self.data.update(value)
            elif hasattr(self, key):
                setattr(self, key, value)
            else:
                self.data[key] = value

    def terminate(self, reason: str) -> None:
        """使用稳定原因标记工作流已终止。"""
        self.terminated = True
        self.termination_reason = reason
