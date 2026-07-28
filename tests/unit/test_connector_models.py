from datetime import date, datetime, time, timezone
from decimal import Decimal
from enum import Enum
from uuid import UUID

import pytest

from app.connectors.models import ExecutionResult, ResultColumn, normalize_value


class ExampleEnum(Enum):
    VALUE = "value"


def test_normalize_value_preserves_json_precision_and_timezone() -> None:
    value = {
        "amount": Decimal("10.20"),
        "at": datetime(2026, 7, 28, 8, 30, tzinfo=timezone.utc),
        "id": UUID("12345678-1234-5678-1234-567812345678"),
        "items": [None, Decimal("0.01")],
    }

    assert normalize_value(value) == {
        "amount": "10.20",
        "at": "2026-07-28T08:30:00+00:00",
        "id": "12345678-1234-5678-1234-567812345678",
        "items": [None, "0.01"],
    }


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, None),
        (True, True),
        (3, 3),
        (1.5, 1.5),
        ("text", "text"),
        (Decimal("1.230"), "1.230"),
        (date(2026, 7, 28), "2026-07-28"),
        (time(8, 30, 1), "08:30:01"),
        (datetime(2026, 7, 28, 8, 30), "2026-07-28T08:30:00"),
        (UUID("12345678-1234-5678-1234-567812345678"),
         "12345678-1234-5678-1234-567812345678"),
        (ExampleEnum.VALUE, "value"),
        ((Decimal("2.0"), date(2026, 7, 28)), ["2.0", "2026-07-28"]),
    ],
)
def test_normalize_value_supports_postgresql_result_values(
    value: object, expected: object
) -> None:
    assert normalize_value(value) == expected


def test_normalize_value_rejects_unsupported_type_without_value() -> None:
    class Sensitive:
        def __repr__(self) -> str:
            return "password=do-not-leak"

    with pytest.raises(
        TypeError, match="unsupported PostgreSQL result type: Sensitive"
    ) as caught:
        normalize_value(Sensitive())

    assert "do-not-leak" not in str(caught.value)


def test_execution_result_is_driver_independent() -> None:
    result = ExecutionResult(
        columns=(ResultColumn(name="amount", type_oid=1700),),
        rows=[["10.20"]],
        returned_row_count=1,
        truncated=False,
        execution_time_ms=1.25,
    )

    assert result.columns[0].name == "amount"
    assert result.rows == [["10.20"]]

