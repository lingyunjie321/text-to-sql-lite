from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from app.connectors.models import ExecutionResult, JsonValue
from evaluation.models import (
    ComparisonMode,
    ComparisonResult,
    NumericTolerance,
)

COMPARATOR_VERSION = "stage1-comparator-v1"

_FLOAT_OIDS = frozenset({700, 701})
_NUMERIC_OIDS = frozenset({20, 21, 23, 700, 701, 1700})
_TIMESTAMPTZ_OID = 1184


def _result(
    passed: bool,
    code: str,
    *,
    predicted: ExecutionResult,
    gold: ExecutionResult,
) -> ComparisonResult:
    messages = {
        "COMPARATOR_MATCH": "The results match.",
        "COMPARATOR_NOT_APPLICABLE": "Result comparison is not applicable.",
        "COMPARATOR_COLUMN_MISMATCH": "The result columns do not match.",
        "COMPARATOR_GRAIN_MISMATCH": "The result grain does not match.",
        "COMPARATOR_ROW_MISMATCH": "The result rows do not match.",
        "COMPARATOR_DUPLICATE_KEY": "A keyed result contains duplicate keys.",
        "COMPARATOR_INVALID_KEY": "The keyed comparison is invalid.",
        "COMPARATOR_INVALID_TOLERANCE": (
            "A numeric tolerance targets a non-numeric column."
        ),
        "COMPARATOR_TOLERANCE_REQUIRED": (
            "A floating-point result requires an explicit tolerance."
        ),
        "COMPARATOR_TRUNCATED_RESULT": (
            "A truncated result cannot be verified."
        ),
    }
    return ComparisonResult(
        passed=passed,
        code=code,
        message=messages[code],
        predicted_row_count=len(predicted.rows),
        gold_row_count=len(gold.rows),
    )


def _column_name(name: str) -> str:
    return name.strip().casefold()


def _parse_timestamptz(value: JsonValue) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _strict_equal(left: JsonValue, right: JsonValue) -> bool:
    if type(left) is not type(right):
        return False
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(
            _strict_equal(left_item, right_item)
            for left_item, right_item in zip(left, right, strict=True)
        )
    if isinstance(left, dict) and isinstance(right, dict):
        return left.keys() == right.keys() and all(
            _strict_equal(left[key], right[key])
            for key in left
        )
    return left == right


def _decimal_equal(
    predicted: JsonValue,
    gold: JsonValue,
    tolerance: NumericTolerance,
) -> bool:
    if (
        isinstance(predicted, bool)
        or isinstance(gold, bool)
        or not isinstance(predicted, (int, float, str))
        or not isinstance(gold, (int, float, str))
    ):
        return False
    try:
        predicted_decimal = Decimal(str(predicted))
        gold_decimal = Decimal(str(gold))
    except InvalidOperation:
        return False
    if (
        not predicted_decimal.is_finite()
        or not gold_decimal.is_finite()
    ):
        return False
    difference = abs(predicted_decimal - gold_decimal)
    allowed = max(
        tolerance.absolute,
        tolerance.relative * abs(gold_decimal),
    )
    return difference <= allowed


def _value_equal(
    predicted: JsonValue,
    gold: JsonValue,
    *,
    type_oid: int,
    tolerance: NumericTolerance | None,
) -> bool:
    if predicted is None or gold is None:
        return predicted is None and gold is None
    if tolerance is not None:
        return _decimal_equal(predicted, gold, tolerance)
    if type_oid == _TIMESTAMPTZ_OID:
        predicted_time = _parse_timestamptz(predicted)
        gold_time = _parse_timestamptz(gold)
        if predicted_time is not None and gold_time is not None:
            return predicted_time == gold_time
    return _strict_equal(predicted, gold)


def _row_equal(
    predicted: list[JsonValue],
    gold: list[JsonValue],
    *,
    type_oids: tuple[int, ...],
    tolerances: tuple[NumericTolerance | None, ...],
) -> bool:
    return (
        len(predicted) == len(type_oids)
        and len(gold) == len(type_oids)
        and all(
            _value_equal(
                predicted_value,
                gold_value,
                type_oid=type_oid,
                tolerance=tolerance,
            )
            for predicted_value, gold_value, type_oid, tolerance in zip(
                predicted,
                gold,
                type_oids,
                tolerances,
                strict=True,
            )
        )
    )


def _unordered_rows_equal(
    predicted_rows: list[list[JsonValue]],
    gold_rows: list[list[JsonValue]],
    *,
    type_oids: tuple[int, ...],
    tolerances: tuple[NumericTolerance | None, ...],
) -> bool:
    adjacency = [
        [
            gold_index
            for gold_index, gold_row in enumerate(gold_rows)
            if _row_equal(
                predicted_row,
                gold_row,
                type_oids=type_oids,
                tolerances=tolerances,
            )
        ]
        for predicted_row in predicted_rows
    ]
    matched_prediction: list[int | None] = [None] * len(gold_rows)
    for start, options in enumerate(adjacency):
        direct = next(
            (
                gold_index
                for gold_index in options
                if matched_prediction[gold_index] is None
            ),
            None,
        )
        if direct is not None:
            matched_prediction[direct] = start
            continue

        pending = [start]
        pending_index = 0
        seen_prediction = {start}
        seen_gold: set[int] = set()
        parent_prediction: dict[int, int] = {}
        incoming_gold: dict[int, int] = {}
        final_prediction: int | None = None
        free_gold: int | None = None
        while pending_index < len(pending) and free_gold is None:
            predicted_index = pending[pending_index]
            pending_index += 1
            for gold_index in adjacency[predicted_index]:
                if gold_index in seen_gold:
                    continue
                seen_gold.add(gold_index)
                owner = matched_prediction[gold_index]
                if owner is None:
                    final_prediction = predicted_index
                    free_gold = gold_index
                    break
                if owner not in seen_prediction:
                    seen_prediction.add(owner)
                    parent_prediction[owner] = predicted_index
                    incoming_gold[owner] = gold_index
                    pending.append(owner)
        if final_prediction is None or free_gold is None:
            return False

        current_prediction = final_prediction
        current_gold = free_gold
        while True:
            matched_prediction[current_gold] = current_prediction
            if current_prediction == start:
                break
            current_gold = incoming_gold[current_prediction]
            current_prediction = parent_prediction[
                current_prediction
            ]
    return True


def _keys_equal(
    left: list[JsonValue],
    right: list[JsonValue],
    *,
    key_indices: tuple[int, ...],
    type_oids: tuple[int, ...],
    tolerances: tuple[NumericTolerance | None, ...],
) -> bool:
    return all(
        _value_equal(
            left[index],
            right[index],
            type_oid=type_oids[index],
            tolerance=tolerances[index],
        )
        for index in key_indices
    )


def _keyed_rows_equal(
    predicted_rows: list[list[JsonValue]],
    gold_rows: list[list[JsonValue]],
    *,
    key_indices: tuple[int, ...],
    type_oids: tuple[int, ...],
    tolerances: tuple[NumericTolerance | None, ...],
) -> tuple[bool, bool]:
    for rows in (predicted_rows, gold_rows):
        for left_index, left in enumerate(rows):
            if any(
                _keys_equal(
                    left,
                    right,
                    key_indices=key_indices,
                    type_oids=type_oids,
                    tolerances=tolerances,
                )
                for right in rows[left_index + 1 :]
            ):
                return False, True

    matched_gold: set[int] = set()
    for predicted_row in predicted_rows:
        matches = tuple(
            gold_index
            for gold_index, gold_row in enumerate(gold_rows)
            if _keys_equal(
                predicted_row,
                gold_row,
                key_indices=key_indices,
                type_oids=type_oids,
                tolerances=tolerances,
            )
        )
        if len(matches) != 1 or matches[0] in matched_gold:
            return False, False
        matched_gold.add(matches[0])
        if not _row_equal(
            predicted_row,
            gold_rows[matches[0]],
            type_oids=type_oids,
            tolerances=tolerances,
        ):
            return False, False
    return len(matched_gold) == len(gold_rows), False


def compare_results(
    predicted: ExecutionResult,
    gold: ExecutionResult,
    *,
    mode: ComparisonMode,
    order_sensitive: bool,
    numeric_tolerances: Mapping[str, NumericTolerance],
    key_columns: tuple[str, ...] = (),
) -> ComparisonResult:
    if mode is ComparisonMode.NONE:
        return _result(
            False,
            "COMPARATOR_NOT_APPLICABLE",
            predicted=predicted,
            gold=gold,
        )
    if predicted.truncated or gold.truncated:
        return _result(
            False,
            "COMPARATOR_TRUNCATED_RESULT",
            predicted=predicted,
            gold=gold,
        )

    predicted_columns = tuple(
        (_column_name(column.name), column.type_oid)
        for column in predicted.columns
    )
    gold_columns = tuple(
        (_column_name(column.name), column.type_oid)
        for column in gold.columns
    )
    if (
        len(predicted_columns) != len(gold_columns)
        or len({name for name, _ in predicted_columns})
        != len(predicted_columns)
        or len({name for name, _ in gold_columns})
        != len(gold_columns)
        or any(
            len(row) != len(predicted_columns)
            for row in predicted.rows
        )
        or any(len(row) != len(gold_columns) for row in gold.rows)
    ):
        return _result(
            False,
            "COMPARATOR_COLUMN_MISMATCH",
            predicted=predicted,
            gold=gold,
        )

    predicted_indices = {
        name: index
        for index, (name, _) in enumerate(predicted_columns)
    }
    gold_names = tuple(name for name, _ in gold_columns)
    if (
        predicted_indices.keys() != {name for name in gold_names}
        or any(
            predicted_columns[predicted_indices[name]][1] != type_oid
            for name, type_oid in gold_columns
        )
    ):
        return _result(
            False,
            "COMPARATOR_COLUMN_MISMATCH",
            predicted=predicted,
            gold=gold,
        )
    predicted_rows = [
        [row[predicted_indices[name]] for name in gold_names]
        for row in predicted.rows
    ]

    normalized_tolerances = {
        _column_name(name): tolerance
        for name, tolerance in numeric_tolerances.items()
    }
    column_names = gold_names
    if any(name not in column_names for name in normalized_tolerances):
        return _result(
            False,
            "COMPARATOR_COLUMN_MISMATCH",
            predicted=predicted,
            gold=gold,
        )
    type_oids = tuple(type_oid for _, type_oid in gold_columns)
    tolerances = tuple(
        normalized_tolerances.get(name)
        for name in column_names
    )
    if any(
        tolerance is not None and type_oid not in _NUMERIC_OIDS
        for type_oid, tolerance in zip(
            type_oids,
            tolerances,
            strict=True,
        )
    ):
        return _result(
            False,
            "COMPARATOR_INVALID_TOLERANCE",
            predicted=predicted,
            gold=gold,
        )
    if any(
        type_oid in _FLOAT_OIDS
        and tolerance is None
        and (predicted_rows or gold.rows)
        for type_oid, tolerance in zip(
            type_oids,
            tolerances,
            strict=True,
        )
    ):
        return _result(
            False,
            "COMPARATOR_TOLERANCE_REQUIRED",
            predicted=predicted,
            gold=gold,
        )

    if len(predicted_rows) != len(gold.rows):
        return _result(
            False,
            "COMPARATOR_GRAIN_MISMATCH",
            predicted=predicted,
            gold=gold,
        )

    if order_sensitive or mode is ComparisonMode.EXACT:
        rows_match = all(
            _row_equal(
                predicted_row,
                gold_row,
                type_oids=type_oids,
                tolerances=tolerances,
            )
            for predicted_row, gold_row in zip(
                predicted_rows,
                gold.rows,
                strict=True,
            )
        )
        duplicate_key = False
    elif mode is ComparisonMode.MULTISET:
        rows_match = _unordered_rows_equal(
            predicted_rows,
            gold.rows,
            type_oids=type_oids,
            tolerances=tolerances,
        )
        duplicate_key = False
    else:
        normalized_keys = tuple(
            _column_name(name) for name in key_columns
        )
        if (
            not normalized_keys
            or len(set(normalized_keys)) != len(normalized_keys)
            or any(name not in column_names for name in normalized_keys)
        ):
            return _result(
                False,
                "COMPARATOR_INVALID_KEY",
                predicted=predicted,
                gold=gold,
            )
        key_indices = tuple(
            column_names.index(name) for name in normalized_keys
        )
        rows_match, duplicate_key = _keyed_rows_equal(
            predicted_rows,
            gold.rows,
            key_indices=key_indices,
            type_oids=type_oids,
            tolerances=tolerances,
        )
    if duplicate_key:
        code = "COMPARATOR_DUPLICATE_KEY"
    else:
        code = (
            "COMPARATOR_MATCH"
            if rows_match
            else "COMPARATOR_ROW_MISMATCH"
        )
    return _result(
        rows_match,
        code,
        predicted=predicted,
        gold=gold,
    )
