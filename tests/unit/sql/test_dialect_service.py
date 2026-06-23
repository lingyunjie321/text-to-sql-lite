import pytest

from text_to_sql_demo.sql.dialect import DialectService


def test_dialect_service_supports_required_dialects() -> None:
    service = DialectService()

    assert service.normalize("SELECT 1", dialect="sqlite").normalized_sql == "SELECT 1"
    assert service.normalize("SELECT 1", dialect="postgres").normalized_sql == "SELECT 1"
    assert service.normalize("SELECT 1", dialect="mysql").normalized_sql == "SELECT 1"

    with pytest.raises(ValueError, match="不支持的 SQL 方言"):
        service.normalize("SELECT 1", dialect="oracle")


def test_transpile_date_function_from_mysql_to_postgres() -> None:
    result = DialectService().transpile(
        sql="SELECT DATE_FORMAT(order_date, '%Y-%m-%d') FROM orders",
        source_dialect="mysql",
        target_dialect="postgres",
    )

    assert result.normalized_sql == "SELECT DATE_FORMAT(order_date, '%Y-%m-%d') FROM orders"
    assert (
        result.rendered_sql
        == "SELECT TO_CHAR(CAST(order_date AS TIMESTAMP), 'YYYY-MM-DD') FROM orders"
    )


def test_transpile_string_concat_from_postgres_to_mysql() -> None:
    result = DialectService().transpile(
        sql="SELECT name || email AS label FROM customers",
        source_dialect="postgres",
        target_dialect="mysql",
    )

    assert result.rendered_sql == "SELECT CONCAT(name, email) AS label FROM customers"


def test_transpile_mysql_pagination_to_postgres() -> None:
    result = DialectService().transpile(
        sql="SELECT * FROM orders LIMIT 20, 10",
        source_dialect="mysql",
        target_dialect="postgres",
    )

    assert result.rendered_sql == "SELECT * FROM orders LIMIT 10 OFFSET 20"
