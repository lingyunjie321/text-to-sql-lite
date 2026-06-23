from time import perf_counter

from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

from text_to_sql_demo.sql.models import SQLError, SQLExecutionResult


class SQLExecutor:
    """使用 SQLAlchemy 执行只读 SQL 并归一化结果。"""

    def execute(self, *, sql: str, database_url: str, max_rows: int) -> SQLExecutionResult:
        started = perf_counter()
        engine = create_engine(database_url)
        try:
            with engine.connect() as connection:
                result = connection.execute(text(sql))
                rows = [dict(row._mapping) for row in result.fetchmany(max_rows)]
                return SQLExecutionResult(
                    success=True,
                    columns=list(result.keys()),
                    rows=rows,
                    duration_ms=int((perf_counter() - started) * 1000),
                )
        except SQLAlchemyError as exc:
            return SQLExecutionResult(
                success=False,
                duration_ms=int((perf_counter() - started) * 1000),
                error=SQLError(
                    category="execution_error",
                    message="SQL 执行失败",
                    raw_message=str(exc),
                ),
            )
        finally:
            engine.dispose()
