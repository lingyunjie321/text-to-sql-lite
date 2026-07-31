from __future__ import annotations

import math
import time
from contextlib import contextmanager
from contextvars import ContextVar

import pymysql

from app.connectors.base import DatabaseConnector
from app.connectors.errors import (
    DatabaseConnectorError,
    DatabaseError,
    ErrorType,
    normalize_database_error,
)
from app.connectors.metadata import (
    MetadataScope,
    SchemaSnapshot,
    build_schema_snapshot,
    empty_schema_snapshot,
    normalize_metadata_scope,
)
from app.connectors.metadata_queries_starrocks import build_metadata_queries
from app.connectors.models import ExecutionResult, ResultColumn
from app.connectors.mysql import (
    MySQLConnector,
    _ConnectionPool,
    _execute_from_connection,
    _map_tables_mysql,
    _map_keys_mysql,
    _map_unique_indexes_mysql,
    _map_foreign_keys,
    _metadata_schema_error,
    _validate_metadata_references,
    _operation_timeout,
    _remaining_timeout,
)


class StarRocksConnector(MySQLConnector):
    """Pluggable StarRocks database connector.

    StarRocks is MySQL-protocol compatible.  This connector extends
    :class:`MySQLConnector` with StarRocks-specific query-timeout
    semantics and metadata query handling.

    Key differences from MySQL:
    * No ``SET TRANSACTION READ ONLY`` (StarRocks does not support it).
    * Uses ``SET query_timeout = N`` instead of ``max_execution_time``.
    * Foreign keys and unique constraints return empty results (StarRocks
      does not enforce referential integrity).

    Parameters match :class:`MySQLConnector`.
    """

    dialect_name: str = "starrocks"

    # ── Override: skip read-only transaction (unsupported) ───────

    @contextmanager
    def read_only_snapshot(self):
        if self._snapshot_connection.get() is not None:
            raise ValueError("read-only snapshot is already active")
        body_error: BaseException | None = None
        try:
            conn = self._pool.connection()
            try:
                conn.begin()
                _set_starrocks_timeout(
                    conn, self._statement_timeout_seconds
                )
                token = self._snapshot_connection.set(conn)
                try:
                    try:
                        yield self
                    except BaseException as error:
                        body_error = error
                        raise
                finally:
                    self._snapshot_connection.reset(token)
            finally:
                try:
                    conn.rollback()
                except Exception:
                    pass
                self._pool.putback(conn)
        except BaseException as error:
            if body_error is not None:
                raise body_error
            if not isinstance(error, Exception):
                raise
            raise normalize_database_error(error) from None

    # ── Override execute: use StarRocks timeout ────────────────

    def _execute_once(
        self,
        sql: str,
        *,
        timeout_seconds: float | None = None,
    ) -> ExecutionResult:
        try:
            snapshot_conn = self._snapshot_connection.get()
            if snapshot_conn is not None:
                return _execute_from_connection(
                    snapshot_conn,
                    sql,
                    max_result_rows=self._max_result_rows,
                    dialect="starrocks",
                )
            conn = self._pool.connection()
            try:
                conn.begin()
                effective_timeout = (
                    float(self._statement_timeout_seconds)
                    if timeout_seconds is None
                    else timeout_seconds
                )
                _set_starrocks_timeout(conn, effective_timeout)
                result = _execute_from_connection(
                    conn,
                    sql,
                    max_result_rows=self._max_result_rows,
                    dialect="starrocks",
                )
                conn.commit()
                return result
            except Exception:
                try:
                    conn.rollback()
                except Exception:
                    pass
                raise
            finally:
                self._pool.putback(conn)
        except Exception as error:
            raise normalize_database_error(error) from None

    # ── Override read metadata: use StarRocks queries ──────────

    def _read_metadata_once(
        self,
        scope: MetadataScope,
        *,
        timeout_seconds: float | None = None,
    ) -> SchemaSnapshot:
        try:
            snapshot_conn = self._snapshot_connection.get()
            if snapshot_conn is not None:
                return _read_metadata_starrocks(
                    snapshot_conn,
                    scope,
                    dialect="starrocks",
                )
            conn = self._pool.connection()
            try:
                conn.begin()
                effective_timeout = (
                    float(self._statement_timeout_seconds)
                    if timeout_seconds is None
                    else timeout_seconds
                )
                _set_starrocks_timeout(conn, effective_timeout)
                result = _read_metadata_starrocks(
                    conn,
                    scope,
                    dialect="starrocks",
                )
                conn.commit()
                return result
            except Exception:
                try:
                    conn.rollback()
                except Exception:
                    pass
                raise
            finally:
                self._pool.putback(conn)
        except Exception as error:
            raise normalize_database_error(error) from None


# ── StarRocks session helpers ────────────────────────────────────


def _set_starrocks_timeout(
    conn: pymysql.Connection,
    timeout_seconds: float,
) -> None:
    """Set ``query_timeout`` for the session (StarRocks)."""
    whole_seconds = max(1, int(math.ceil(timeout_seconds)))
    with conn.cursor() as cursor:
        cursor.execute("SET query_timeout = %s", (whole_seconds,))


# ── StarRocks metadata ───────────────────────────────────────────


def _read_metadata_starrocks(
    conn: pymysql.Connection,
    scope: MetadataScope,
    *,
    dialect: str,
) -> SchemaSnapshot:
    """Read metadata using StarRocks-specific information_schema queries."""
    schema_list = scope.schema_parameters
    table_list = scope.table_parameters
    param_count = max(len(schema_list), len(table_list), 1)
    queries = build_metadata_queries(param_count)

    flat_params = tuple(schema_list + table_list)

    with conn.cursor() as cursor:
        cursor.execute(queries["table_columns"], flat_params)
        table_rows = cursor.fetchall()

        cursor.execute(queries["primary_keys"], flat_params)
        key_rows = cursor.fetchall()

        cursor.execute(queries["foreign_keys"], flat_params)
        foreign_key_rows = cursor.fetchall()

        cursor.execute(queries["unique_indexes"], flat_params)
        unique_index_rows = cursor.fetchall()

    authorized = set(scope.table_pairs)
    tables = _map_tables_mysql(
        [
            row
            for row in table_rows
            if (str(row[0]), str(row[1])) in authorized
        ]
    )
    primary_keys, unique_constraints = _map_keys_mysql(
        [
            row
            for row in key_rows
            if (str(row[2]), str(row[3])) in authorized
        ]
    )
    foreign_keys = _map_foreign_keys(
        [
            row
            for row in foreign_key_rows
            if row[1] is not None
            and (str(row[1]), str(row[2])) in authorized
            and (str(row[4]), str(row[5])) in authorized
        ]
    )
    unique_indexes = _map_unique_indexes_mysql(
        [
            row
            for row in unique_index_rows
            if row[0] is not None
            and (str(row[1]), str(row[2])) in authorized
        ]
    )
    _validate_metadata_references(
        tables=tables,
        primary_keys=primary_keys,
        foreign_keys=foreign_keys,
        unique_constraints=unique_constraints,
        unique_indexes=unique_indexes,
    )
    return build_schema_snapshot(
        tables=tables,
        primary_keys=primary_keys,
        foreign_keys=foreign_keys,
        unique_constraints=unique_constraints,
        unique_indexes=unique_indexes,
    )
