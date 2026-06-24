from pathlib import Path

from text_to_sql_demo.db.init_db import initialize_database
from text_to_sql_demo.schema.catalog import read_schema_metadata
from text_to_sql_demo.sql.validator import SQLValidator


def load_schema(tmp_path: Path) -> dict:
    db_path = tmp_path / "demo.db"
    initialize_database(db_path)
    schema = read_schema_metadata(f"sqlite:///{db_path}")
    return schema.model_dump(mode="python")


def test_validator_accepts_single_readonly_select(tmp_path: Path) -> None:
    result = SQLValidator().validate(
        sql="SELECT id, amount FROM orders",
        schema=load_schema(tmp_path),
        dialect="sqlite",
    )

    assert result.success is True
    assert result.error is None
    assert result.normalized_sql == "SELECT id, amount FROM orders"
    assert result.rendered_sql == "SELECT id, amount FROM orders"


def test_validator_rejects_unknown_table(tmp_path: Path) -> None:
    result = SQLValidator().validate(
        sql="SELECT * FROM missing_orders",
        schema=load_schema(tmp_path),
        dialect="sqlite",
    )

    assert result.success is False
    assert result.error is not None
    assert result.error.category == "unknown_table"
    assert result.error.table == "missing_orders"


def test_validator_parses_target_dialect_date_function(tmp_path: Path) -> None:
    result = SQLValidator().validate(
        sql="SELECT DATE_FORMAT(order_date, '%Y-%m-%d') FROM orders",
        schema=load_schema(tmp_path),
        dialect="mysql",
    )

    assert result.success is True
    assert result.rendered_sql == "SELECT DATE_FORMAT(order_date, '%Y-%m-%d') FROM orders"


def test_validator_rejects_unknown_column(tmp_path: Path) -> None:
    result = SQLValidator().validate(
        sql="SELECT orders.total_amount FROM orders",
        schema=load_schema(tmp_path),
        dialect="sqlite",
    )

    assert result.success is False
    assert result.error is not None
    assert result.error.category == "unknown_column"
    assert result.error.column == "total_amount"


def test_validator_rejects_ambiguous_unqualified_column(tmp_path: Path) -> None:
    result = SQLValidator().validate(
        sql=(
            "SELECT id FROM orders "
            "JOIN customers ON orders.customer_id = customers.id"
        ),
        schema=load_schema(tmp_path),
        dialect="sqlite",
    )

    assert result.success is False
    assert result.error is not None
    assert result.error.category == "ambiguous_column"
    assert result.error.column == "id"


def test_validator_rejects_write_statement(tmp_path: Path) -> None:
    result = SQLValidator().validate(
        sql="DELETE FROM orders",
        schema=load_schema(tmp_path),
        dialect="sqlite",
    )

    assert result.success is False
    assert result.error is not None
    assert result.error.category == "dialect_error"


def test_validator_accepts_single_level_cte_output_columns(tmp_path: Path) -> None:
    result = SQLValidator().validate(
        sql=(
            "WITH monthly AS ("
            "SELECT customer_id, SUM(amount) AS total FROM orders GROUP BY customer_id"
            ") "
            "SELECT customer_id, total FROM monthly"
        ),
        schema=load_schema(tmp_path),
        dialect="sqlite",
    )

    assert result.success is True
    assert result.error is None


def test_validator_rejects_unknown_table_inside_cte(tmp_path: Path) -> None:
    result = SQLValidator().validate(
        sql=(
            "WITH monthly AS ("
            "SELECT customer_id, SUM(amount) AS total FROM missing_orders GROUP BY customer_id"
            ") "
            "SELECT customer_id, total FROM monthly"
        ),
        schema=load_schema(tmp_path),
        dialect="sqlite",
    )

    assert result.success is False
    assert result.error is not None
    assert result.error.category == "unknown_table"
    assert result.error.table == "missing_orders"


def test_validator_rejects_unknown_column_inside_cte(tmp_path: Path) -> None:
    result = SQLValidator().validate(
        sql=(
            "WITH monthly AS ("
            "SELECT customer_id, SUM(missing_amount) AS total FROM orders GROUP BY customer_id"
            ") "
            "SELECT customer_id, total FROM monthly"
        ),
        schema=load_schema(tmp_path),
        dialect="sqlite",
    )

    assert result.success is False
    assert result.error is not None
    assert result.error.category == "unknown_column"
    assert result.error.column == "missing_amount"
