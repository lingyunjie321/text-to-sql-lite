from contextlib import contextmanager
import hashlib
import json
from pathlib import Path

import pytest

from app.connectors.metadata import (
    ColumnMetadata,
    TableMetadata,
    build_schema_snapshot,
)
from app.connectors.models import ExecutionResult
from app.connectors.view_semantics import (
    FrozenSemanticConnector,
    ViewDefinitionInput,
    build_view_semantic_manifest,
    build_view_semantic_review,
    extract_view_semantic_candidates,
    load_view_semantic_manifest,
    review_semantic_candidate,
)


def _table(name: str, column: str, data_type: str):
    return TableMetadata(
        schema_name="public",
        table_name=name,
        relation_kind="table",
        comment=None,
        columns=(
            ColumnMetadata(
                schema_name="public",
                table_name=name,
                column_name=column,
                ordinal_position=1,
                data_type=data_type,
                formatted_type=data_type,
                nullable=False,
                comment=None,
            ),
        ),
    )


ASSET = _table("asset", "is_archived", "boolean")
OWNER = _table("owner", "owner_id", "integer")
FULL_SNAPSHOT = build_schema_snapshot(
    tables=(ASSET, OWNER),
    primary_keys=(),
    foreign_keys=(),
    unique_constraints=(),
    unique_indexes=(),
)


def _manifest():
    ledger = extract_view_semantic_candidates(
        (
            ViewDefinitionInput(
                schema_name="public",
                view_name="asset_directory",
                sql=(
                    "SELECT CASE WHEN a.is_archived "
                    "THEN 'retired' ELSE '' END AS note "
                    "FROM public.asset AS a"
                ),
            ),
        ),
        snapshot=FULL_SNAPSHOT,
        allowed_schemas=("public",),
        allowed_tables=("public.asset", "public.owner"),
        database_schema_sha256="5" * 64,
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
    return build_view_semantic_manifest(
        ledger,
        review,
        snapshot=FULL_SNAPSHOT,
        datasource_id="synthetic",
    )


class Delegate:
    def __init__(self) -> None:
        self.execute_calls = 0
        self.snapshot_enters = 0
        self.retry_count = 2

    def read_metadata(
        self,
        allowed_schemas: tuple[str, ...],
        allowed_tables: tuple[str, ...],
    ):
        del allowed_schemas
        allowed = set(allowed_tables)
        return build_schema_snapshot(
            tables=tuple(
                table
                for table in FULL_SNAPSHOT.tables
                if f"public.{table.table_name}" in allowed
            ),
            primary_keys=(),
            foreign_keys=(),
            unique_constraints=(),
            unique_indexes=(),
        )

    def execute(self, sql: str) -> ExecutionResult:
        del sql
        self.execute_calls += 1
        return ExecutionResult(
            columns=(),
            rows=[],
            returned_row_count=0,
            truncated=False,
            execution_time_ms=0,
        )

    def _consume_retry_count(self) -> int:
        value = self.retry_count
        self.retry_count = 0
        return value

    @contextmanager
    def read_only_snapshot(self):
        self.snapshot_enters += 1
        yield self


def test_wrapper_filters_semantics_to_request_metadata_scope() -> None:
    wrapper = FrozenSemanticConnector(Delegate(), _manifest())

    asset = wrapper.read_metadata(
        ("public",),
        ("public.asset",),
    )
    owner = wrapper.read_metadata(
        ("public",),
        ("public.owner",),
    )

    assert asset.tables[0].columns[0].aliases == ("retired",)
    assert owner.tables[0].columns[0].aliases == ()
    assert "asset" not in owner.schema_version


def test_wrapper_rejects_delegate_metadata_outside_request_scope() -> None:
    class LeakyDelegate(Delegate):
        def read_metadata(
            self,
            allowed_schemas: tuple[str, ...],
            allowed_tables: tuple[str, ...],
        ):
            del allowed_schemas, allowed_tables
            return FULL_SNAPSHOT

    wrapper = FrozenSemanticConnector(LeakyDelegate(), _manifest())

    with pytest.raises(ValueError, match="semantic connector"):
        wrapper.read_metadata(
            ("public",),
            ("public.asset",),
        )


def test_wrapper_delegates_execution_and_retry_accounting() -> None:
    delegate = Delegate()
    wrapper = FrozenSemanticConnector(delegate, _manifest())

    result = wrapper.execute("SELECT 1")

    assert result.returned_row_count == 0
    assert delegate.execute_calls == 1
    assert wrapper._consume_retry_count() == 2
    assert wrapper._consume_retry_count() == 0


def test_wrapper_preserves_shared_read_only_snapshot() -> None:
    delegate = Delegate()
    wrapper = FrozenSemanticConnector(delegate, _manifest())

    with wrapper.read_only_snapshot() as snapshot:
        assert isinstance(snapshot, FrozenSemanticConnector)
        assert snapshot is not wrapper
        assert snapshot.read_metadata(
            ("public",),
            ("public.asset",),
        ).tables[0].columns[0].aliases == ("retired",)

    assert delegate.snapshot_enters == 1


def _write_manifest(path: Path) -> str:
    payload = (_manifest().model_dump_json(indent=2) + "\n").encode(
        "utf-8"
    )
    path.write_bytes(payload)
    return hashlib.sha256(payload).hexdigest()


def test_load_manifest_verifies_external_trust_anchor(
    tmp_path: Path,
) -> None:
    path = tmp_path / "semantics.json"
    expected_sha256 = _write_manifest(path)

    loaded = load_view_semantic_manifest(
        path,
        expected_sha256=expected_sha256,
        snapshot=FULL_SNAPSHOT,
        datasource_id="synthetic",
        database_schema_sha256="5" * 64,
        allowed_schemas=("public",),
        allowed_tables=("public.asset", "public.owner"),
    )

    assert loaded == _manifest()


@pytest.mark.parametrize(
    "change",
    [
        "file_sha",
        "datasource",
        "database_schema",
        "base_snapshot",
        "scope",
    ],
)
def test_load_manifest_rejects_every_trust_anchor_drift(
    tmp_path: Path,
    change: str,
) -> None:
    path = tmp_path / "semantics.json"
    expected_sha256 = _write_manifest(path)
    kwargs = {
        "expected_sha256": expected_sha256,
        "snapshot": FULL_SNAPSHOT,
        "datasource_id": "synthetic",
        "database_schema_sha256": "5" * 64,
        "allowed_schemas": ("public",),
        "allowed_tables": ("public.asset", "public.owner"),
    }
    if change == "file_sha":
        kwargs["expected_sha256"] = "0" * 64
    elif change == "datasource":
        kwargs["datasource_id"] = "other"
    elif change == "database_schema":
        kwargs["database_schema_sha256"] = "0" * 64
    elif change == "base_snapshot":
        kwargs["snapshot"] = build_schema_snapshot(
            tables=(ASSET,),
            primary_keys=(),
            foreign_keys=(),
            unique_constraints=(),
            unique_indexes=(),
        )
    else:
        kwargs["allowed_tables"] = ("public.asset",)

    with pytest.raises(ValueError, match="manifest"):
        load_view_semantic_manifest(path, **kwargs)


def test_load_manifest_rejects_forged_entry_even_with_new_file_hash(
    tmp_path: Path,
) -> None:
    path = tmp_path / "semantics.json"
    _write_manifest(path)
    payload = json.loads(
        path.read_text(encoding="utf-8")
    )
    payload["entries"][0]["alias"] = "forged"
    encoded = (
        json.dumps(payload, indent=2) + "\n"
    ).encode("utf-8")
    path.write_bytes(encoded)

    with pytest.raises(ValueError, match="manifest"):
        load_view_semantic_manifest(
            path,
            expected_sha256=hashlib.sha256(encoded).hexdigest(),
            snapshot=FULL_SNAPSHOT,
            datasource_id="synthetic",
            database_schema_sha256="5" * 64,
            allowed_schemas=("public",),
            allowed_tables=("public.asset", "public.owner"),
        )
