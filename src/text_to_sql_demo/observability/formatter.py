from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

from text_to_sql_demo.observability.context import get_log_context
from text_to_sql_demo.observability.redaction import exception_location, redact_mapping

_RESERVED_LOG_RECORD_KEYS = {
    "args",
    "asctime",
    "created",
    "exc_info",
    "exc_text",
    "filename",
    "funcName",
    "levelname",
    "levelno",
    "lineno",
    "module",
    "msecs",
    "message",
    "msg",
    "name",
    "pathname",
    "process",
    "processName",
    "relativeCreated",
    "stack_info",
    "thread",
    "threadName",
    "taskName",
}


class JsonLogFormatter(logging.Formatter):
    """输出 JSON Lines 的日志 formatter。"""

    def format(self, record: logging.LogRecord) -> str:
        payload = _record_payload(record)
        return json.dumps(payload, ensure_ascii=False, default=str)


class ConsoleLogFormatter(logging.Formatter):
    """输出适合本地阅读的短文本日志。"""

    def format(self, record: logging.LogRecord) -> str:
        payload = _record_payload(record)
        timestamp = datetime.fromtimestamp(record.created, UTC).strftime("%Y-%m-%d %H:%M:%S")
        parts = [
            timestamp,
            str(payload.get("level", record.levelname)),
            str(payload.get("event") or "-"),
        ]

        if payload.get("request_id"):
            parts.append(f"request_id={payload['request_id']}")
        if payload.get("node_name"):
            parts.append(f"node={payload['node_name']}")
        if payload.get("outcome"):
            parts.append(f"outcome={payload['outcome']}")

        message = str(payload.get("message") or record.getMessage())
        if message:
            parts.append(message)

        for key, value in payload.items():
            if key in _CONSOLE_BASE_KEYS or value is None:
                continue
            parts.append(f"{key}={value}")

        return " ".join(parts)


_CONSOLE_BASE_KEYS = {
    "timestamp",
    "level",
    "logger",
    "event",
    "message",
    "request_id",
    "workflow_name",
    "node_name",
    "node_type",
    "outcome",
    "source_file",
    "source_line",
    "source_function",
}


def _record_payload(record: logging.LogRecord) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
        "level": record.levelname,
        "logger": record.name,
        "message": record.getMessage(),
        "source_file": record.pathname,
        "source_line": record.lineno,
        "source_function": record.funcName,
    }
    payload.update({key: value for key, value in get_log_context().items() if value is not None})
    payload.update(_extra_payload(record))

    if record.exc_info and record.exc_info[1] is not None:
        error = record.exc_info[1]
        payload.update(
            {
                "error_type": error.__class__.__name__,
                "error_message": str(error),
            }
        )
        payload.update(exception_location(error))

    return redact_mapping(payload)


def _extra_payload(record: logging.LogRecord) -> dict[str, Any]:
    return {
        key: value
        for key, value in record.__dict__.items()
        if key not in _RESERVED_LOG_RECORD_KEYS and not key.startswith("_")
    }

