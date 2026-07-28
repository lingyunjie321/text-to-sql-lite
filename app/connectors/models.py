from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
from enum import Enum
from typing import TypeAlias
from uuid import UUID

JsonValue: TypeAlias = (
    None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
)


@dataclass(frozen=True, slots=True)
class ResultColumn:
    name: str
    type_oid: int


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    columns: tuple[ResultColumn, ...]
    rows: list[list[JsonValue]]
    returned_row_count: int
    truncated: bool
    execution_time_ms: float


def normalize_value(value: object) -> JsonValue:
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
