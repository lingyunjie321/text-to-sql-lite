"""执行结果模型：连接器 ``execute`` 返回值的统一结构。

包含结果列描述、已规范化为 JSON 安全值的行数据、截断标记与执行
耗时；另提供 PostgreSQL 方言的兼容版 :func:`normalize_value`。
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
from enum import Enum
from typing import TypeAlias
from uuid import UUID

from app.connectors.types import JsonValue

__all__ = [
    "ExecutionResult",
    "JsonValue",
    "ResultColumn",
    "normalize_value",
]


@dataclass(frozen=True, slots=True)
class ResultColumn:
    """单个结果列的描述：列名与驱动报告的类型 OID。"""

    name: str
    type_oid: int


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    """一次 SQL 执行的结果。

    ``rows`` 最多包含 ``max_result_rows`` 行；当数据库实际返回更多行时
    ``truncated`` 为 ``True``（连接器多读一行以探测截断）。
    """

    columns: tuple[ResultColumn, ...]
    rows: list[list[JsonValue]]
    returned_row_count: int
    truncated: bool
    execution_time_ms: float


def normalize_value(value: object) -> JsonValue:
    """Normalize a database driver return value into a JSON-safe
    representation, using the PostgreSQL (psycopg) dialect.

    For multi-dialect support use :func:`app.connectors.types.normalize_value`
    directly with an explicit *dialect* parameter.
    """
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, (date, time)):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Enum):
        return normalize_value(value.value)
    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            raise TypeError("unsupported PostgreSQL result type: mapping key")
        return {
            key: normalize_value(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [normalize_value(item) for item in value]
    raise TypeError(
        f"unsupported PostgreSQL result type: {type(value).__name__}"
    )
