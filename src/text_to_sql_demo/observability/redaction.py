from __future__ import annotations

from collections.abc import Mapping
from hashlib import sha256
from typing import Any

from sqlalchemy.engine import make_url

REDACTED = "***REDACTED***"

DEFAULT_REDACT_KEYS = frozenset(
    {
        "authorization",
        "api-key",
        "api_key",
        "password",
        "secret",
        "token",
        "x-api-key",
        "x_api_key",
    }
)


def redact_mapping(
    value: Any,
    *,
    redact_keys: set[str] | frozenset[str] = DEFAULT_REDACT_KEYS,
) -> Any:
    """递归脱敏 mapping/list 中的敏感字段。"""
    if isinstance(value, Mapping):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if _is_sensitive_key(key_text, redact_keys):
                redacted[key_text] = REDACTED
            else:
                redacted[key_text] = redact_mapping(item, redact_keys=redact_keys)
        return redacted

    if isinstance(value, list):
        return [redact_mapping(item, redact_keys=redact_keys) for item in value]

    if isinstance(value, tuple):
        return tuple(redact_mapping(item, redact_keys=redact_keys) for item in value)

    return value


def sanitize_database_url(database_url: str) -> str:
    """隐藏数据库 URL 中的密码，同时保留 driver、host 和 database 等定位信息。"""
    try:
        return make_url(database_url).render_as_string(hide_password=True)
    except Exception:  # noqa: BLE001 - 日志脱敏不能影响主流程。
        return "<invalid-database-url>"


def summarize_sql(
    sql: str,
    *,
    include_preview: bool = False,
    max_preview_chars: int = 160,
) -> dict[str, Any]:
    """生成 SQL 日志摘要；默认不输出 SQL 文本。"""
    summary: dict[str, Any] = {
        "sql_length": len(sql),
        "sql_hash": f"sha256:{sha256(sql.encode('utf-8')).hexdigest()[:16]}",
    }
    if include_preview:
        summary["sql_preview"] = sql[:max_preview_chars]
    return summary


def exception_location(error: BaseException) -> dict[str, Any]:
    """返回异常 traceback 的最后一帧位置。"""
    traceback = error.__traceback__
    if traceback is None:
        return {
            "error_file": None,
            "error_line": None,
            "error_function": None,
        }

    while traceback.tb_next is not None:
        traceback = traceback.tb_next

    code = traceback.tb_frame.f_code
    return {
        "error_file": code.co_filename,
        "error_line": traceback.tb_lineno,
        "error_function": code.co_name,
    }


def _is_sensitive_key(
    key: str,
    redact_keys: set[str] | frozenset[str],
) -> bool:
    lowered = key.lower()
    normalized = lowered.replace("-", "_")
    return lowered in redact_keys or normalized in redact_keys

