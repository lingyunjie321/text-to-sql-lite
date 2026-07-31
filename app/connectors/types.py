"""连接器共享类型：JSON 安全值、方言名称与驱动返回值规范化。

:func:`normalize_value` 把各数据库驱动返回的 Python 值（Decimal、
日期时间、字节串等）转换为可 JSON 序列化的表示，保证执行结果可以
安全地写入 API 响应与审计证据。
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from enum import Enum
from typing import Literal, TypeAlias
from uuid import UUID

JsonValue: TypeAlias = (
    None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
)

DialectName: TypeAlias = Literal["postgres", "mysql", "starrocks"]


def normalize_value(
    value: object,
    *,
    dialect: DialectName = "postgres",
) -> JsonValue:
    """Normalize a database driver return value into a JSON-safe representation.

    Handles PostgreSQL (psycopg), MySQL (pymysql), and StarRocks (pymysql
    protocol) type differences.
    """
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Decimal):
        return _normalize_decimal(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, time):
        return value.isoformat()
    if isinstance(value, timedelta):
        return _normalize_timedelta(value)
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, bytes):
        return _normalize_bytes(value)
    if isinstance(value, bytearray):
        return _normalize_bytes(bytes(value))
    if isinstance(value, Enum):
        return normalize_value(value.value, dialect=dialect)
    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            raise TypeError(
                f"unsupported {dialect} result type: non-string mapping key"
            )
        return {
            key: normalize_value(item, dialect=dialect)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple, set)):
        return [normalize_value(item, dialect=dialect) for item in value]
    raise TypeError(
        f"unsupported {dialect} result type: {type(value).__name__}"
    )


def _normalize_decimal(value: Decimal) -> str:
    """Normalize Decimal to string, preserving exact representation."""
    return str(value)


def _normalize_timedelta(value: timedelta) -> str:
    """Normalize timedelta to ISO 8601 duration-ish string."""
    total_seconds = int(value.total_seconds())
    days, remainder = divmod(abs(total_seconds), 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, seconds = divmod(remainder, 60)
    sign = "-" if total_seconds < 0 else ""
    if value.microseconds:
        return (
            f"{sign}{days} days, "
            f"{hours:02d}:{minutes:02d}:{seconds:02d}."
            f"{value.microseconds:06d}"
        )
    return (
        f"{sign}{days} days, "
        f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    )


def _normalize_bytes(value: bytes) -> str:
    """Normalize bytes to a hex string for safe transport."""
    if len(value) <= 64:
        return f"\\x{value.hex()}"
    return f"\\x{value[:32].hex()}...({len(value)} bytes)"
