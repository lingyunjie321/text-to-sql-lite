from __future__ import annotations

import time
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
from app.connectors.models import (
    ExecutionResult,
    ResultColumn,
    normalize_value,
)


class PostgreSQLConnector:
    def __init__(self, settings: DatabaseSettings) -> None:
        self._settings = settings
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

    def execute(self, sql: str) -> ExecutionResult:
        for retry_index in range(
            self._settings.connection_retry_count + 1
        ):
            try:
                return self._execute_once(sql)
            except Exception as error:
                normalized = normalize_database_error(error)
                if (
                    not normalized.details.retryable
                    or retry_index
                    >= self._settings.connection_retry_count
                ):
                    raise normalized from None
        raise AssertionError("unreachable")

    def _execute_once(self, sql: str) -> ExecutionResult:
        try:
            with self._pool.connection(
                timeout=self._settings.pool_timeout_seconds
            ) as connection:
                with connection.transaction():
                    connection.execute("SET TRANSACTION READ ONLY")
                    connection.execute(
                        "SELECT set_config('statement_timeout', %s, true)",
                        (
                            f"{self._settings.statement_timeout_seconds}s",
                        ),
                    )
                    started = time.perf_counter()
                    cursor = connection.execute(sql)
                    raw_rows = cursor.fetchmany(
                        self._settings.max_result_rows + 1
                    )
                    elapsed_ms = (
                        time.perf_counter() - started
                    ) * 1000
                    if cursor.description is None:
                        raise PostgreSQLConnectorError(
                            DatabaseError(
                                sqlstate=None,
                                error_type=ErrorType.UNKNOWN,
                                code="DB_UNKNOWN",
                                retryable=False,
                                public_message=(
                                    "The database operation failed."
                                ),
                            )
                        )

                    truncated = (
                        len(raw_rows)
                        > self._settings.max_result_rows
                    )
                    bounded_rows = raw_rows[
                        : self._settings.max_result_rows
                    ]
                    columns = tuple(
                        ResultColumn(
                            name=column.name,
                            type_oid=int(column.type_code),
                        )
                        for column in cursor.description
                    )
                    rows = [
                        [normalize_value(value) for value in row]
                        for row in bounded_rows
                    ]
                    return ExecutionResult(
                        columns=columns,
                        rows=rows,
                        returned_row_count=len(rows),
                        truncated=truncated,
                        execution_time_ms=elapsed_ms,
                    )
        except Exception as error:
            raise normalize_database_error(error) from None
