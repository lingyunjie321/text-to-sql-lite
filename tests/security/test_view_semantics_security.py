import pytest

from app.connectors.metadata import (
    ColumnMetadata,
    TableMetadata,
    build_schema_snapshot,
)
from app.connectors.view_semantics import (
    ViewDefinitionInput,
    build_view_semantic_manifest,
    build_view_semantic_review,
    extract_view_semantic_candidates,
    review_semantic_candidate,
)


def _snapshot():
    table = TableMetadata(
        schema_name="public",
        table_name="asset",
        relation_kind="table",
        comment=None,
        columns=(
            ColumnMetadata(
                schema_name="public",
                table_name="asset",
                column_name="is_archived",
                ordinal_position=1,
                data_type="boolean",
                formatted_type="boolean",
                nullable=False,
                comment=None,
            ),
        ),
    )
    return build_schema_snapshot(
        tables=(table,),
        primary_keys=(),
        foreign_keys=(),
        unique_constraints=(),
        unique_indexes=(),
    )


def _extract(label: str):
    snapshot = _snapshot()
    definition = ViewDefinitionInput(
        schema_name="public",
        view_name="sensitive_internal_view",
        sql=(
            "SELECT CASE WHEN a.is_archived "
            f"THEN '{label}' ELSE '' END AS note "
            "FROM public.asset AS a"
        ),
    )
    return definition, extract_view_semantic_candidates(
        (definition,),
        snapshot=snapshot,
        allowed_schemas=("public",),
        allowed_tables=("public.asset",),
        database_schema_sha256="2" * 64,
    )


def test_raw_view_sql_and_view_name_are_never_serialized_or_represented() -> None:
    definition, ledger = _extract("retired")
    serialized = ledger.model_dump_json()

    assert "sensitive_internal_view" not in repr(definition)
    assert "SELECT CASE" not in repr(definition)
    assert "sensitive_internal_view" not in serialized
    assert "SELECT CASE" not in serialized
    assert "FROM public.asset" not in serialized


@pytest.mark.parametrize(
    "label",
    [
        "ceo@example.com",
        "https://internal.example/path",
        "123456789",
        "contains private free text",
        "x" * 64,
        "api_key_sk_secret",
        "line\\nbreak",
    ],
)
def test_unsafe_label_shapes_never_become_candidates(
    label: str,
) -> None:
    _, ledger = _extract(label)

    assert ledger.candidates == ()
    assert label not in ledger.model_dump_json()


@pytest.mark.parametrize(
    "label_expression",
    [
        "UPPER('retired')",
        "CAST('retired' AS integer)",
        "'retired'::bytea",
        "('retired' || '_state')::text",
    ],
)
def test_only_literal_text_casts_can_supply_case_labels(
    label_expression: str,
) -> None:
    snapshot = _snapshot()
    definition = ViewDefinitionInput(
        schema_name="public",
        view_name="synthetic_directory",
        sql=(
            "SELECT CASE WHEN a.is_archived "
            f"THEN {label_expression} ELSE '' END AS note "
            "FROM public.asset AS a"
        ),
    )
    ledger = extract_view_semantic_candidates(
        (definition,),
        snapshot=snapshot,
        allowed_schemas=("public",),
        allowed_tables=("public.asset",),
        database_schema_sha256="2" * 64,
    )

    assert ledger.candidates == ()


def test_rejected_sensitive_candidate_never_enters_runtime_manifest() -> None:
    snapshot = _snapshot()
    _, ledger = _extract("patient_positive")
    decision = review_semantic_candidate(
        ledger.candidates[0],
        approved=False,
    )
    review = build_view_semantic_review(ledger, (decision,))
    manifest = build_view_semantic_manifest(
        ledger,
        review,
        snapshot=snapshot,
        datasource_id="synthetic",
    )
    serialized = manifest.model_dump_json()

    assert "patient_positive" not in serialized
    assert manifest.entries == ()


def test_manifest_cannot_approve_a_candidate_with_forged_evidence() -> None:
    snapshot = _snapshot()
    _, first = _extract("retired")
    _, second = _extract("archived")
    forged = review_semantic_candidate(
        second.candidates[0],
        approved=True,
    )

    with pytest.raises(ValueError, match="review"):
        build_view_semantic_review(first, (forged,))

    assert snapshot.schema_version == first.base_schema_version
