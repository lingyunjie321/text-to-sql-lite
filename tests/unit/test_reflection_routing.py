import pytest

from app.connectors.errors import ErrorType
from app.reflection import (
    ReflectionDecision,
    ReflectionRoute,
    RepairStrategy,
    decide_reflection,
)


@pytest.mark.parametrize(
    ("error_type", "route", "strategy", "code"),
    [
        (
            ErrorType.SYNTAX_ERROR,
            ReflectionRoute.GENERATE_SQL,
            RepairStrategy.MINIMAL_SQL_REPAIR,
            "REFLECT_SYNTAX_REPAIR",
        ),
        (
            ErrorType.SCHEMA_ERROR,
            ReflectionRoute.SCHEMA_LINKING,
            RepairStrategy.RELINK_SCHEMA,
            "REFLECT_SCHEMA_RELINK",
        ),
        (
            ErrorType.DIALECT_ERROR,
            ReflectionRoute.GENERATE_SQL,
            RepairStrategy.REGENERATE_POSTGRES,
            "REFLECT_DIALECT_REGENERATE",
        ),
        (
            ErrorType.BUSINESS_KNOWLEDGE_MISSING,
            ReflectionRoute.CLARIFICATION,
            None,
            "REFLECT_CLARIFICATION",
        ),
        (
            ErrorType.AMBIGUOUS_SEMANTICS,
            ReflectionRoute.CLARIFICATION,
            None,
            "REFLECT_CLARIFICATION",
        ),
        (
            ErrorType.PERMISSION_DENIED,
            ReflectionRoute.FINALIZE,
            None,
            "REFLECT_NON_REPAIRABLE",
        ),
        (
            ErrorType.CONNECTION_ERROR,
            ReflectionRoute.FINALIZE,
            None,
            "REFLECT_NON_REPAIRABLE",
        ),
        (
            ErrorType.TIMEOUT,
            ReflectionRoute.FINALIZE,
            None,
            "REFLECT_NON_REPAIRABLE",
        ),
        (
            ErrorType.DUPLICATE_SQL,
            ReflectionRoute.FINALIZE,
            None,
            "REFLECT_NON_REPAIRABLE",
        ),
        (
            ErrorType.UNKNOWN,
            ReflectionRoute.FINALIZE,
            None,
            "REFLECT_NON_REPAIRABLE",
        ),
    ],
)
def test_error_type_has_one_deterministic_route(
    error_type: ErrorType,
    route: ReflectionRoute,
    strategy: RepairStrategy | None,
    code: str,
) -> None:
    decision = decide_reflection(error_type, repair_count=0)

    assert decision.error_type is error_type
    assert decision.route is route
    assert decision.strategy is strategy
    assert decision.code == code
    assert decision.should_repair is (strategy is not None)


def test_repair_budget_exhaustion_precedes_repair_route() -> None:
    for error_type in (
        ErrorType.SYNTAX_ERROR,
        ErrorType.SCHEMA_ERROR,
        ErrorType.DIALECT_ERROR,
    ):
        decision = decide_reflection(error_type, repair_count=3)

        assert decision.route is ReflectionRoute.FINALIZE
        assert decision.strategy is None
        assert decision.code == "REFLECT_REPAIR_EXHAUSTED"


def test_resource_risk_requires_explicit_safe_reduction() -> None:
    unsafe = decide_reflection(
        ErrorType.RESOURCE_RISK,
        repair_count=0,
    )
    safe = decide_reflection(
        ErrorType.RESOURCE_RISK,
        repair_count=0,
        can_reduce_resource=True,
    )

    assert unsafe.route is ReflectionRoute.FINALIZE
    assert unsafe.code == "REFLECT_RESOURCE_RISK"
    assert safe.route is ReflectionRoute.CLARIFICATION
    assert safe.code == "REFLECT_RESOURCE_CLARIFICATION"
    assert safe.strategy is None


@pytest.mark.parametrize("repair_count", [-1, 4, True])
def test_invalid_repair_count_is_rejected(repair_count: object) -> None:
    with pytest.raises(ValueError, match="reflection context is invalid"):
        decide_reflection(
            ErrorType.SCHEMA_ERROR,
            repair_count=repair_count,  # type: ignore[arg-type]
        )


def test_non_repairable_error_rejects_repair_strategy() -> None:
    with pytest.raises(ValueError, match="reflection decision is invalid"):
        ReflectionDecision(
            error_type=ErrorType.PERMISSION_DENIED,
            route=ReflectionRoute.GENERATE_SQL,
            strategy=RepairStrategy.MINIMAL_SQL_REPAIR,
            code="REFLECT_SYNTAX_REPAIR",
        )
