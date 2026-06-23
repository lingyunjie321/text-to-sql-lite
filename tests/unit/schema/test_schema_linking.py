from pathlib import Path

from text_to_sql_demo.db.init_db import initialize_database
from text_to_sql_demo.schema.catalog import read_schema_metadata
from text_to_sql_demo.schema.linking import SchemaLinker


def build_schema(tmp_path: Path):
    db_path = tmp_path / "demo.db"
    initialize_database(db_path)
    return read_schema_metadata(f"sqlite:///{db_path}")


def test_region_order_amount_question_links_regions_customers_orders(tmp_path: Path) -> None:
    schema = build_schema(tmp_path)
    linker = SchemaLinker(top_k_tables=3, max_columns_per_table=6)

    result = linker.link("统计每个地区订单金额", schema)

    table_names = [table.name for table in result.tables]
    assert table_names == ["orders", "regions", "customers"]
    assert all(table.score > 0 for table in result.tables)
    assert all(table.reasons for table in result.tables)
    assert "amount" in result.tables[0].columns


def test_unrelated_product_fields_do_not_dominate_region_order_question(tmp_path: Path) -> None:
    schema = build_schema(tmp_path)
    linker = SchemaLinker(top_k_tables=3, max_columns_per_table=6)

    result = linker.link("统计每个地区订单金额", schema)

    table_names = [table.name for table in result.tables]
    assert "products" not in table_names
    selected_column_names = {
        column_name
        for table in result.tables
        for column_name in table.columns
    }
    assert "sku" not in selected_column_names
    assert "category" not in selected_column_names
