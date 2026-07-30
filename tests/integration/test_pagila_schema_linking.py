import json
from pathlib import Path

import pytest

from app.connectors.postgresql import PostgreSQLConnector
from app.schema_linking import link_schema


CASE_PATH = Path("evaluation/cases/pagila_mvp.jsonl")
LINKING_CASE_IDS = {
    *(f"PG-MVP-{index:03d}" for index in range(1, 15)),
    "PG-MVP-018",
}
KNOWN_PARTITION_PARENT_EDGE_GAP = {
    frozenset(
        (
            "public.customer.customer_id",
            "public.payment.customer_id",
        )
    )
}


def _load_linking_cases() -> list[dict[str, object]]:
    return [
        case
        for line in CASE_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
        for case in (json.loads(line),)
        if case["case_id"] in LINKING_CASE_IDS
    ]


@pytest.mark.integration
@pytest.mark.parametrize(
    "case",
    _load_linking_cases(),
    ids=lambda case: str(case["case_id"]),
)
def test_pagila_gold_tables_and_fields_are_recalled_within_authorization(
    connector: PostgreSQLConnector,
    case: dict[str, object],
) -> None:
    allowed_tables = tuple(
        f"public.{table_name}"
        for table_name in case["allowed_tables"]
    )
    snapshot = connector.read_metadata(("public",), allowed_tables)

    result = link_schema(
        str(case["question"]),
        allowed_schemas=("public",),
        allowed_tables=allowed_tables,
        snapshot=snapshot,
        top_k=20,
    )

    candidate_tables = {
        table.object_id for table in result.candidate_tables
    }
    candidate_fields = {
        field.object_id for field in result.candidate_fields
    }
    expected_tables = {
        f"public.{table_name}" for table_name in case["gold_tables"]
    }
    expected_fields = {
        f"public.{field_name}" for field_name in case["gold_fields"]
    }
    snapshot_edges = {
        (
            foreign_key.constraint_name,
            (
                f"{foreign_key.source_schema}."
                f"{foreign_key.source_table}"
            ),
            foreign_key.source_columns,
            (
                f"{foreign_key.target_schema}."
                f"{foreign_key.target_table}"
            ),
            foreign_key.target_columns,
        )
        for foreign_key in snapshot.foreign_keys
    }
    snapshot_join_edges = {
        frozenset(
            (
                (
                    f"{foreign_key.source_schema}."
                    f"{foreign_key.source_table}.{source_column}"
                ),
                (
                    f"{foreign_key.target_schema}."
                    f"{foreign_key.target_table}.{target_column}"
                ),
            )
        )
        for foreign_key in snapshot.foreign_keys
        for source_column, target_column in zip(
            foreign_key.source_columns,
            foreign_key.target_columns,
            strict=True,
        )
    }
    emitted_join_edges = {
        frozenset(
            (
                f"{edge.source_table}.{source_column}",
                f"{edge.target_table}.{target_column}",
            )
        )
        for path in result.join_paths
        for edge in path.edges
        for source_column, target_column in zip(
            edge.source_columns,
            edge.target_columns,
            strict=True,
        )
    }
    expected_join_edges = {
        frozenset(
            (
                f"public.{left_endpoint}",
                f"public.{right_endpoint}",
            )
        )
        for gold_edge in case["gold_join_edges"]
        for left_endpoint, right_endpoint in (
            str(gold_edge).split("=", 1),
        )
    }

    assert expected_tables.issubset(candidate_tables)
    assert expected_fields.issubset(candidate_fields)
    assert candidate_tables.issubset(allowed_tables)
    assert len(candidate_tables) <= 20
    assert result.top_k == 20
    missing_snapshot_edges = expected_join_edges - snapshot_join_edges
    assert missing_snapshot_edges.issubset(
        KNOWN_PARTITION_PARENT_EDGE_GAP
    )
    assert (
        expected_join_edges & snapshot_join_edges
    ).issubset(emitted_join_edges)
    assert all(
        (
            edge.constraint_name,
            edge.source_table,
            edge.source_columns,
            edge.target_table,
            edge.target_columns,
        )
        in snapshot_edges
        for path in result.join_paths
        for edge in path.edges
    )
