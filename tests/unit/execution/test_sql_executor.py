from pathlib import Path

from text_to_sql_demo.db.init_db import initialize_database
from text_to_sql_demo.execution.sql_executor import SQLExecutor


def make_database_url(tmp_path: Path) -> str:
    db_path = tmp_path / "demo.db"
    initialize_database(db_path)
    return f"sqlite:///{db_path}"


def test_sql_executor_returns_columns_rows_and_duration(tmp_path: Path) -> None:
    result = SQLExecutor().execute(
        sql="SELECT id, amount FROM orders ORDER BY id",
        database_url=make_database_url(tmp_path),
        max_rows=2,
    )

    assert result.success is True
    assert result.columns == ["id", "amount"]
    assert len(result.rows) == 2
    assert result.duration_ms >= 0
    assert result.error is None


def test_sql_executor_converts_database_error(tmp_path: Path) -> None:
    result = SQLExecutor().execute(
        sql="SELECT * FROM missing_orders",
        database_url=make_database_url(tmp_path),
        max_rows=10,
    )

    assert result.success is False
    assert result.error is not None
    assert result.error.category == "execution_error"
    assert "missing_orders" in (result.error.raw_message or "")
