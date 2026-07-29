from decimal import Decimal

import pytest

from app.connectors.models import ExecutionResult, ResultColumn
from evaluation import ComparisonMode, NumericTolerance
from evaluation.comparator import compare_results


def _result(
    columns: list[tuple[str, int]],
    rows: list[list[object]],
) -> ExecutionResult:
    return ExecutionResult(
        columns=tuple(
            ResultColumn(name=name, type_oid=type_oid)
            for name, type_oid in columns
        ),
        rows=rows,  # type: ignore[arg-type]
        returned_row_count=len(rows),
        truncated=False,
        execution_time_ms=0.1,
    )


def test_exact_mode_requires_row_order() -> None:
    columns = [("film_id", 23)]
    result = compare_results(
        _result(columns, [[2], [1]]),
        _result(columns, [[1], [2]]),
        mode=ComparisonMode.EXACT,
        order_sensitive=False,
        numeric_tolerances={},
    )

    assert result.passed is False
    assert result.code == "COMPARATOR_ROW_MISMATCH"


def test_multiset_ignores_order_but_preserves_duplicates() -> None:
    columns = [("film_id", 23)]
    reordered = compare_results(
        _result(columns, [[2], [1], [1]]),
        _result(columns, [[1], [2], [1]]),
        mode=ComparisonMode.MULTISET,
        order_sensitive=False,
        numeric_tolerances={},
    )
    missing_duplicate = compare_results(
        _result(columns, [[1], [2]]),
        _result(columns, [[1], [1], [2]]),
        mode=ComparisonMode.MULTISET,
        order_sensitive=False,
        numeric_tolerances={},
    )

    assert reordered.passed is True
    assert missing_duplicate.passed is False
    assert missing_duplicate.code == "COMPARATOR_GRAIN_MISMATCH"


def test_multiset_handles_the_full_1000_duplicate_row_limit() -> None:
    columns = [("film_id", 23)]
    rows = [[1] for _ in range(1000)]

    result = compare_results(
        _result(columns, rows),
        _result(columns, rows),
        mode=ComparisonMode.MULTISET,
        order_sensitive=False,
        numeric_tolerances={},
    )

    assert result.passed is True


def test_null_and_empty_string_are_not_equal() -> None:
    columns = [("value", 25)]

    result = compare_results(
        _result(columns, [[None]]),
        _result(columns, [[""]]),
        mode=ComparisonMode.MULTISET,
        order_sensitive=False,
        numeric_tolerances={},
    )

    assert result.passed is False
    assert result.code == "COMPARATOR_ROW_MISMATCH"


def test_nested_json_compares_structurally() -> None:
    columns = [("payload", 3802)]

    result = compare_results(
        _result(columns, [[{"b": [2], "a": 1}]]),
        _result(columns, [[{"a": 1, "b": [2]}]]),
        mode=ComparisonMode.MULTISET,
        order_sensitive=False,
        numeric_tolerances={},
    )

    assert result.passed is True


def test_column_names_are_normalized_but_types_are_exact() -> None:
    normalized = compare_results(
        _result([(" Film_ID ", 23)], [[1]]),
        _result([("film_id", 23)], [[1]]),
        mode=ComparisonMode.MULTISET,
        order_sensitive=False,
        numeric_tolerances={},
    )
    wrong_type = compare_results(
        _result([("film_id", 20)], [[1]]),
        _result([("film_id", 23)], [[1]]),
        mode=ComparisonMode.MULTISET,
        order_sensitive=False,
        numeric_tolerances={},
    )

    assert normalized.passed is True
    assert wrong_type.code == "COMPARATOR_COLUMN_MISMATCH"


def test_columns_with_the_same_names_and_types_align_by_name() -> None:
    result = compare_results(
        _result(
            [("title", 25), ("film_id", 23)],
            [["ACADEMY DINOSAUR", 1]],
        ),
        _result(
            [("film_id", 23), ("title", 25)],
            [[1, "ACADEMY DINOSAUR"]],
        ),
        mode=ComparisonMode.MULTISET,
        order_sensitive=False,
        numeric_tolerances={},
    )

    assert result.passed is True
    assert result.code == "COMPARATOR_MATCH"


def test_missing_or_extra_column_fails() -> None:
    result = compare_results(
        _result([("film_id", 23)], [[1]]),
        _result([("film_id", 23), ("title", 25)], [[1, "A"]]),
        mode=ComparisonMode.MULTISET,
        order_sensitive=False,
        numeric_tolerances={},
    )

    assert result.passed is False
    assert result.code == "COMPARATOR_COLUMN_MISMATCH"


@pytest.mark.parametrize(
    ("predicted", "expected_pass"),
    [
        ("10.01", True),
        ("10.0101", False),
    ],
)
def test_decimal_absolute_tolerance_boundary_is_inclusive(
    predicted: str,
    expected_pass: bool,
) -> None:
    result = compare_results(
        _result([("amount", 1700)], [[predicted]]),
        _result([("amount", 1700)], [["10.00"]]),
        mode=ComparisonMode.MULTISET,
        order_sensitive=False,
        numeric_tolerances={
            "amount": NumericTolerance(
                absolute=Decimal("0.01"),
            )
        },
    )

    assert result.passed is expected_pass


def test_decimal_relative_tolerance_uses_gold_magnitude() -> None:
    result = compare_results(
        _result([("ratio", 1700)], [["101"]]),
        _result([("ratio", 1700)], [["100"]]),
        mode=ComparisonMode.MULTISET,
        order_sensitive=False,
        numeric_tolerances={
            "ratio": NumericTolerance(relative=Decimal("0.01"))
        },
    )

    assert result.passed is True


def test_numeric_tolerance_is_rejected_for_text_columns() -> None:
    result = compare_results(
        _result([("value", 25)], [["1"]]),
        _result([("value", 25)], [["2"]]),
        mode=ComparisonMode.MULTISET,
        order_sensitive=False,
        numeric_tolerances={
            "value": NumericTolerance(absolute=Decimal("1"))
        },
    )

    assert result.passed is False
    assert result.code == "COMPARATOR_INVALID_TOLERANCE"


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity"])
def test_non_finite_numeric_value_is_a_stable_mismatch(
    value: str,
) -> None:
    result = compare_results(
        _result([("amount", 1700)], [[value]]),
        _result([("amount", 1700)], [["10.00"]]),
        mode=ComparisonMode.MULTISET,
        order_sensitive=False,
        numeric_tolerances={
            "amount": NumericTolerance(absolute=Decimal("0.01"))
        },
    )

    assert result.passed is False
    assert result.code == "COMPARATOR_ROW_MISMATCH"


def test_float_requires_explicit_tolerance() -> None:
    result = compare_results(
        _result([("average", 701)], [[1.0]]),
        _result([("average", 701)], [[1.0]]),
        mode=ComparisonMode.MULTISET,
        order_sensitive=False,
        numeric_tolerances={},
    )

    assert result.passed is False
    assert result.code == "COMPARATOR_TOLERANCE_REQUIRED"


def test_timestamptz_values_compare_as_the_same_instant() -> None:
    result = compare_results(
        _result(
            [("created_at", 1184)],
            [["2026-01-01T08:00:00+08:00"]],
        ),
        _result(
            [("created_at", 1184)],
            [["2026-01-01T00:00:00+00:00"]],
        ),
        mode=ComparisonMode.MULTISET,
        order_sensitive=False,
        numeric_tolerances={},
    )

    assert result.passed is True


def test_keyed_mode_aligns_rows_by_unique_key() -> None:
    columns = [("id", 23), ("value", 25)]
    result = compare_results(
        _result(columns, [[2, "b"], [1, "a"]]),
        _result(columns, [[1, "a"], [2, "b"]]),
        mode=ComparisonMode.KEYED,
        order_sensitive=False,
        numeric_tolerances={},
        key_columns=("id",),
    )

    assert result.passed is True


def test_keyed_mode_rejects_duplicate_keys() -> None:
    columns = [("id", 23), ("value", 25)]
    result = compare_results(
        _result(columns, [[1, "a"], [1, "b"]]),
        _result(columns, [[1, "a"], [2, "b"]]),
        mode=ComparisonMode.KEYED,
        order_sensitive=False,
        numeric_tolerances={},
        key_columns=("id",),
    )

    assert result.passed is False
    assert result.code == "COMPARATOR_DUPLICATE_KEY"


def test_keyed_mode_normalizes_timestamptz_keys() -> None:
    columns = [("created_at", 1184), ("value", 25)]
    result = compare_results(
        _result(
            columns,
            [["2026-01-01T08:00:00+08:00", "same"]],
        ),
        _result(
            columns,
            [["2026-01-01T00:00:00+00:00", "same"]],
        ),
        mode=ComparisonMode.KEYED,
        order_sensitive=False,
        numeric_tolerances={},
        key_columns=("created_at",),
    )

    assert result.passed is True


def test_keyed_mode_rejects_logically_duplicate_timestamptz_keys() -> None:
    columns = [("created_at", 1184), ("value", 25)]
    result = compare_results(
        _result(
            columns,
            [
                ["2026-01-01T08:00:00+08:00", "a"],
                ["2026-01-01T00:00:00+00:00", "b"],
            ],
        ),
        _result(
            columns,
            [
                ["2026-01-01T00:00:00+00:00", "a"],
                ["2026-01-02T00:00:00+00:00", "b"],
            ],
        ),
        mode=ComparisonMode.KEYED,
        order_sensitive=False,
        numeric_tolerances={},
        key_columns=("created_at",),
    )

    assert result.passed is False
    assert result.code == "COMPARATOR_DUPLICATE_KEY"


def test_same_total_with_different_grain_fails() -> None:
    columns = [("group_id", 23), ("amount", 1700)]
    result = compare_results(
        _result(columns, [[1, "5"], [2, "5"]]),
        _result(columns, [[1, "10"]]),
        mode=ComparisonMode.MULTISET,
        order_sensitive=False,
        numeric_tolerances={},
    )

    assert result.passed is False
    assert result.code == "COMPARATOR_GRAIN_MISMATCH"


def test_legal_empty_results_compare_successfully() -> None:
    columns = [("film_id", 23)]
    result = compare_results(
        _result(columns, []),
        _result(columns, []),
        mode=ComparisonMode.MULTISET,
        order_sensitive=False,
        numeric_tolerances={},
    )

    assert result.passed is True
    assert result.predicted_row_count == 0
    assert result.gold_row_count == 0


def test_truncated_result_cannot_be_verified() -> None:
    result = compare_results(
        ExecutionResult(
            columns=(ResultColumn(name="film_id", type_oid=23),),
            rows=[[1]],
            returned_row_count=1,
            truncated=True,
            execution_time_ms=0.1,
        ),
        _result([("film_id", 23)], [[1]]),
        mode=ComparisonMode.MULTISET,
        order_sensitive=False,
        numeric_tolerances={},
    )

    assert result.passed is False
    assert result.code == "COMPARATOR_TRUNCATED_RESULT"
