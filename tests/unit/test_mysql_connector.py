from __future__ import annotations

from contextlib import AbstractContextManager

import pytest

from app.connectors.errors import DatabaseConnectorError
from app.connectors.metadata import normalize_metadata_scope
from app.connectors.mysql import (
    MySQLConnector,
    _read_metadata_from_connection,
)


class _Cursor(AbstractContextManager["_Cursor"]):
    def __init__(self, connection: "_Connection") -> None:
        self._connection = connection
        self.description = (("film_id", 3),)

    def __enter__(self) -> "_Cursor":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def execute(
        self,
        sql: str,
        params: tuple[object, ...] | None = None,
    ) -> None:
        self._connection.events.append((sql, params))
        if sql == "START TRANSACTION READ ONLY":
            if self._connection.start_error is not None:
                raise self._connection.start_error
            return
        if sql.startswith("SET SESSION max_execution_time"):
            return
        self._connection.user_sql_count += 1
        if self._connection.user_error is not None:
            raise self._connection.user_error

    def fetchmany(self, count: int) -> list[tuple[int]]:
        del count
        return [(1,)]


class _Connection:
    def __init__(
        self,
        *,
        start_error: Exception | None = None,
        user_error: Exception | None = None,
        rollback_error: Exception | None = None,
    ) -> None:
        self.start_error = start_error
        self.user_error = user_error
        self.rollback_error = rollback_error
        self.events: list[tuple[str, tuple[object, ...] | None]] = []
        self.user_sql_count = 0
        self.begin_count = 0
        self.commit_count = 0
        self.rollback_count = 0
        self.closed = False

    def cursor(self) -> _Cursor:
        return _Cursor(self)

    def begin(self) -> None:
        self.begin_count += 1

    def commit(self) -> None:
        self.commit_count += 1

    def rollback(self) -> None:
        self.rollback_count += 1
        if self.rollback_error is not None:
            raise self.rollback_error

    def close(self) -> None:
        self.closed = True


class _Pool:
    def __init__(self, connection: _Connection) -> None:
        self._connection = connection
        self.putback_count = 0
        self.discard_count = 0

    def connection(self) -> _Connection:
        return self._connection

    def putback(self, connection: _Connection) -> None:
        assert connection is self._connection
        self.putback_count += 1

    def discard(self, connection: _Connection) -> None:
        assert connection is self._connection
        self.discard_count += 1
        connection.close()


def _connector(connection: _Connection) -> tuple[MySQLConnector, _Pool]:
    connector = MySQLConnector(
        host="127.0.0.1",
        user="reader",
        password="private-secret",
        database="sakila",
        connection_retry_count=0,
    )
    pool = _Pool(connection)
    connector._pool = pool  # type: ignore[assignment]
    return connector, pool


class _MetadataCursor(AbstractContextManager["_MetadataCursor"]):
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[object, ...] | None]] = []
        self._result_index = -1
        self._results = (
            [
                (
                    "sakila",
                    "actor",
                    "table",
                    None,
                    "actor_id",
                    1,
                    "smallint",
                    "smallint unsigned",
                    False,
                    None,
                ),
                (
                    "sakila",
                    "actor_info",
                    "view",
                    None,
                    "actor_id",
                    1,
                    "smallint",
                    "smallint unsigned",
                    False,
                    None,
                ),
            ],
            [],
            [],
            [],
        )

    def __enter__(self) -> "_MetadataCursor":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def execute(
        self,
        sql: str,
        params: tuple[object, ...] | None = None,
    ) -> None:
        self.calls.append((sql, params))
        self._result_index += 1

    def fetchall(self) -> list[tuple[object, ...]]:
        return self._results[self._result_index]


class _MetadataConnection:
    def __init__(self) -> None:
        self.metadata_cursor = _MetadataCursor()

    def cursor(self) -> _MetadataCursor:
        return self.metadata_cursor


def test_execute_starts_atomic_read_only_transaction_before_user_sql() -> None:
    connection = _Connection()
    connector, pool = _connector(connection)

    result = connector.execute("SELECT film_id FROM film")

    assert result.rows == [[1]]
    assert connection.events[0] == ("START TRANSACTION READ ONLY", None)
    assert connection.events[-1] == ("SELECT film_id FROM film", None)
    assert connection.begin_count == 0
    assert connection.user_sql_count == 1
    assert connection.commit_count == 1
    assert pool.putback_count == 1
    assert pool.discard_count == 0


def test_read_only_start_failure_executes_no_user_sql_and_discards_connection(
) -> None:
    connection = _Connection(
        start_error=RuntimeError("driver password=private-secret")
    )
    connector, pool = _connector(connection)

    with pytest.raises(DatabaseConnectorError) as captured:
        connector.execute("SELECT film_id FROM film")

    assert connection.user_sql_count == 0
    assert connection.closed is True
    assert pool.discard_count == 1
    assert pool.putback_count == 0
    assert "private-secret" not in str(captured.value)


def test_snapshot_start_failure_never_enters_body_and_discards_connection(
) -> None:
    connection = _Connection(start_error=RuntimeError("unsafe driver detail"))
    connector, pool = _connector(connection)
    entered = False

    with pytest.raises(DatabaseConnectorError):
        with connector.read_only_snapshot():
            entered = True

    assert entered is False
    assert connection.user_sql_count == 0
    assert connection.closed is True
    assert pool.discard_count == 1
    assert pool.putback_count == 0


def test_snapshot_reuses_read_only_transaction_and_rolls_back_on_exit() -> None:
    connection = _Connection()
    connector, pool = _connector(connection)

    with connector.read_only_snapshot():
        result = connector.execute("SELECT film_id FROM film")

    assert result.rows == [[1]]
    assert connection.events[0] == ("START TRANSACTION READ ONLY", None)
    assert connection.user_sql_count == 1
    assert connection.commit_count == 0
    assert connection.rollback_count == 1
    assert pool.putback_count == 1
    assert pool.discard_count == 0


def test_rollback_failure_discards_connection_instead_of_returning_it() -> None:
    connection = _Connection(
        user_error=RuntimeError("query failed"),
        rollback_error=RuntimeError("rollback failed"),
    )
    connector, pool = _connector(connection)

    with pytest.raises(DatabaseConnectorError):
        connector.execute("SELECT film_id FROM film")

    assert connection.closed is True
    assert pool.discard_count == 1
    assert pool.putback_count == 0


def test_metadata_uses_unique_schema_params_and_preserves_view_kind() -> None:
    connection = _MetadataConnection()
    scope = normalize_metadata_scope(
        ("sakila",),
        ("sakila.actor", "sakila.actor_info"),
    )

    snapshot = _read_metadata_from_connection(
        connection,  # type: ignore[arg-type]
        scope,
        dialect="mysql",
    )

    assert [
        params for _, params in connection.metadata_cursor.calls
    ] == [("sakila", "actor", "actor_info")] * 4
    assert tuple(
        (table.table_name, table.relation_kind)
        for table in snapshot.tables
    ) == (("actor", "table"), ("actor_info", "view"))
