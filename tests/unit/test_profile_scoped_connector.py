from __future__ import annotations

from contextlib import contextmanager

import pytest

from app.connectors.catalog import validate_allowlist
from app.connectors.errors import DatabaseConnectorError, ErrorType
from app.connectors.metadata import (
    ColumnMetadata,
    TableMetadata,
    build_schema_snapshot,
)
from app.connectors.models import ExecutionResult
from app.connectors.scoped import ProfileScopedConnector


def _table(name: str, *, schema: str = "public") -> TableMetadata:
    return TableMetadata(
        schema_name=schema,
        table_name=name,
        relation_kind="table",
        comment=None,
        columns=(
            ColumnMetadata(
                schema_name=schema,
                table_name=name,
                column_name="id",
                ordinal_position=1,
                data_type="integer",
                formatted_type="integer",
                nullable=False,
                comment=None,
            ),
        ),
    )


def _snapshot(*names: str):
    return build_schema_snapshot(
        tables=tuple(_table(name) for name in names),
        primary_keys=(),
        foreign_keys=(),
        unique_constraints=(),
        unique_indexes=(),
    )


class MetadataConnectorFake:
    dialect_name = "postgres"

    def __init__(self, snapshot=None) -> None:
        self.snapshot = snapshot or _snapshot("actor")
        self.read_count = 0
        self.metadata_timeouts: list[float | None] = []
        self.execute_timeouts: list[float | None] = []
        self.events: list[str] = []
        self.snapshot_enters = 0

    def open(self) -> None:
        self.events.append("open")

    def close(self) -> None:
        self.events.append("close")

    def check_connection(self) -> None:
        self.events.append("check")

    def read_metadata(
        self,
        allowed_schemas: tuple[str, ...],
        allowed_tables: tuple[str, ...],
        *,
        timeout_seconds: float | None = None,
    ):
        del allowed_schemas, allowed_tables
        self.read_count += 1
        self.metadata_timeouts.append(timeout_seconds)
        return self.snapshot

    def execute(
        self,
        sql: str,
        *,
        timeout_seconds: float | None = None,
    ) -> ExecutionResult:
        del sql
        self.execute_timeouts.append(timeout_seconds)
        return ExecutionResult(
            columns=(),
            rows=[],
            returned_row_count=0,
            truncated=False,
            execution_time_ms=0.0,
        )

    @contextmanager
    def read_only_snapshot(self):
        self.snapshot_enters += 1
        yield self


def _scoped(delegate: MetadataConnectorFake) -> ProfileScopedConnector:
    return ProfileScopedConnector(
        delegate=delegate,
        allowed_schemas=("public",),
        allowed_tables=("public.actor",),
    )


def test_scoped_connector_rejects_scope_mismatch_before_delegate_read():
    delegate = MetadataConnectorFake()
    connector = _scoped(delegate)

    with pytest.raises(DatabaseConnectorError) as captured:
        connector.read_metadata(
            ("public",),
            ("public.actor", "public.staff"),
        )

    assert captured.value.details.code == "DB_ALLOWLIST_MISMATCH"
    assert captured.value.details.error_type is ErrorType.PERMISSION_DENIED
    assert delegate.read_count == 0


@pytest.mark.parametrize(
    ("allowed_schemas", "allowed_tables"),
    [
        ((), ()),
        (("public",), ()),
        (("public", "unused"), ("public.actor",)),
    ],
)
def test_scoped_connector_rejects_empty_or_unmatched_profile_scope(
    allowed_schemas: tuple[str, ...],
    allowed_tables: tuple[str, ...],
):
    with pytest.raises(DatabaseConnectorError) as captured:
        ProfileScopedConnector(
            delegate=MetadataConnectorFake(),
            allowed_schemas=allowed_schemas,
            allowed_tables=allowed_tables,
        )

    assert captured.value.details.code == "DB_ALLOWLIST_MISMATCH"


@pytest.mark.parametrize("returned", [_snapshot(), _snapshot("actor", "staff")])
def test_scoped_connector_rejects_missing_or_extra_returned_relations(returned):
    delegate = MetadataConnectorFake(returned)
    connector = _scoped(delegate)

    with pytest.raises(DatabaseConnectorError) as captured:
        connector.read_metadata(("public",), ("public.actor",))

    assert captured.value.details.code == "DB_ALLOWLIST_MISMATCH"
    assert "actor" not in str(captured.value)
    assert "staff" not in str(captured.value)


def test_scoped_connector_accepts_same_scope_in_canonical_order():
    delegate = MetadataConnectorFake()
    connector = ProfileScopedConnector(
        delegate=delegate,
        allowed_schemas=("public",),
        allowed_tables=("public.staff", "public.actor"),
    )
    delegate.snapshot = _snapshot("actor", "staff")

    snapshot = connector.read_metadata(
        ("public",),
        ("public.actor", "public.staff"),
        timeout_seconds=0.4,
    )

    assert tuple(table.table_name for table in snapshot.tables) == (
        "actor",
        "staff",
    )
    assert delegate.metadata_timeouts == [0.4]


def test_scoped_connector_accepts_authorized_schema_subset():
    delegate = MetadataConnectorFake(_snapshot("actor"))
    connector = ProfileScopedConnector(
        delegate=delegate,
        allowed_schemas=("public", "archive"),
        allowed_tables=("public.actor", "archive.audit"),
    )

    snapshot = connector.read_metadata(
        ("public",),
        ("public.actor",),
    )

    assert tuple(table.table_name for table in snapshot.tables) == ("actor",)
    assert delegate.read_count == 1


def test_scoped_connector_delegates_lifecycle_execution_and_snapshot():
    delegate = MetadataConnectorFake()
    connector = _scoped(delegate)

    connector.open()
    connector.check_connection()
    connector.execute("SELECT 1", timeout_seconds=0.3)
    with connector.read_only_snapshot() as snapshot_connector:
        assert snapshot_connector is connector
    connector.close()

    assert connector.dialect_name == "postgres"
    assert delegate.events == ["open", "check", "close"]
    assert delegate.execute_timeouts == [0.3]
    assert delegate.snapshot_enters == 1


def test_validate_allowlist_reads_only_requested_scope():
    delegate = MetadataConnectorFake(_snapshot("actor", "staff"))

    snapshot = validate_allowlist(
        delegate,
        database_type="postgresql",
        allowed_schemas=("public",),
        allowed_tables=("public.staff", "public.actor"),
        timeout_seconds=30.0,
    )

    assert tuple(table.table_name for table in snapshot.tables) == (
        "actor",
        "staff",
    )
    assert delegate.read_count == 1
    assert delegate.metadata_timeouts == [30.0]


def test_validate_allowlist_rejects_missing_relation():
    delegate = MetadataConnectorFake(_snapshot("actor"))

    with pytest.raises(DatabaseConnectorError) as captured:
        validate_allowlist(
            delegate,
            database_type="postgresql",
            allowed_schemas=("public",),
            allowed_tables=("public.actor", "public.staff"),
            timeout_seconds=30.0,
        )

    assert captured.value.details.code == "DB_ALLOWLIST_MISMATCH"


@pytest.mark.parametrize(
    ("database_type", "schema_name"),
    [
        ("postgresql", "pg_catalog"),
        ("postgresql", "pg_temp_7"),
        ("mysql", "information_schema"),
        ("mysql", "sys"),
    ],
)
def test_validate_allowlist_rejects_system_schema_without_database_read(
    database_type: str,
    schema_name: str,
):
    delegate = MetadataConnectorFake()

    with pytest.raises(DatabaseConnectorError) as captured:
        validate_allowlist(
            delegate,
            database_type=database_type,
            allowed_schemas=(schema_name,),
            allowed_tables=(f"{schema_name}.object",),
            timeout_seconds=30.0,
        )

    assert captured.value.details.code == "DB_ALLOWLIST_MISMATCH"
    assert delegate.read_count == 0
