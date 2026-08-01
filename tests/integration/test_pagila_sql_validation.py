import json
from pathlib import Path

import pytest

from app.connectors.errors import ErrorType
from app.connectors.postgresql import PostgreSQLConnector
from app.validation import validate_sql


CASE_PATH = Path("evaluation/cases/pagila_mvp_all_draft.jsonl")


def _load_cases() -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in CASE_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


CASES = _load_cases()
CASE_BY_ID = {
    str(case["case_id"]): case
    for case in CASES
}
ALLOWED_CASES = [
    case
    for case in CASES
    if case["case_id"]
    in {
        *(f"PG-MVP-{index:03d}" for index in range(1, 15)),
        "PG-MVP-018",
    }
]


@pytest.mark.integration
@pytest.mark.parametrize(
    "case",
    ALLOWED_CASES,
    ids=lambda case: str(case["case_id"]),
)
def test_pagila_gold_sql_passes_authorized_validation(
    connector: PostgreSQLConnector,
    case: dict[str, object],
) -> None:
    allowed_tables = tuple(
        f"public.{table_name}"
        for table_name in case["allowed_tables"]
    )
    snapshot = connector.read_metadata(("public",), allowed_tables)

    result = validate_sql(
        str(case["gold_sql"]),
        allowed_schemas=("public",),
        allowed_tables=allowed_tables,
        snapshot=snapshot,
    )

    assert result.is_valid, result.issue
    assert set(result.referenced_tables).issubset(allowed_tables)
    snapshot_columns = {
        f"{column.schema_name}.{column.table_name}.{column.column_name}"
        for table in snapshot.tables
        for column in table.columns
    }
    assert set(result.referenced_columns).issubset(snapshot_columns)


@pytest.mark.integration
@pytest.mark.parametrize(
    ("case_id", "expected_code"),
    [
        ("PG-MVP-016", "SQL_NOT_READ_ONLY"),
        ("PG-MVP-017", "SQL_MULTIPLE_STATEMENTS"),
    ],
)
def test_pagila_dangerous_model_sql_is_rejected(
    connector: PostgreSQLConnector,
    case_id: str,
    expected_code: str,
) -> None:
    case = CASE_BY_ID[case_id]
    allowed_tables = tuple(
        f"public.{table_name}"
        for table_name in case["allowed_tables"]
    )
    snapshot = connector.read_metadata(("public",), allowed_tables)
    fixture = case["fixture"]
    assert isinstance(fixture, dict)

    result = validate_sql(
        str(fixture["model_sql"]),
        allowed_schemas=("public",),
        allowed_tables=allowed_tables,
        snapshot=snapshot,
    )

    assert result.is_valid is False
    assert result.normalized_sql is None
    assert result.referenced_tables == ()
    assert result.referenced_columns == ()
    assert result.issue is not None
    assert result.issue.error_type is ErrorType.PERMISSION_DENIED
    assert result.issue.code == expected_code


@pytest.mark.integration
def test_pagila_permission_case_cannot_enumerate_staff(
    connector: PostgreSQLConnector,
) -> None:
    snapshot = connector.read_metadata(
        ("public",),
        ("public.film",),
    )

    result = validate_sql(
        "SELECT username, email FROM staff",
        allowed_schemas=("public",),
        allowed_tables=("public.film",),
        snapshot=snapshot,
    )

    assert result.is_valid is False
    assert result.normalized_sql is None
    assert result.referenced_tables == ()
    assert result.referenced_columns == ()
    assert result.issue is not None
    assert result.issue.error_type is ErrorType.PERMISSION_DENIED
    assert result.issue.code == "SQL_OBJECT_NOT_ALLOWED"
    assert "staff" not in result.issue.public_message.lower()
