"""MySQL 连接器：基于 pymysql 的 :class:`DatabaseConnector` 实现。

提供连接池、只读事务快照、语句超时（``max_execution_time``）、
结果截断与 ``information_schema`` 元数据读取；所有驱动异常经
:func:`normalize_database_error` 规范化后抛出。StarRocks 连接器
在本类基础上做方言特化。
"""

from __future__ import annotations

import logging
import math
import queue
import threading
import time
from contextlib import contextmanager
from contextvars import ContextVar
from types import TracebackType
from typing import Any

import pymysql
import pymysql.cursors

from app.connectors.base import DatabaseConnector
from app.connectors.errors import (
    DatabaseConnectorError,
    DatabaseError,
    ErrorType,
    normalize_database_error,
)
from app.connectors.metadata import (
    ColumnMetadata,
    ForeignKeyMetadata,
    MetadataScope,
    PrimaryKeyMetadata,
    SchemaSnapshot,
    TableMetadata,
    UniqueConstraintMetadata,
    UniqueIndexMetadata,
    build_schema_snapshot,
    empty_schema_snapshot,
    normalize_metadata_scope,
)
from app.connectors.metadata_queries_mysql import build_metadata_queries
from app.connectors.models import ExecutionResult, ResultColumn
from app.connectors.types import normalize_value

logger = logging.getLogger(__name__)


class MySQLConnector:
    """Pluggable MySQL database connector.

    Parameters
    ----------
    host:
        MySQL server hostname or IP.
    port:
        MySQL server port (default 3306).
    user:
        MySQL user name.
    password:
        MySQL password.
    database:
        Default database / schema.
    min_pool_size:
        Minimum connections in the pool.
    max_pool_size:
        Maximum connections in the pool.
    pool_timeout_seconds:
        Seconds to wait for a connection from the pool.
    statement_timeout_seconds:
        Default statement timeout in seconds.
    max_result_rows:
        Maximum rows to return per query.
    connection_retry_count:
        Number of retries on transient connection errors.
    """

    dialect_name: str = "mysql"

    def __init__(
        self,
        *,
        host: str,
        port: int = 3306,
        user: str,
        password: str,
        database: str,
        min_pool_size: int = 1,
        max_pool_size: int = 4,
        pool_timeout_seconds: float = 5.0,
        statement_timeout_seconds: int = 30,
        max_result_rows: int = 1000,
        connection_retry_count: int = 1,
    ) -> None:
        _validate_pool_sizes(min_pool_size, max_pool_size)
        self._host = host
        self._port = port
        self._user = user
        self._password = password
        self._database = database
        self._min_pool_size = min_pool_size
        self._max_pool_size = max_pool_size
        self._pool_timeout_seconds = pool_timeout_seconds
        self._statement_timeout_seconds = statement_timeout_seconds
        self._max_result_rows = max_result_rows
        self._connection_retry_count = connection_retry_count

        self._retry_count: ContextVar[int] = ContextVar(
            f"mysql_connector_retry_{id(self)}", default=0
        )
        self._snapshot_connection: ContextVar[pymysql.Connection | None] = (
            ContextVar(
                f"mysql_connector_snapshot_{id(self)}", default=None
            )
        )
        self._pool: _ConnectionPool | None = None

    # ── Connection lifecycle ────────────────────────────────────

    def open(self) -> None:
        """建立连接池并验证连通性；重复调用幂等。"""
        if self._pool is not None and not self._pool.closed:
            return
        self.check_connection()
        self._pool = _ConnectionPool(
            create=self._connect,
            min_size=self._min_pool_size,
            max_size=self._max_pool_size,
            timeout=self._pool_timeout_seconds,
        )
        self._pool.open()

    def close(self) -> None:
        """关闭连接池并释放全部连接；之后可重新 ``open``。"""
        if self._pool is not None:
            self._pool.close()
            self._pool = None

    def __enter__(self) -> MySQLConnector:
        self.open()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def check_connection(self) -> None:
        """执行轻量连通性检查（``SELECT 1``）。

        失败时抛出规范化后的 :class:`DatabaseConnectorError`。
        """
        try:
            conn = self._connect()
            try:
                with conn.cursor() as cursor:
                    cursor.execute("SELECT 1")
            finally:
                conn.close()
        except Exception as error:
            raise normalize_database_error(error) from None

    def _connect(self) -> pymysql.Connection:
        return pymysql.connect(
            host=self._host,
            port=self._port,
            user=self._user,
            password=self._password,
            database=self._database,
            autocommit=False,
            connect_timeout=int(
                max(1, self._pool_timeout_seconds)
            ),
            cursorclass=pymysql.cursors.Cursor,
        )

    # ── Snapshot context manager ─────────────────────────────────

    @contextmanager
    def read_only_snapshot(self):
        """进入只读快照事务上下文。

        上下文内的 ``execute`` / ``read_metadata`` 复用同一连接，
        会话设置为只读事务并应用语句超时；退出时回滚并归还连接。
        不允许嵌套。
        """
        if self._snapshot_connection.get() is not None:
            raise ValueError("read-only snapshot is already active")
        body_error: BaseException | None = None
        try:
            conn = self._pool.connection()
            reusable = True
            transaction_started = False
            try:
                try:
                    _start_mysql_read_only_transaction(conn)
                    transaction_started = True
                except BaseException:
                    reusable = False
                    self._pool.discard(conn)
                    raise
                _set_mysql_timeout(
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
                cleanup_error = None
                if reusable and transaction_started:
                    cleanup_error = _rollback_or_discard(
                        self._pool,
                        conn,
                    )
                    reusable = cleanup_error is None
                if reusable:
                    self._pool.putback(conn)
                if cleanup_error is not None and body_error is None:
                    raise cleanup_error
        except BaseException as error:
            if body_error is not None:
                raise body_error
            if not isinstance(error, Exception):
                raise
            raise normalize_database_error(error) from None

    # ── SQL execution ───────────────────────────────────────────

    def execute(
        self,
        sql: str,
        *,
        timeout_seconds: float | None = None,
    ) -> ExecutionResult:
        """在只读事务中执行 *sql* 并返回截断受控的结果集。

        *timeout_seconds* 缺省时使用连接器的 ``statement_timeout_seconds``；
        可重试的连接错误按 ``connection_retry_count`` 重试，其余错误
        规范化后直接抛出。
        """
        operation_started_at, timeout = _operation_timeout(timeout_seconds)
        self._retry_count.set(0)
        for retry_index in range(self._connection_retry_count + 1):
            self._retry_count.set(retry_index)
            try:
                if timeout is None:
                    return self._execute_once(sql)
                return self._execute_once(
                    sql,
                    timeout_seconds=_remaining_timeout(
                        operation_started_at=operation_started_at,
                        timeout_seconds=timeout,
                    ),
                )
            except Exception as error:
                normalized = normalize_database_error(error)
                if (
                    not normalized.details.retryable
                    or retry_index >= self._connection_retry_count
                ):
                    raise normalized from None
        raise AssertionError("unreachable")

    def read_metadata(
        self,
        allowed_schemas: tuple[str, ...],
        allowed_tables: tuple[str, ...],
        *,
        timeout_seconds: float | None = None,
    ) -> SchemaSnapshot:
        """读取授权范围内的 schema 元数据并构建快照。

        只读取 ``allowed_schemas`` / ``allowed_tables``（``schema.table``
        形式）覆盖的表、列、主键、外键与唯一索引；范围为空时返回空
        快照。重试与超时语义同 :meth:`execute`。
        """
        operation_started_at, timeout = _operation_timeout(timeout_seconds)
        self._retry_count.set(0)
        scope = normalize_metadata_scope(allowed_schemas, allowed_tables)
        if scope.is_empty:
            return empty_schema_snapshot()

        for retry_index in range(self._connection_retry_count + 1):
            self._retry_count.set(retry_index)
            try:
                if timeout is None:
                    return self._read_metadata_once(scope)
                return self._read_metadata_once(
                    scope,
                    timeout_seconds=_remaining_timeout(
                        operation_started_at=operation_started_at,
                        timeout_seconds=timeout,
                    ),
                )
            except Exception as error:
                normalized = normalize_database_error(error)
                if (
                    not normalized.details.retryable
                    or retry_index >= self._connection_retry_count
                ):
                    raise normalized from None
        raise AssertionError("unreachable")

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
                    dialect="mysql",
                )
            conn = self._pool.connection()
            reusable = True
            transaction_started = False
            try:
                try:
                    _start_mysql_read_only_transaction(conn)
                    transaction_started = True
                except BaseException:
                    reusable = False
                    self._pool.discard(conn)
                    raise
                effective_timeout = (
                    float(self._statement_timeout_seconds)
                    if timeout_seconds is None
                    else timeout_seconds
                )
                _set_mysql_timeout(conn, effective_timeout)
                result = _execute_from_connection(
                    conn,
                    sql,
                    max_result_rows=self._max_result_rows,
                    dialect="mysql",
                )
                conn.commit()
                transaction_started = False
                return result
            except BaseException:
                if reusable and transaction_started:
                    reusable = (
                        _rollback_or_discard(self._pool, conn) is None
                    )
                raise
            finally:
                if reusable:
                    self._pool.putback(conn)
        except Exception as error:
            raise normalize_database_error(error) from None

    def _read_metadata_once(
        self,
        scope: MetadataScope,
        *,
        timeout_seconds: float | None = None,
    ) -> SchemaSnapshot:
        try:
            snapshot_conn = self._snapshot_connection.get()
            if snapshot_conn is not None:
                return _read_metadata_from_connection(
                    snapshot_conn,
                    scope,
                    dialect="mysql",
                )
            conn = self._pool.connection()
            reusable = True
            transaction_started = False
            try:
                try:
                    _start_mysql_read_only_transaction(conn)
                    transaction_started = True
                except BaseException:
                    reusable = False
                    self._pool.discard(conn)
                    raise
                effective_timeout = (
                    float(self._statement_timeout_seconds)
                    if timeout_seconds is None
                    else timeout_seconds
                )
                _set_mysql_timeout(conn, effective_timeout)
                result = _read_metadata_from_connection(
                    conn,
                    scope,
                    dialect="mysql",
                )
                conn.commit()
                transaction_started = False
                return result
            except BaseException:
                if reusable and transaction_started:
                    reusable = (
                        _rollback_or_discard(self._pool, conn) is None
                    )
                raise
            finally:
                if reusable:
                    self._pool.putback(conn)
        except Exception as error:
            raise normalize_database_error(error) from None


# ── Connection pool ──────────────────────────────────────────────


class _ConnectionPool:
    """Lightweight thread-safe connection pool for pymysql."""

    def __init__(
        self,
        *,
        create: Any,
        min_size: int,
        max_size: int,
        timeout: float,
    ) -> None:
        self._create = create
        self._min = min_size
        self._max = max_size
        self._timeout = timeout
        self._queue: queue.Queue[pymysql.Connection] = queue.Queue(
            maxsize=max_size
        )
        self._created = 0
        self._lock = threading.Lock()
        self.closed = False

    def open(self) -> None:
        """预建 ``min_size`` 个连接放入池中；已关闭的池不再打开。"""
        if self.closed:
            return
        for _ in range(self._min):
            conn = self._create()
            self._queue.put(conn)
            self._created += 1

    def connection(self) -> pymysql.Connection:
        """Get a connection from the pool, blocking if necessary."""
        if self.closed:
            raise DatabaseConnectorError(
                DatabaseError(
                    sqlstate=None,
                    error_type=ErrorType.CONNECTION_ERROR,
                    code="DB_CONNECTION_ERROR",
                    retryable=False,
                    public_message="Connection pool is closed.",
                )
            )
        try:
            return self._queue.get(timeout=self._timeout)
        except queue.Empty:
            with self._lock:
                if self._created < self._max:
                    conn = self._create()
                    self._created += 1
                    return conn
            # Pool exhausted — block until one is returned.
            return self._queue.get(timeout=self._timeout)

    def putback(self, conn: pymysql.Connection) -> None:
        """Return a connection to the pool."""
        if self.closed:
            self.discard(conn)
            return
        try:
            self._queue.put_nowait(conn)
        except queue.Full:
            self.discard(conn)

    def discard(self, conn: pymysql.Connection) -> None:
        """Close an unsafe connection and release one pool slot."""
        with self._lock:
            self._created = max(0, self._created - 1)
        try:
            conn.close()
        except Exception:
            logger.warning("mysql_connection_close_failed")

    def close(self) -> None:
        """标记池已关闭并关闭池中全部空闲连接。"""
        self.closed = True
        while True:
            try:
                conn = self._queue.get_nowait()
            except queue.Empty:
                break
            self.discard(conn)


# ── MySQL session helpers ────────────────────────────────────────


def _start_mysql_read_only_transaction(conn: pymysql.Connection) -> None:
    """Atomically start a read-only transaction or propagate failure."""
    with conn.cursor() as cursor:
        cursor.execute("START TRANSACTION READ ONLY")


def _rollback_or_discard(
    pool: _ConnectionPool,
    conn: pymysql.Connection,
) -> Exception | None:
    try:
        conn.rollback()
    except Exception as error:
        pool.discard(conn)
        return error
    return None


def _set_mysql_timeout(
    conn: pymysql.Connection,
    timeout_seconds: float,
) -> None:
    """Set ``max_execution_time`` for the session (MySQL 5.7.8+)."""
    whole_ms = max(1, int(math.ceil(timeout_seconds * 1000)))
    with conn.cursor() as cursor:
        cursor.execute("SET SESSION max_execution_time = %s", (whole_ms,))


# ── Operation helpers ────────────────────────────────────────────


def _operation_timeout(
    timeout_seconds: float | None,
) -> tuple[float, float | None]:
    if (
        timeout_seconds is not None
        and (
            type(timeout_seconds) not in (int, float)
            or not math.isfinite(float(timeout_seconds))
            or timeout_seconds <= 0
        )
    ):
        raise ValueError("database timeout is invalid")
    return (
        time.monotonic(),
        float(timeout_seconds) if timeout_seconds is not None else None,
    )


def _timeout_error() -> DatabaseConnectorError:
    return DatabaseConnectorError(
        DatabaseError(
            sqlstate="MY-03024",
            error_type=ErrorType.TIMEOUT,
            code="DB_TIMEOUT",
            retryable=False,
            public_message="The database query timed out.",
        )
    )


def _remaining_timeout(
    *,
    operation_started_at: float,
    timeout_seconds: float,
    maximum_seconds: float | None = None,
) -> float:
    remaining = timeout_seconds - (time.monotonic() - operation_started_at)
    if remaining < 0.001:
        raise _timeout_error() from None
    return (
        remaining
        if maximum_seconds is None
        else min(float(maximum_seconds), remaining)
    )


def _validate_pool_sizes(min_size: int, max_size: int) -> None:
    if min_size < 1:
        raise ValueError("min_pool_size must be >= 1")
    if max_size < 1:
        raise ValueError("max_pool_size must be >= 1")
    if min_size > max_size:
        raise ValueError("min_pool_size cannot exceed max_pool_size")


# ── Execution helpers ────────────────────────────────────────────


def _execute_from_connection(
    conn: pymysql.Connection,
    sql: str,
    *,
    max_result_rows: int,
    dialect: str,
) -> ExecutionResult:
    started = time.perf_counter()
    with conn.cursor() as cursor:
        cursor.execute(sql)
        raw_rows = cursor.fetchmany(max_result_rows + 1)
    elapsed_ms = (time.perf_counter() - started) * 1000

    if cursor.description is None:
        raise DatabaseConnectorError(
            DatabaseError(
                sqlstate=None,
                error_type=ErrorType.UNKNOWN,
                code="DB_UNKNOWN",
                retryable=False,
                public_message="The database operation failed.",
            )
        )

    truncated = len(raw_rows) > max_result_rows
    bounded_rows = raw_rows[:max_result_rows]
    columns = tuple(
        ResultColumn(
            name=column[0],
            type_oid=column[1],
        )
        for column in cursor.description
    )
    rows = [
        [normalize_value(value, dialect=dialect) for value in row]
        for row in bounded_rows
    ]
    return ExecutionResult(
        columns=columns,
        rows=rows,
        returned_row_count=len(rows),
        truncated=truncated,
        execution_time_ms=elapsed_ms,
    )


# ── Metadata reading ─────────────────────────────────────────────


def _read_metadata_from_connection(
    conn: pymysql.Connection,
    scope: MetadataScope,
    *,
    dialect: str,
) -> SchemaSnapshot:
    schema_list = list(scope.schemas)
    table_list = scope.table_parameters
    queries = build_metadata_queries(
        schema_count=len(schema_list),
        table_count=len(table_list),
    )

    # Build flattened parameters — each IN clause gets its own set of
    # placeholders and values.
    flat_params_columns = tuple(schema_list + table_list)
    flat_params_keys = tuple(schema_list + table_list)
    flat_params_fk = tuple(schema_list + table_list)
    flat_params_ui = tuple(schema_list + table_list)

    with conn.cursor() as cursor:
        cursor.execute(queries["table_columns"], flat_params_columns)
        table_rows = cursor.fetchall()

        cursor.execute(queries["primary_keys"], flat_params_keys)
        key_rows = cursor.fetchall()

        cursor.execute(queries["foreign_keys"], flat_params_fk)
        foreign_key_rows = cursor.fetchall()

        cursor.execute(queries["unique_indexes"], flat_params_ui)
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
            if row[1] is not None  # skip empty FK result rows
            and (str(row[1]), str(row[2])) in authorized
            and (str(row[4]), str(row[5])) in authorized
        ]
    )
    unique_indexes = _map_unique_indexes_mysql(
        [
            row
            for row in unique_index_rows
            if row[0] is not None  # skip empty result rows
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


# ── MySQL-specific mapping adapters ──────────────────────────────
# MySQL metadata query results have the same column layout as
# PostgreSQL, with two differences:
# 1. constraint_kind is "PRIMARY KEY" / "UNIQUE" instead of "p"/"u"
# 2. unique_index columns is a GROUP_CONCAT string, not an array


def _map_tables_mysql(
    rows: list[tuple[object, ...]],
) -> tuple[TableMetadata, ...]:
    grouped: dict[
        tuple[str, str],
        tuple[str, str | None, list[ColumnMetadata]],
    ] = {}
    for row in rows:
        schema_name = str(row[0])
        table_name = str(row[1])
        table_key = (schema_name, table_name)
        relation_kind = str(row[2])
        table_comment = None if row[3] is None else str(row[3])
        column = ColumnMetadata(
            schema_name=schema_name,
            table_name=table_name,
            column_name=str(row[4]),
            ordinal_position=int(row[5]),
            data_type=str(row[6]),
            formatted_type=str(row[7]),
            nullable=bool(row[8]),
            comment=None if row[9] is None else str(row[9]),
        )
        if table_key not in grouped:
            grouped[table_key] = (relation_kind, table_comment, [column])
        else:
            relation, comment, columns = grouped[table_key]
            if relation != relation_kind or comment != table_comment:
                raise _metadata_schema_error()
            if any(
                existing.ordinal_position == column.ordinal_position
                for existing in columns
            ):
                raise _metadata_schema_error()
            grouped[table_key][2].append(column)

    return tuple(
        TableMetadata(
            schema_name=schema_name,
            table_name=table_name,
            relation_kind=relation_kind,
            comment=comment,
            columns=tuple(columns),
        )
        for (schema_name, table_name), (
            relation_kind,
            comment,
            columns,
        ) in grouped.items()
    )


def _map_keys_mysql(
    rows: list[tuple[object, ...]],
) -> tuple[
    tuple[PrimaryKeyMetadata, ...],
    tuple[UniqueConstraintMetadata, ...],
]:
    grouped: dict[
        tuple[str, str, str, str],
        list[tuple[int, str]],
    ] = {}
    for row in rows:
        constraint_kind_raw = str(row[1]).upper()
        if constraint_kind_raw == "PRIMARY KEY":
            kind = "p"
        elif constraint_kind_raw == "UNIQUE":
            kind = "u"
        else:
            continue  # skip unknown constraint types

        key = (
            kind,
            str(row[2]),
            str(row[3]),
            str(row[0]),
        )
        grouped.setdefault(key, []).append(
            (int(row[5]), str(row[4]))
        )

    primary_keys: list[PrimaryKeyMetadata] = []
    unique_constraints: list[UniqueConstraintMetadata] = []
    for (
        kind,
        schema_name,
        table_name,
        constraint_name,
    ), positioned_columns in grouped.items():
        columns = _ordered_columns(positioned_columns)
        if kind == "p":
            primary_keys.append(
                PrimaryKeyMetadata(
                    constraint_name=constraint_name,
                    schema_name=schema_name,
                    table_name=table_name,
                    columns=columns,
                )
            )
        elif kind == "u":
            unique_constraints.append(
                UniqueConstraintMetadata(
                    constraint_name=constraint_name,
                    schema_name=schema_name,
                    table_name=table_name,
                    columns=columns,
                )
            )
        else:
            raise _metadata_schema_error()
    return tuple(primary_keys), tuple(unique_constraints)


def _map_unique_indexes_mysql(
    rows: list[tuple[object, ...]],
) -> tuple[UniqueIndexMetadata, ...]:
    unique_indexes: list[UniqueIndexMetadata] = []
    for row in rows:
        raw_columns = row[3]
        if raw_columns is None:
            continue
        if isinstance(raw_columns, (list, tuple)):
            columns = tuple(str(c) for c in raw_columns)
        elif isinstance(raw_columns, str):
            columns = tuple(
                c.strip() for c in raw_columns.split(",") if c.strip()
            )
        else:
            raise _metadata_schema_error()
        if not columns:
            continue
        definition = None if row[4] is None else str(row[4])
        predicate = None if row[5] is None else str(row[5])
        unique_indexes.append(
            UniqueIndexMetadata(
                index_name=str(row[0]),
                schema_name=str(row[1]),
                table_name=str(row[2]),
                columns=columns,
                definition=definition if definition else "",
                predicate=predicate,
            )
        )
    return tuple(unique_indexes)


# ── Shared mapping functions (column layout compatible) ──────────


def _map_foreign_keys(
    rows: list[tuple[object, ...]],
) -> tuple[ForeignKeyMetadata, ...]:
    grouped: dict[
        tuple[str, str, str, str, str],
        list[tuple[int, str, str]],
    ] = {}
    for row in rows:
        key = (
            str(row[1]),
            str(row[2]),
            str(row[0]),
            str(row[4]),
            str(row[5]),
        )
        grouped.setdefault(key, []).append(
            (int(row[7]), str(row[3]), str(row[6]))
        )

    foreign_keys: list[ForeignKeyMetadata] = []
    for (
        source_schema,
        source_table,
        constraint_name,
        target_schema,
        target_table,
    ), positioned_pairs in grouped.items():
        positions = [pos for pos, _, _ in positioned_pairs]
        if not positions or len(positions) != len(set(positions)):
            raise _metadata_schema_error()
        ordered_pairs = sorted(positioned_pairs, key=lambda item: item[0])
        foreign_keys.append(
            ForeignKeyMetadata(
                constraint_name=constraint_name,
                source_schema=source_schema,
                source_table=source_table,
                source_columns=tuple(
                    src for _, src, _ in ordered_pairs
                ),
                target_schema=target_schema,
                target_table=target_table,
                target_columns=tuple(
                    tgt for _, _, tgt in ordered_pairs
                ),
            )
        )
    return tuple(foreign_keys)


def _ordered_columns(
    positioned_columns: list[tuple[int, str]],
) -> tuple[str, ...]:
    positions = [pos for pos, _ in positioned_columns]
    if not positions or len(positions) != len(set(positions)):
        raise _metadata_schema_error()
    return tuple(
        col
        for _, col in sorted(positioned_columns, key=lambda item: item[0])
    )


def _validate_metadata_references(
    *,
    tables: tuple[TableMetadata, ...],
    primary_keys: tuple[PrimaryKeyMetadata, ...],
    foreign_keys: tuple[ForeignKeyMetadata, ...],
    unique_constraints: tuple[UniqueConstraintMetadata, ...],
    unique_indexes: tuple[UniqueIndexMetadata, ...],
) -> None:
    table_identities = {
        (table.schema_name, table.table_name) for table in tables
    }
    column_identities = {
        (col.schema_name, col.table_name, col.column_name)
        for table in tables
        for col in table.columns
    }

    for key in (*primary_keys, *unique_constraints, *unique_indexes):
        table_identity = (key.schema_name, key.table_name)
        if table_identity not in table_identities or any(
            (key.schema_name, key.table_name, column)
            not in column_identities
            for column in key.columns
        ):
            raise _metadata_schema_error()

    for fk in foreign_keys:
        source_table = (fk.source_schema, fk.source_table)
        target_table = (fk.target_schema, fk.target_table)
        if (
            source_table not in table_identities
            or target_table not in table_identities
            or len(fk.source_columns) != len(fk.target_columns)
            or any(
                (fk.source_schema, fk.source_table, col)
                not in column_identities
                for col in fk.source_columns
            )
            or any(
                (fk.target_schema, fk.target_table, col)
                not in column_identities
                for col in fk.target_columns
            )
        ):
            raise _metadata_schema_error()


def _metadata_schema_error() -> DatabaseConnectorError:
    return DatabaseConnectorError(
        DatabaseError(
            sqlstate=None,
            error_type=ErrorType.SCHEMA_ERROR,
            code="DB_SCHEMA_ERROR",
            retryable=False,
            public_message="The database metadata snapshot is inconsistent.",
        )
    )
