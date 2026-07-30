from pathlib import Path

from evaluation.loader import load_retrieval_routing_suites


DEVELOPMENT_PATH = Path(
    "evaluation/cases/retrieval_routing_development.jsonl"
)
CALIBRATION_PATH = Path(
    "evaluation/cases/retrieval_routing_calibration.jsonl"
)


def _suites():
    return load_retrieval_routing_suites(
        DEVELOPMENT_PATH,
        CALIBRATION_PATH,
    )


def test_synthetic_snapshot_covers_every_suite_object_and_fk() -> None:
    from evaluation.stage1_synthetic import (
        build_stage1_synthetic_snapshot,
        validate_stage1_synthetic_suite,
    )

    suites = _suites()
    snapshot = build_stage1_synthetic_snapshot()
    table_by_id = {
        f"{table.schema_name}.{table.table_name}": table
        for table in snapshot.tables
    }
    field_by_id = {
        (
            f"{table.schema_name}.{table.table_name}."
            f"{column.column_name}"
        ): column
        for table in snapshot.tables
        for column in table.columns
    }
    fk_edges = {
        frozenset(
            (
                (
                    f"{foreign_key.source_schema}."
                    f"{foreign_key.source_table}.{source}"
                ),
                (
                    f"{foreign_key.target_schema}."
                    f"{foreign_key.target_table}.{target}"
                ),
            )
        )
        for foreign_key in snapshot.foreign_keys
        for source, target in zip(
            foreign_key.source_columns,
            foreign_key.target_columns,
            strict=True,
        )
    }

    assert set(snapshot.schemas) == {
        "synthetic/rrdev",
        "synthetic/rrcal",
    }
    assert all(table.comment and table.aliases for table in snapshot.tables)
    assert all(
        column.comment and column.aliases
        for table in snapshot.tables
        for column in table.columns
    )
    for suite in (suites.development, suites.calibration):
        validate_stage1_synthetic_suite(suite)
        for case in suite.cases:
            assert set(case.allowed_tables).issubset(table_by_id)
            assert set(case.expected_fields).issubset(field_by_id)
            for edge in case.expected_join_edges:
                assert frozenset(edge.split("=", 1)) in fk_edges


def test_synthetic_retrieval_reaches_every_declared_complexity() -> None:
    from app.schema_linking import link_schema
    from app.workflow.complexity import decide_complexity
    from evaluation.stage1_synthetic import (
        Stage1SyntheticConnector,
        build_stage1_synthetic_retrieval_runtime,
    )

    suites = _suites()
    connector = Stage1SyntheticConnector()
    runtime = build_stage1_synthetic_retrieval_runtime()

    for suite in (suites.development, suites.calibration):
        for case in suite.cases:
            snapshot = connector.read_metadata(
                (case.namespace,),
                case.allowed_tables,
            )
            linking = link_schema(
                case.question,
                datasource_id="synthetic",
                allowed_schemas=(case.namespace,),
                allowed_tables=case.allowed_tables,
                snapshot=snapshot,
                top_k=20,
                retrieval_runtime=runtime,
            )
            decision = decide_complexity(
                case.question,
                candidate_tables=linking.candidate_tables,
                join_paths=linking.join_paths,
                has_repair_history=False,
            )

            assert decision.level.value == (
                case.expected_complexity.value
            )
            assert decision.schema_top_k == case.expected_top_k

    medium_positive_tables = {
        "RRDEV-003": {
            "synthetic/rrdev.rover_mission",
        },
        "RRCAL-003": {
            "synthetic/rrcal.drone_flight",
        },
    }
    for suite in (suites.development, suites.calibration):
        case = next(
            item
            for item in suite.cases
            if item.case_id in medium_positive_tables
        )
        snapshot = connector.read_metadata(
            (case.namespace,),
            case.allowed_tables,
        )
        linking = link_schema(
            case.question,
            datasource_id="synthetic",
            allowed_schemas=(case.namespace,),
            allowed_tables=case.allowed_tables,
            snapshot=snapshot,
            top_k=20,
            retrieval_runtime=runtime,
        )
        assert {
            table.object_id
            for table in linking.candidate_tables
            if table.score > 0
        } == medium_positive_tables[case.case_id]


def test_synthetic_embedding_and_generation_are_deterministic() -> None:
    from app.generation import LLMMessage
    from evaluation.stage1_synthetic import (
        Stage1SyntheticEmbeddingProvider,
        Stage1SyntheticGenerationProvider,
    )

    suites = _suites()
    case = suites.development.cases[0]
    embedding = Stage1SyntheticEmbeddingProvider()
    inputs = (
        case.question,
        (
            '{"kind":"table","object_id":'
            '"synthetic/rrdev.weather_beacon"}'
        ),
    )

    assert embedding.embed(inputs) == embedding.embed(inputs)

    generation = Stage1SyntheticGenerationProvider()
    messages = (
        LLMMessage(role="system", content="fixed-system-contract"),
        LLMMessage(
            role="user",
            content=(
                '{"question":'
                f'"{case.question}"'
                "}"
            ),
        ),
    )
    first = generation.generate(messages)
    second = generation.generate(messages)

    assert first == second
    assert first.output.sql is not None
    assert "synthetic/rrdev" in first.output.sql
    assert first.output.clarification_reason is None


def test_synthetic_fixture_contains_no_pagila_namespace() -> None:
    from evaluation.stage1_synthetic import (
        build_stage1_synthetic_snapshot,
    )

    snapshot = build_stage1_synthetic_snapshot()
    assert all(
        table.schema_name.startswith("synthetic/rr")
        for table in snapshot.tables
    )
    assert all(
        not table.schema_name.startswith("public")
        for table in snapshot.tables
    )
