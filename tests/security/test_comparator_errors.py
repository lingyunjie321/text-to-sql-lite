from app.connectors.models import ExecutionResult, ResultColumn
from evaluation import ComparisonMode
from evaluation.comparator import compare_results


def _result(value: object) -> ExecutionResult:
    return ExecutionResult(
        columns=(ResultColumn(name="value", type_oid=25),),
        rows=[[value]],  # type: ignore[list-item]
        returned_row_count=1,
        truncated=False,
        execution_time_ms=0.1,
    )


def test_comparator_failure_does_not_echo_values() -> None:
    predicted_secret = "postgresql://reader:secret@db/pagila"
    gold_secret = "private-gold-value"

    result = compare_results(
        _result(predicted_secret),
        _result(gold_secret),
        mode=ComparisonMode.MULTISET,
        order_sensitive=False,
        numeric_tolerances={},
    )

    rendered = result.model_dump_json()
    assert result.passed is False
    assert predicted_secret not in rendered
    assert gold_secret not in rendered
    assert "secret" not in rendered


def test_none_mode_never_compares_result_values() -> None:
    result = compare_results(
        _result("predicted"),
        _result("gold"),
        mode=ComparisonMode.NONE,
        order_sensitive=False,
        numeric_tolerances={},
    )

    assert result.passed is False
    assert result.code == "COMPARATOR_NOT_APPLICABLE"
