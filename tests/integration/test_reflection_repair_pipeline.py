import json
from pathlib import Path

import pytest

from app.connectors.errors import ErrorType
from app.connectors.postgresql import PostgreSQLConnector
from app.execution import execute_validated_sql
from app.reflection import (
    ReflectionRoute,
    RepairRegistrationStatus,
    decide_reflection,
    record_execution,
    record_validation,
    register_repair_sql,
    start_attempt,
)
from app.schema_linking import link_schema
from app.validation import validate_sql


CASE_PATH = (
    Path(__file__).parents[2] / "evaluation/cases/pagila_mvp_all_draft.jsonl"
)


def _reflection_case() -> dict[str, object]:
    cases = [
        json.loads(line)
        for line in CASE_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    return next(
        case for case in cases if case["case_id"] == "PG-MVP-018"
    )


@pytest.mark.integration
def test_pagila_schema_error_is_repaired_and_reexecuted(
    connector: PostgreSQLConnector,
) -> None:
    case = _reflection_case()
    fixture = case["fixture"]
    assert isinstance(fixture, dict)
    initial_sql = fixture["initial_model_sql"]
    repaired_sql = case["gold_sql"]
    question = case["question"]
    assert isinstance(initial_sql, str)
    assert isinstance(repaired_sql, str)
    assert isinstance(question, str)
    allowed_schemas = ("public",)
    allowed_tables = ("public.film",)
    snapshot = connector.read_metadata(
        allowed_schemas,
        allowed_tables,
    )

    linking = link_schema(
        question,
        allowed_schemas=allowed_schemas,
        allowed_tables=allowed_tables,
        snapshot=snapshot,
        top_k=10,
    )
    assert "public.film" in {
        table.object_id for table in linking.candidate_tables
    }

    history = start_attempt(initial_sql)
    initial_validation = validate_sql(
        initial_sql,
        allowed_schemas=allowed_schemas,
        allowed_tables=allowed_tables,
        snapshot=snapshot,
    )
    history = record_validation(history, initial_validation)
    assert (
        history.current_attempt.current_error_type
        is ErrorType.SCHEMA_ERROR
    )

    decision = decide_reflection(
        ErrorType.SCHEMA_ERROR,
        repair_count=history.repair_count,
    )
    assert decision.route is ReflectionRoute.SCHEMA_LINKING

    relinked = link_schema(
        question,
        allowed_schemas=allowed_schemas,
        allowed_tables=allowed_tables,
        snapshot=snapshot,
        top_k=10,
    )
    assert relinked.schema_version == linking.schema_version

    registration = register_repair_sql(history, repaired_sql)
    assert registration.status is RepairRegistrationStatus.ACCEPTED
    history = registration.history
    repaired_validation = validate_sql(
        history.current_attempt.sql,
        allowed_schemas=allowed_schemas,
        allowed_tables=allowed_tables,
        snapshot=snapshot,
    )
    history = record_validation(history, repaired_validation)
    outcome = execute_validated_sql(
        repaired_validation,
        allowed_schemas=allowed_schemas,
        allowed_tables=allowed_tables,
        snapshot=snapshot,
        connector=connector,
    )
    history = record_execution(history, outcome)

    assert history.repair_count == 1
    assert len(history.attempts) == 2
    assert history.current_attempt.is_success is True
    assert history.current_attempt.execution_result is not None
    assert history.current_attempt.execution_result.returned_row_count == 1000


@pytest.mark.integration
def test_a_b_a_duplicate_stops_before_execution(
    connector: PostgreSQLConnector,
) -> None:
    allowed_schemas = ("public",)
    allowed_tables = ("public.film",)
    snapshot = connector.read_metadata(
        allowed_schemas,
        allowed_tables,
    )
    history = record_validation(
        start_attempt("SELECT missing_a FROM film"),
        validate_sql(
            "SELECT missing_a FROM film",
            allowed_schemas=allowed_schemas,
            allowed_tables=allowed_tables,
            snapshot=snapshot,
        ),
    )
    accepted = register_repair_sql(
        history,
        "SELECT missing_b FROM film",
    )
    history = record_validation(
        accepted.history,
        validate_sql(
            "SELECT missing_b FROM film",
            allowed_schemas=allowed_schemas,
            allowed_tables=allowed_tables,
            snapshot=snapshot,
        ),
    )

    duplicate = register_repair_sql(
        history,
        "select missing_a from film;",
    )

    assert duplicate.status is RepairRegistrationStatus.DUPLICATE
    assert duplicate.error_type is ErrorType.DUPLICATE_SQL
    assert duplicate.history.repair_count == 1
