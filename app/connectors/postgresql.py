from __future__ import annotations

import math
import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from types import TracebackType

import psycopg
from psycopg_pool import ConnectionPool

from app.config import DatabaseSettings
from app.connectors.errors import (
    DatabaseError,
    ErrorType,
    PostgreSQLConnectorError,
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
from app.connectors.metadata_queries import (
    FOREIGN_KEYS_SQL,
    KEY_CONSTRAINTS_SQL,
    TABLE_COLUMNS_SQL,
    UNIQUE_INDEXES_SQL,
)
from app.connectors.models import (
    ExecutionResult,
    ResultColumn,
)
from app.connectors.types import normalize_value


class PostgreSQLConnector:
    dialect_name: str = "postgres"

    def __init__(self, settings: DatabaseSettings) -> None:
        self._settings = settings
        self._retry_count: ContextVar[int] = ContextVar(
            f"postgresql_connector_retry_count_{id(self)}",
            default=0,
        )
        self._snapshot_connection: ContextVar[
            psycopg.Connection | None
        ] = ContextVar(
            f"postgresql_connector_snapshot_{id(self)}",
            default=None,
        )
        self._pool = ConnectionPool(
            conninfo=settings.dsn_value,
            min_size=settings.min_pool_size,
            max_size=settings.max_pool_size,
            timeout=settings.pool_timeout_seconds,
            kwargs={"autocommit": False},
            open=False,
        )

    def open(self) -> None:
        if not self._pool.closed:
            return
        self.check_connection()
        try:
            self._pool.open(
                wait=True,
                timeout=self._settings.pool_timeout_seconds,
            )
        except Exception as error:
            raise normalize_database_error(error) from None

    def close(self) -> None:
        if not self._pool.closed:
            self._pool.close()

    def __enter__(self) -> PostgreSQLConnector:
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
        try:
            with psycopg.connect(
                self._settings.dsn_value,
                connect_timeout=max(
                    1, int(self._settings.pool_timeout_seconds)
                ),
            ) as connection:
                connection.execute("SELECT 1")
        except Exception as error:
            raise normalize_database_error(error) from None

    @contextmanager
    def read_only_snapshot(
        self,
    ) -> Iterator[PostgreSQLConnector]:
        if self._snapshot_connection.get() is not None:
            raise ValueError("read-only snapshot is already active")
        body_error: BaseException | None = None
        try:
            with self._pool.connection(
                timeout=self._settings.pool_timeout_seconds
            ) as connection:
                with connection.transaction():
                    connection.execute(
                        "SET TRANSACTION ISOLATION LEVEL "
                        "REPEATABLE READ READ ONLY"
                    )
                    connection.execute(
                        "SELECT set_config('statement_timeout', %s, true)",
                        (
                            f"{self._settings.statement_timeout_seconds}s",
                        ),
                    )
                    token = self._snapshot_connection.set(connection)
                    try:
                        try:
                            yield self
                        except BaseException as error:
                            body_error = error
                            raise
                    finally:
                        self._snapshot_connection.reset(token)
        except BaseException as error:
            if body_error is not None:
                raise body_error
            if not isinstance(error, Exception):
                raise
            raise normalize_database_error(error) from None

    def execute(
        self,
        sql: str,
        *,
        timeout_seconds: float | None = None,
    ) -> ExecutionResult:
        operation_started_at, timeout = _operation_timeout(
            timeout_seconds
        )
        self._retry_count.set(0)
        for retry_index in range(
            self._settings.connection_retry_count + 1
        ):
            self._retry_count.set(retry_index)
            try:
                if timeout is None:
                    return self._execute_once(sql)
                return self._execute_once(
                    sql,
                    timeout_seconds=_remaining_timeout(
                        operation_started_at=(
                            operation_started_at
                        ),
                        timeout_seconds=timeout,
                    ),
                )
            except Exception as error:
                normalized = normalize_database_error(error)
                if (
                    not normalized.details.retryable
                    or retry_index
                    >= self._settings.connection_retry_count
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
        operation_started_at, timeout = _operation_timeout(
            timeout_seconds
        )
        self._retry_count.set(0)
        scope = normalize_metadata_scope(
            allowed_schemas,
            allowed_tables,
        )
        if scope.is_empty:
            return empty_schema_snapshot()

        for retry_index in range(
            self._settings.connection_retry_count + 1
        ):
            self._retry_count.set(retry_index)
            try:
                if timeout is None:
                    return self._read_metadata_once(scope)
                return self._read_metadata_once(
                    scope,
                    timeout_seconds=_remaining_timeout(
                        operation_started_at=(
                            operation_started_at
                        ),
                        timeout_seconds=timeout,
                    ),
                )
            except Exception as error:
                normalized = normalize_database_error(error)
                if (
                    not normalized.details.retryable
                    or retry_index
                    >= self._settings.connection_retry_count
                ):
                    raise normalized from None
        raise AssertionError("unreachable")

    def _consume_retry_count(self) -> int:
        retry_count = self._retry_count.get()
        self._retry_count.set(0)
        return retry_count

    def _read_metadata_once(
        self,
        scope: MetadataScope,
        *,
        timeout_seconds: float | None = None,
    ) -> SchemaSnapshot:
        try:
            operation_started_at, timeout = _operation_timeout(
                timeout_seconds
            )
            snapshot_connection = self._snapshot_connection.get()
            if snapshot_connection is not None:
                if timeout is not None:
                    _set_statement_timeout(
                        snapshot_connection,
                        _remaining_timeout(
                            operation_started_at=(
                                operation_started_at
                            ),
                            timeout_seconds=timeout,
                            maximum_seconds=(
                                self._settings
                                .statement_timeout_seconds
                            ),
                        ),
                    )
                return _read_metadata_from_connection(
                    snapshot_connection,
                    scope,
                )
            with self._pool.connection(
                timeout=(
                    self._settings.pool_timeout_seconds
                    if timeout is None
                    else _remaining_timeout(
                        operation_started_at=(
                            operation_started_at
                        ),
                        timeout_seconds=timeout,
                        maximum_seconds=(
                            self._settings.pool_timeout_seconds
                        ),
                    )
                )
            ) as connection:
                with connection.transaction():
                    connection.execute("SET TRANSACTION READ ONLY")
                    _set_statement_timeout(
                        connection,
                        (
                            float(
                                self._settings
                                .statement_timeout_seconds
                            )
                            if timeout is None
                            else _remaining_timeout(
                                operation_started_at=(
                                    operation_started_at
                                ),
                                timeout_seconds=timeout,
                                maximum_seconds=(
                                    self._settings
                                    .statement_timeout_seconds
                                ),
                            )
                        ),
                    )
                    return _read_metadata_from_connection(
                        connection,
                        scope,
                    )
        except Exception as error:
            raise normalize_database_error(error) from None

    def _execute_once(
        self,
        sql: str,
        *,
        timeout_seconds: float | None = None,
    ) -> ExecutionResult:
        try:
            operation_started_at, timeout = _operation_timeout(
                timeout_seconds
            )
            snapshot_connection = self._snapshot_connection.get()
            if snapshot_connection is not None:
                with snapshot_connection.transaction():
                    if timeout is not None:
                        _set_statement_timeout(
                            snapshot_connection,
                            _remaining_timeout(
                                operation_started_at=(
                                    operation_started_at
                                ),
                                timeout_seconds=timeout,
                                maximum_seconds=(
                                    self._settings
                                    .statement_timeout_seconds
                                ),
                            ),
                        )
                    return _execute_from_connection(
                        snapshot_connection,
                        sql,
                        max_result_rows=self._settings.max_result_rows,
                    )
            with self._pool.connection(
                timeout=(
                    self._settings.pool_timeout_seconds
                    if timeout is None
                    else _remaining_timeout(
                        operation_started_at=(
                            operation_started_at
                        ),
                        timeout_seconds=timeout,
                        maximum_seconds=(
                            self._settings.pool_timeout_seconds
                        ),
                    )
                )
            ) as connection:
                with connection.transaction():
                    connection.execute("SET TRANSACTION READ ONLY")
                    _set_statement_timeout(
                        connection,
                        (
                            float(
                                self._settings
                                .statement_timeout_seconds
                            )
                            if timeout is None
                            else _remaining_timeout(
                                operation_started_at=(
                                    operation_started_at
                                ),
                                timeout_seconds=timeout,
                                maximum_seconds=(
                                    self._settings
                                    .statement_timeout_seconds
                                ),
                            )
                        ),
                    )
                    return _execute_from_connection(
                        connection,
                        sql,
                        max_result_rows=self._settings.max_result_rows,
                    )
        except Exception as error:
            raise normalize_database_error(error) from None


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
        (
            float(timeout_seconds)
            if timeout_seconds is not None
            else None
        ),
    )


def _timeout_error() -> PostgreSQLConnectorError:
    return PostgreSQLConnectorError(
        DatabaseError(
            sqlstate="57014",
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
    remaining = timeout_seconds - (
        time.monotonic() - operation_started_at
    )
    if remaining < 0.001:
        raise _timeout_error() from None
    return (
        remaining
        if maximum_seconds is None
        else min(float(maximum_seconds), remaining)
    )


def _set_statement_timeout(
    connection: psycopg.Connection,
    timeout_seconds: float,
) -> None:
    whole_seconds = int(timeout_seconds)
    value = (
        f"{whole_seconds}s"
        if timeout_seconds == whole_seconds
        else f"{max(1, math.floor(timeout_seconds * 1000))}ms"
    )
    connection.execute(
        "SELECT set_config('statement_timeout', %s, true)",
        (value,),
    )


def _read_metadata_from_connection(
    connection: psycopg.Connection,
    scope: MetadataScope,
) -> SchemaSnapshot:
    params = (
        scope.schema_parameters,
        scope.table_parameters,
    )
    table_rows = connection.execute(
        TABLE_COLUMNS_SQL, params
    ).fetchall()
    key_rows = connection.execute(
        KEY_CONSTRAINTS_SQL, params
    ).fetchall()
    foreign_key_rows = connection.execute(
        FOREIGN_KEYS_SQL, params
    ).fetchall()
    unique_index_rows = connection.execute(
        UNIQUE_INDEXES_SQL, params
    ).fetchall()
    authorized = set(scope.table_pairs)
    tables = _map_tables(
        [
            row
            for row in table_rows
            if (str(row[0]), str(row[1])) in authorized
        ]
    )
    primary_keys, unique_constraints = _map_keys(
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
            if (
                (str(row[1]), str(row[2])) in authorized
                and (str(row[4]), str(row[5])) in authorized
            )
        ]
    )
    unique_indexes = _map_unique_indexes(
        [
            row
            for row in unique_index_rows
            if (str(row[1]), str(row[2])) in authorized
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


def _execute_from_connection(
    connection: psycopg.Connection,
    sql: str,
    *,
    max_result_rows: int,
) -> ExecutionResult:
    started = time.perf_counter()
    cursor = connection.execute(sql)
    raw_rows = cursor.fetchmany(max_result_rows + 1)
    elapsed_ms = (time.perf_counter() - started) * 1000
    if cursor.description is None:
        raise PostgreSQLConnectorError(
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
            name=column.name,
            type_oid=int(column.type_code),
        )
        for column in cursor.description
    )
    rows = [
        [normalize_value(value, dialect="postgres") for value in row]
        for row in bounded_rows
    ]
    return ExecutionResult(
        columns=columns,
        rows=rows,
        returned_row_count=len(rows),
        truncated=truncated,
        execution_time_ms=elapsed_ms,
    )


def _map_tables(
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
            grouped[table_key] = (
                relation_kind,
                table_comment,
                [column],
            )
        else:
            relation, comment, columns = grouped[table_key]
            if relation != relation_kind or comment != table_comment:
                raise _metadata_schema_error()
            if any(
                existing.ordinal_position
                == column.ordinal_position
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


def _map_keys(
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
        key = (
            str(row[1]),
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
        positions = [position for position, _, _ in positioned_pairs]
        if not positions or len(positions) != len(set(positions)):
            raise _metadata_schema_error()
        ordered_pairs = sorted(
            positioned_pairs,
            key=lambda item: item[0],
        )
        foreign_keys.append(
            ForeignKeyMetadata(
                constraint_name=constraint_name,
                source_schema=source_schema,
                source_table=source_table,
                source_columns=tuple(
                    source_column
                    for _, source_column, _ in ordered_pairs
                ),
                target_schema=target_schema,
                target_table=target_table,
                target_columns=tuple(
                    target_column
                    for _, _, target_column in ordered_pairs
                ),
            )
        )
    return tuple(foreign_keys)


def _map_unique_indexes(
    rows: list[tuple[object, ...]],
) -> tuple[UniqueIndexMetadata, ...]:
    unique_indexes: list[UniqueIndexMetadata] = []
    for row in rows:
        raw_columns = row[3]
        if not isinstance(raw_columns, (list, tuple)):
            raise _metadata_schema_error()
        columns = tuple(str(column) for column in raw_columns)
        if not columns:
            raise _metadata_schema_error()
        unique_indexes.append(
            UniqueIndexMetadata(
                index_name=str(row[0]),
                schema_name=str(row[1]),
                table_name=str(row[2]),
                columns=columns,
                definition=str(row[4]),
                predicate=None if row[5] is None else str(row[5]),
            )
        )
    return tuple(unique_indexes)


def _ordered_columns(
    positioned_columns: list[tuple[int, str]],
) -> tuple[str, ...]:
    positions = [position for position, _ in positioned_columns]
    if not positions or len(positions) != len(set(positions)):
        raise _metadata_schema_error()
    return tuple(
        column
        for _, column in sorted(
            positioned_columns,
            key=lambda item: item[0],
        )
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
        (table.schema_name, table.table_name)
        for table in tables
    }
    column_identities = {
        (
            column.schema_name,
            column.table_name,
            column.column_name,
        )
        for table in tables
        for column in table.columns
    }

    for key in (*primary_keys, *unique_constraints, *unique_indexes):
        table_identity = (key.schema_name, key.table_name)
        if table_identity not in table_identities or any(
            (key.schema_name, key.table_name, column)
            not in column_identities
            for column in key.columns
        ):
            raise _metadata_schema_error()

    for foreign_key in foreign_keys:
        source_table = (
            foreign_key.source_schema,
            foreign_key.source_table,
        )
        target_table = (
            foreign_key.target_schema,
            foreign_key.target_table,
        )
        if (
            source_table not in table_identities
            or target_table not in table_identities
            or len(foreign_key.source_columns)
            != len(foreign_key.target_columns)
            or any(
                (
                    foreign_key.source_schema,
                    foreign_key.source_table,
                    column,
                )
                not in column_identities
                for column in foreign_key.source_columns
            )
            or any(
                (
                    foreign_key.target_schema,
                    foreign_key.target_table,
                    column,
                )
                not in column_identities
                for column in foreign_key.target_columns
            )
        ):
            raise _metadata_schema_error()


def _metadata_schema_error() -> PostgreSQLConnectorError:
    return PostgreSQLConnectorError(
        DatabaseError(
            sqlstate=None,
            error_type=ErrorType.SCHEMA_ERROR,
            code="DB_SCHEMA_ERROR",
            retryable=False,
            public_message=(
                "The database metadata snapshot is inconsistent."
            ),
        )
    )
