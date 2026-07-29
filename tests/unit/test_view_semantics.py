import pytest

from app.connectors.metadata import (
    ColumnMetadata,
    TableMetadata,
    build_schema_snapshot,
)
from app.connectors.view_semantics import (
    SemanticPolarity,
    SemanticRule,
    ViewDefinitionInput,
    ViewSemanticEntry,
    build_view_semantic_manifest,
    build_view_semantic_review,
    enrich_schema_snapshot,
    extract_view_semantic_candidates,
    review_semantic_candidate,
    validate_view_semantic_manifest,
)


SCHEMA_SHA256 = "1" * 64


def _table(
    name: str,
    *columns: tuple[str, str],
) -> TableMetadata:
    return TableMetadata(
        schema_name="public",
        table_name=name,
        relation_kind="table",
        comment=None,
        columns=tuple(
            ColumnMetadata(
                schema_name="public",
                table_name=name,
                column_name=column_name,
                ordinal_position=position,
                data_type=data_type,
                formatted_type=data_type,
                nullable=False,
                comment=None,
            )
            for position, (column_name, data_type) in enumerate(
                columns,
                start=1,
            )
        ),
    )


ASSET = _table(
    "asset",
    ("asset_id", "integer"),
    ("is_archived", "boolean"),
)
OWNER = _table(
    "owner",
    ("owner_id", "integer"),
    ("is_enabled", "boolean"),
)
SNAPSHOT = build_schema_snapshot(
    tables=(ASSET, OWNER),
    primary_keys=(),
    foreign_keys=(),
    unique_constraints=(),
    unique_indexes=(),
)
ALLOWED_TABLES = ("public.asset", "public.owner")


def _extract(sql: str):
    return extract_view_semantic_candidates(
        (
            ViewDefinitionInput(
                schema_name="public",
                view_name="asset_directory",
                sql=sql,
            ),
        ),
        snapshot=SNAPSHOT,
        allowed_schemas=("public",),
        allowed_tables=ALLOWED_TABLES,
        database_schema_sha256=SCHEMA_SHA256,
    )


def test_extracts_generic_direct_and_boolean_case_aliases() -> None:
    ledger = _extract(
        "SELECT a.asset_id AS record_key, "
        "CASE WHEN a.is_archived THEN 'retired' ELSE '' END "
        "AS lifecycle_note "
        "FROM public.asset AS a"
    )

    assert [
        (
            item.object_id,
            item.alias,
            item.rule,
            item.polarity,
        )
        for item in ledger.candidates
    ] == [
        (
            "public.asset.asset_id",
            "record_key",
            SemanticRule.DIRECT_PROJECTION_ALIAS,
            SemanticPolarity.NONE,
        ),
        (
            "public.asset.is_archived",
            "retired",
            SemanticRule.SIMPLE_BOOLEAN_CASE_LABEL,
            SemanticPolarity.TRUE,
        ),
    ]
    assert ledger.base_schema_version == SNAPSHOT.schema_version
    assert ledger.database_schema_sha256 == SCHEMA_SHA256


def test_extracts_string_labels_with_explicit_text_casts() -> None:
    ledger = _extract(
        "SELECT CASE WHEN a.is_archived "
        "THEN 'retired'::text ELSE ''::text END AS lifecycle_note "
        "FROM public.asset AS a"
    )

    assert [
        (
            item.object_id,
            item.alias,
            item.rule,
            item.polarity,
        )
        for item in ledger.candidates
    ] == [
        (
            "public.asset.is_archived",
            "retired",
            SemanticRule.SIMPLE_BOOLEAN_CASE_LABEL,
            SemanticPolarity.TRUE,
        ),
    ]


@pytest.mark.parametrize(
    ("predicate", "expected"),
    [
        ("a.is_archived IS TRUE", SemanticPolarity.TRUE),
        ("a.is_archived IS FALSE", SemanticPolarity.FALSE),
    ],
)
def test_explicit_boolean_case_predicates_preserve_polarity(
    predicate: str,
    expected: SemanticPolarity,
) -> None:
    ledger = _extract(
        f"SELECT CASE WHEN {predicate} "
        "THEN 'retired' ELSE '' END AS note "
        "FROM public.asset AS a"
    )

    assert len(ledger.candidates) == 1
    assert ledger.candidates[0].polarity is expected


def test_approved_candidates_enrich_only_existing_fields() -> None:
    ledger = _extract(
        "SELECT a.asset_id AS record_key, "
        "CASE WHEN a.is_archived THEN 'retired' ELSE '' END "
        "AS lifecycle_note "
        "FROM public.asset AS a"
    )
    review = build_view_semantic_review(
        ledger,
        tuple(
            review_semantic_candidate(candidate, approved=True)
            for candidate in ledger.candidates
        ),
    )
    manifest = build_view_semantic_manifest(
        ledger,
        review,
        snapshot=SNAPSHOT,
        datasource_id="synthetic",
    )

    enriched = enrich_schema_snapshot(SNAPSHOT, manifest)
    asset = next(
        table for table in enriched.tables if table.table_name == "asset"
    )
    aliases = {
        column.column_name: column.aliases
        for column in asset.columns
    }

    assert aliases == {
        "asset_id": ("record_key",),
        "is_archived": ("retired",),
    }
    assert enriched.schema_version == manifest.enriched_schema_version
    assert enriched.schema_version != SNAPSHOT.schema_version


def test_rejected_candidate_never_enters_manifest() -> None:
    ledger = _extract(
        "SELECT CASE WHEN a.is_archived "
        "THEN 'patient_positive' ELSE '' END AS note "
        "FROM public.asset AS a"
    )
    assert [item.alias for item in ledger.candidates] == [
        "patient_positive"
    ]
    review = build_view_semantic_review(
        ledger,
        (
            review_semantic_candidate(
                ledger.candidates[0],
                approved=False,
            ),
        ),
    )

    manifest = build_view_semantic_manifest(
        ledger,
        review,
        snapshot=SNAPSHOT,
        datasource_id="synthetic",
    )

    assert manifest.entries == ()
    assert "patient_positive" not in manifest.model_dump_json()


def test_manifest_requires_a_decision_for_every_candidate() -> None:
    ledger = _extract(
        "SELECT a.asset_id AS record_key, "
        "CASE WHEN a.is_archived THEN 'retired' ELSE '' END AS note "
        "FROM public.asset AS a"
    )
    review = build_view_semantic_review(
        ledger,
        (
            review_semantic_candidate(
                ledger.candidates[0],
                approved=True,
            ),
        ),
        require_complete=False,
    )

    with pytest.raises(ValueError, match="review"):
        build_view_semantic_manifest(
            ledger,
            review,
            snapshot=SNAPSHOT,
            datasource_id="synthetic",
        )


def test_manifest_rejects_stale_review_digest() -> None:
    ledger = _extract(
        "SELECT a.asset_id AS record_key FROM public.asset AS a"
    )
    decision = review_semantic_candidate(
        ledger.candidates[0],
        approved=True,
    )
    stale = decision.model_copy(
        update={"review_sha256": "0" * 64}
    )

    with pytest.raises(ValueError, match="review"):
        build_view_semantic_review(ledger, (stale,))


@pytest.mark.parametrize(
    "sql",
    [
        (
            "SELECT CASE WHEN is_archived THEN 'retired' ELSE '' END "
            "AS note FROM public.asset AS a"
        ),
        (
            "SELECT CASE WHEN NOT a.is_archived THEN 'retired' ELSE '' "
            "END AS note FROM public.asset AS a"
        ),
        (
            "SELECT CASE WHEN COALESCE(a.is_archived, false) "
            "THEN 'retired' ELSE '' END AS note "
            "FROM public.asset AS a"
        ),
        (
            "SELECT CASE WHEN a.asset_id = 1 THEN 'retired' ELSE '' END "
            "AS note FROM public.asset AS a"
        ),
        (
            "SELECT CASE WHEN a.is_archived AND o.is_enabled "
            "THEN 'retired' ELSE '' END AS note "
            "FROM public.asset AS a "
            "JOIN public.owner AS o ON o.owner_id = a.asset_id"
        ),
        "SELECT * FROM public.asset AS a",
        (
            "WITH chosen AS (SELECT * FROM public.asset) "
            "SELECT chosen.asset_id AS record_key FROM chosen"
        ),
        (
            "SELECT a.asset_id AS record_key FROM public.asset AS a; "
            "SELECT 1"
        ),
        "SELECT FROM",
    ],
)
def test_unsupported_or_ambiguous_views_fail_closed(sql: str) -> None:
    assert _extract(sql).candidates == ()


def test_any_unauthorized_dependency_rejects_the_entire_view() -> None:
    ledger = extract_view_semantic_candidates(
        (
            ViewDefinitionInput(
                schema_name="public",
                view_name="mixed_directory",
                sql=(
                    "SELECT a.asset_id AS record_key "
                    "FROM public.asset AS a "
                    "JOIN private.payroll AS p "
                    "ON p.owner_id = a.asset_id"
                ),
            ),
        ),
        snapshot=SNAPSHOT,
        allowed_schemas=("public",),
        allowed_tables=ALLOWED_TABLES,
        database_schema_sha256=SCHEMA_SHA256,
    )

    assert ledger.candidates == ()
    assert "payroll" not in ledger.model_dump_json()


def test_conflicting_aliases_are_removed_for_every_field() -> None:
    ledger = extract_view_semantic_candidates(
        (
            ViewDefinitionInput(
                schema_name="public",
                view_name="asset_directory",
                sql=(
                    "SELECT a.asset_id AS record_key "
                    "FROM public.asset AS a"
                ),
            ),
            ViewDefinitionInput(
                schema_name="public",
                view_name="owner_directory",
                sql=(
                    "SELECT o.owner_id AS record_key "
                    "FROM public.owner AS o"
                ),
            ),
        ),
        snapshot=SNAPSHOT,
        allowed_schemas=("public",),
        allowed_tables=ALLOWED_TABLES,
        database_schema_sha256=SCHEMA_SHA256,
    )

    assert ledger.candidates == ()


def test_manifest_aggregates_duplicate_authoritative_sources() -> None:
    ledger = extract_view_semantic_candidates(
        (
            ViewDefinitionInput(
                schema_name="public",
                view_name="first_asset_directory",
                sql=(
                    "SELECT a.asset_id AS record_key "
                    "FROM public.asset AS a"
                ),
            ),
            ViewDefinitionInput(
                schema_name="public",
                view_name="second_asset_directory",
                sql=(
                    "SELECT a.asset_id AS record_key "
                    "FROM public.asset AS a WHERE a.asset_id > 0"
                ),
            ),
        ),
        snapshot=SNAPSHOT,
        allowed_schemas=("public",),
        allowed_tables=ALLOWED_TABLES,
        database_schema_sha256=SCHEMA_SHA256,
    )
    assert len(ledger.candidates) == 2
    review = build_view_semantic_review(
        ledger,
        tuple(
            review_semantic_candidate(candidate, approved=True)
            for candidate in ledger.candidates
        ),
    )

    manifest = build_view_semantic_manifest(
        ledger,
        review,
        snapshot=SNAPSHOT,
        datasource_id="synthetic",
    )

    assert len(manifest.entries) == 1
    assert manifest.entries[0].object_id == "public.asset.asset_id"
    assert manifest.entries[0].alias == "record_key"


def test_runtime_manifest_rejects_unknown_authorized_object() -> None:
    ledger = _extract(
        "SELECT a.asset_id AS record_key FROM public.asset AS a"
    )
    review = build_view_semantic_review(
        ledger,
        (
            review_semantic_candidate(
                ledger.candidates[0],
                approved=True,
            ),
        ),
    )
    manifest = build_view_semantic_manifest(
        ledger,
        review,
        snapshot=SNAPSHOT,
        datasource_id="synthetic",
    )
    forged = ViewSemanticEntry(
        object_id="public.asset.missing_column",
        alias="phantom",
        rule=SemanticRule.DIRECT_PROJECTION_ALIAS,
        polarity=SemanticPolarity.NONE,
        source_definition_set_sha256="1" * 64,
        approved_evidence_set_sha256="2" * 64,
        approved_review_set_sha256="3" * 64,
    )
    tampered = manifest.model_copy(
        update={"entries": (*manifest.entries, forged)}
    )

    with pytest.raises(ValueError, match="manifest"):
        validate_view_semantic_manifest(
            tampered,
            snapshot=SNAPSHOT,
            datasource_id="synthetic",
            database_schema_sha256=SCHEMA_SHA256,
            allowed_schemas=("public",),
            allowed_tables=ALLOWED_TABLES,
        )
