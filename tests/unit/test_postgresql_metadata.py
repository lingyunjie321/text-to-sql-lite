from __future__ import annotations

from contextlib import AbstractContextManager
from typing import Any
from unittest.mock import Mock, call

import pytest
from psycopg_pool import PoolTimeout

from app.config import DatabaseSettings
from app.connectors.errors import (
    DatabaseError,
    ErrorType,
    PostgreSQLConnectorError,
)
from app.connectors.metadata import (
    empty_schema_snapshot,
    normalize_metadata_scope,
)
from app.connectors.metadata_queries import (
    FOREIGN_KEYS_SQL,
    KEY_CONSTRAINTS_SQL,
    TABLE_COLUMNS_SQL,
    UNIQUE_INDEXES_SQL,
)
from app.connectors.postgresql import PostgreSQLConnector


def _settings(**overrides: object) -> DatabaseSettings:
    values: dict[str, object] = {
        "dsn": "postgresql://reader:secret@127.0.0.1:55432/pagila",
        "min_pool_size": 1,
        "max_pool_size": 1,
        "pool_timeout_seconds": 0.1,
        "statement_timeout_seconds": 30,
    }
    values.update(overrides)
    return DatabaseSettings(**values)


class FakeResult:
    def __init__(self, rows: list[tuple[object, ...]]) -> None:
        self._rows = rows

    def fetchall(self) -> list[tuple[object, ...]]:
        return self._rows


class FakeTransaction(AbstractContextManager[None]):
    def __enter__(self) -> None:
        return None

    def __exit__(self, *args: object) -> None:
        return None


class FakeConnection(AbstractContextManager["FakeConnection"]):
    def __init__(self, results: dict[str, list[tuple[object, ...]]]) -> None:
        self.results = results
        self.calls: list[tuple[str, object | None]] = []

    def __enter__(self) -> FakeConnection:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def transaction(self) -> FakeTransaction:
        return FakeTransaction()

    def execute(
        self,
        sql: str,
        params: object | None = None,
    ) -> FakeResult:
        self.calls.append((sql, params))
        return FakeResult(self.results.get(sql, []))


class FakePool:
    def __init__(self, connection: FakeConnection) -> None:
        self._connection = connection
        self.timeouts: list[float] = []

    def connection(self, *, timeout: float) -> FakeConnection:
        self.timeouts.append(timeout)
        return self._connection


def _read_snapshot(
    results: dict[str, list[tuple[object, ...]]],
    allowed_tables: tuple[str, ...] | None = None,
):
    connector = PostgreSQLConnector(_settings())
    connector._pool = FakePool(FakeConnection(results))
    return connector.read_metadata(
        ("public",),
        allowed_tables
        or tuple(
            f"public.{table_name}"
            for table_name in {
                str(row[1])
                for row in results.get(TABLE_COLUMNS_SQL, [])
            }
        ),
    )


def _table_row(
    table_name: str,
    column_name: str,
    position: int,
) -> tuple[object, ...]:
    return (
        "public",
        table_name,
        "table",
        None,
        column_name,
        position,
        "int4",
        "integer",
        False,
        None,
    )


def _connector_error(
    error_type: ErrorType,
    *,
    sqlstate: str | None = None,
    retryable: bool = False,
) -> PostgreSQLConnectorError:
    return PostgreSQLConnectorError(
        DatabaseError(
            sqlstate=sqlstate,
            error_type=error_type,
            code=f"DB_{error_type.value}",
            retryable=retryable,
            public_message="safe",
        )
    )


def test_empty_metadata_scope_does_not_acquire_connection() -> None:
    connector = PostgreSQLConnector(_settings())
    connector._pool = Mock()

    snapshot = connector.read_metadata((), ())

    assert snapshot == empty_schema_snapshot()
    connector._pool.connection.assert_not_called()


def test_metadata_read_uses_one_read_only_transaction_and_maps_tables() -> None:
    connection = FakeConnection(
        {
            TABLE_COLUMNS_SQL: [
                (
                    "public",
                    "film",
                    "table",
                    "Available films",
                    "language_id",
                    4,
                    "int2",
                    "smallint",
                    False,
                    None,
                ),
                (
                    "public",
                    "film",
                    "table",
                    "Available films",
                    "film_id",
                    1,
                    "int4",
                    "integer",
                    False,
                    "Primary key",
                ),
            ],
            KEY_CONSTRAINTS_SQL: [],
            FOREIGN_KEYS_SQL: [],
            UNIQUE_INDEXES_SQL: [],
        }
    )
    pool = FakePool(connection)
    connector = PostgreSQLConnector(_settings())
    connector._pool = pool

    snapshot = connector.read_metadata(
        ("public",),
        ("public.film",),
    )

    assert pool.timeouts == [0.1]
    assert connection.calls[:2] == [
        ("SET TRANSACTION READ ONLY", None),
        (
            "SELECT set_config('statement_timeout', %s, true)",
            ("30s",),
        ),
    ]
    expected_params = (["public"], ["film"])
    assert connection.calls[2:] == [
        (TABLE_COLUMNS_SQL, expected_params),
        (KEY_CONSTRAINTS_SQL, expected_params),
        (FOREIGN_KEYS_SQL, expected_params),
        (UNIQUE_INDEXES_SQL, expected_params),
    ]
    assert snapshot.schemas == ("public",)
    assert [table.table_name for table in snapshot.tables] == ["film"]
    assert [column.column_name for column in snapshot.tables[0].columns] == [
        "film_id",
        "language_id",
    ]
    assert snapshot.tables[0].columns[0].data_type == "int4"
    assert not _contains_driver_object(snapshot)


def test_metadata_read_maps_keys_relationships_and_unique_indexes() -> None:
    snapshot = _read_snapshot(
        {
            TABLE_COLUMNS_SQL: [
                _table_row("film_actor", "film_id", 2),
                _table_row("film", "language_id", 2),
                _table_row("language", "language_id", 1),
                _table_row("film", "film_id", 1),
                _table_row("film_actor", "actor_id", 1),
            ],
            KEY_CONSTRAINTS_SQL: [
                ("film_actor_pkey", "p", "public", "film_actor", "film_id", 2),
                ("film_title_key", "u", "public", "film", "film_id", 1),
                ("film_pkey", "p", "public", "film", "film_id", 1),
                ("film_actor_pkey", "p", "public", "film_actor", "actor_id", 1),
            ],
            FOREIGN_KEYS_SQL: [
                (
                    "film_language_id_fkey",
                    "public",
                    "film",
                    "language_id",
                    "public",
                    "language",
                    "language_id",
                    1,
                ),
            ],
            UNIQUE_INDEXES_SQL: [
                (
                    "idx_unq_film_id",
                    "public",
                    "film",
                    ["film_id"],
                    "CREATE UNIQUE INDEX idx_unq_film_id "
                    "ON public.film USING btree (film_id)",
                    None,
                ),
            ],
        }
    )

    assert [
        (key.constraint_name, key.columns)
        for key in snapshot.primary_keys
    ] == [
        ("film_pkey", ("film_id",)),
        ("film_actor_pkey", ("actor_id", "film_id")),
    ]
    assert [
        (constraint.constraint_name, constraint.columns)
        for constraint in snapshot.unique_constraints
    ] == [("film_title_key", ("film_id",))]
    assert snapshot.foreign_keys[0].source_columns == ("language_id",)
    assert snapshot.foreign_keys[0].target_columns == ("language_id",)
    assert snapshot.unique_indexes[0].columns == ("film_id",)
    assert snapshot.unique_indexes[0].predicate is None


def test_composite_foreign_key_keeps_source_target_pairs_aligned() -> None:
    snapshot = _read_snapshot(
        {
            TABLE_COLUMNS_SQL: [
                _table_row("child", "first_id", 1),
                _table_row("child", "second_id", 2),
                _table_row("parent", "first_id", 1),
                _table_row("parent", "second_id", 2),
            ],
            KEY_CONSTRAINTS_SQL: [],
            FOREIGN_KEYS_SQL: [
                (
                    "child_parent_fkey",
                    "public",
                    "child",
                    "second_id",
                    "public",
                    "parent",
                    "second_id",
                    2,
                ),
                (
                    "child_parent_fkey",
                    "public",
                    "child",
                    "first_id",
                    "public",
                    "parent",
                    "first_id",
                    1,
                ),
            ],
            UNIQUE_INDEXES_SQL: [],
        }
    )

    foreign_key = snapshot.foreign_keys[0]
    assert foreign_key.source_columns == ("first_id", "second_id")
    assert foreign_key.target_columns == ("first_id", "second_id")


def test_snapshot_assembly_discards_objects_outside_authorized_scope() -> None:
    snapshot = _read_snapshot(
        {
            TABLE_COLUMNS_SQL: [
                _table_row("film", "film_id", 1),
                _table_row("staff", "staff_id", 1),
            ],
            KEY_CONSTRAINTS_SQL: [
                ("film_pkey", "p", "public", "film", "film_id", 1),
                ("staff_pkey", "p", "public", "staff", "staff_id", 1),
            ],
            FOREIGN_KEYS_SQL: [
                (
                    "film_staff_fkey",
                    "public",
                    "film",
                    "film_id",
                    "public",
                    "staff",
                    "staff_id",
                    1,
                )
            ],
            UNIQUE_INDEXES_SQL: [],
        },
        allowed_tables=("public.film",),
    )

    assert [table.table_name for table in snapshot.tables] == ["film"]
    assert [key.constraint_name for key in snapshot.primary_keys] == [
        "film_pkey"
    ]
    assert snapshot.foreign_keys == ()
    assert "staff" not in repr(snapshot)


@pytest.mark.parametrize(
    "results",
    [
        {
            TABLE_COLUMNS_SQL: [
                _table_row("film", "film_id", 1),
                _table_row("film", "title", 1),
            ],
            KEY_CONSTRAINTS_SQL: [],
            FOREIGN_KEYS_SQL: [],
            UNIQUE_INDEXES_SQL: [],
        },
        {
            TABLE_COLUMNS_SQL: [_table_row("film", "film_id", 1)],
            KEY_CONSTRAINTS_SQL: [
                ("film_pkey", "p", "public", "film", "missing", 1),
            ],
            FOREIGN_KEYS_SQL: [],
            UNIQUE_INDEXES_SQL: [],
        },
        {
            TABLE_COLUMNS_SQL: [_table_row("film", "film_id", 1)],
            KEY_CONSTRAINTS_SQL: [],
            FOREIGN_KEYS_SQL: [],
            UNIQUE_INDEXES_SQL: [
                (
                    "idx_empty",
                    "public",
                    "film",
                    [],
                    "CREATE UNIQUE INDEX idx_empty ON public.film",
                    None,
                )
            ],
        },
    ],
)
def test_inconsistent_metadata_is_a_public_safe_schema_error(
    results: dict[str, list[tuple[object, ...]]],
) -> None:
    with pytest.raises(PostgreSQLConnectorError) as caught:
        _read_snapshot(results)

    assert caught.value.details.error_type is ErrorType.SCHEMA_ERROR
    assert caught.value.details.retryable is False
    assert caught.value.details.public_message == (
        "The database metadata snapshot is inconsistent."
    )
    assert "film" not in str(caught.value)
    assert "missing" not in str(caught.value)


@pytest.mark.parametrize("retry_count", [0, 1, 3])
def test_metadata_read_honors_connection_retry_budget(
    retry_count: int,
) -> None:
    connector = PostgreSQLConnector(
        _settings(connection_retry_count=retry_count)
    )
    expected = empty_schema_snapshot()
    failures = [
        _connector_error(
            ErrorType.CONNECTION_ERROR,
            sqlstate="08006",
            retryable=True,
        )
        for _ in range(retry_count)
    ]
    connector._read_metadata_once = Mock(
        side_effect=[*failures, expected]
    )
    scope = normalize_metadata_scope(
        ("public",),
        ("public.film",),
    )

    assert connector.read_metadata(
        ("public",), ("public.film",)
    ) == expected
    assert connector._read_metadata_once.call_args_list == [
        call(scope)
        for _ in range(retry_count + 1)
    ]
    assert connector._consume_retry_count() == retry_count
    assert connector._consume_retry_count() == 0


@pytest.mark.parametrize(
    "failure",
    [
        _connector_error(ErrorType.PERMISSION_DENIED, sqlstate="42501"),
        _connector_error(ErrorType.TIMEOUT, sqlstate="57014"),
        _connector_error(ErrorType.SCHEMA_ERROR, sqlstate="42P01"),
        _connector_error(ErrorType.RESOURCE_RISK, sqlstate="53000"),
        _connector_error(ErrorType.UNKNOWN),
        PoolTimeout("pool exhausted"),
    ],
)
def test_metadata_read_does_not_retry_non_transient_errors(
    failure: Exception,
) -> None:
    connector = PostgreSQLConnector(
        _settings(connection_retry_count=3)
    )
    connector._read_metadata_once = Mock(side_effect=failure)

    with pytest.raises(PostgreSQLConnectorError):
        connector.read_metadata(("public",), ("public.film",))

    connector._read_metadata_once.assert_called_once_with(
        normalize_metadata_scope(("public",), ("public.film",))
    )


def _contains_driver_object(value: object) -> bool:
    if isinstance(value, (FakeConnection, FakeResult, FakePool)):
        return True
    fields: dict[str, Any] | None = getattr(
        value, "__dataclass_fields__", None
    )
    if fields is not None:
        return any(
            _contains_driver_object(getattr(value, name))
            for name in fields
        )
    if isinstance(value, (tuple, list)):
        return any(_contains_driver_object(item) for item in value)
    return False
