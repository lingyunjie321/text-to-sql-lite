from __future__ import annotations

from contextvars import ContextVar
from typing import Any

_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)
_workflow_name: ContextVar[str | None] = ContextVar("workflow_name", default=None)
_node_name: ContextVar[str | None] = ContextVar("node_name", default=None)
_node_type: ContextVar[str | None] = ContextVar("node_type", default=None)


def set_request_context(*, request_id: str | None) -> None:
    """设置当前请求日志上下文。"""
    _request_id.set(request_id)


def set_workflow_context(*, workflow_name: str | None) -> None:
    """设置当前工作流日志上下文。"""
    _workflow_name.set(workflow_name)


def set_node_context(*, node_name: str | None, node_type: str | None = None) -> None:
    """设置当前节点日志上下文。"""
    _node_name.set(node_name)
    _node_type.set(node_type)


def clear_context() -> None:
    """清空当前日志上下文。"""
    _request_id.set(None)
    _workflow_name.set(None)
    _node_name.set(None)
    _node_type.set(None)


def get_log_context() -> dict[str, Any]:
    """返回当前日志上下文字段。"""
    return {
        "request_id": _request_id.get(),
        "workflow_name": _workflow_name.get(),
        "node_name": _node_name.get(),
        "node_type": _node_type.get(),
    }

