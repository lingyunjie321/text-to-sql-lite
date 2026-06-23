from pathlib import Path

from sqlalchemy import create_engine, text

from text_to_sql_demo.db.init_db import initialize_database
from text_to_sql_demo.schema.catalog import read_schema_metadata


def test_initialize_database_creates_ecommerce_schema(tmp_path: Path) -> None:
    db_path = tmp_path / "demo.db"

    initialize_database(db_path)

    assert db_path.exists()

    engine = create_engine(f"sqlite:///{db_path}")
    with engine.connect() as connection:
        table_count = connection.execute(
            text("select count(*) from sqlite_master where type = 'table'")
        ).scalar_one()
        customer_count = connection.execute(text("select count(*) from customers")).scalar_one()
        order_item_count = connection.execute(text("select count(*) from order_items")).scalar_one()

    assert table_count >= 5
    assert customer_count >= 3
    assert order_item_count >= 4


def test_schema_metadata_includes_columns_primary_keys_and_foreign_keys(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "demo.db"
    initialize_database(db_path)

    schema = read_schema_metadata(f"sqlite:///{db_path}")

    assert set(schema.tables) == {
        "customers",
        "regions",
        "orders",
        "order_items",
        "products",
    }
    assert schema.tables["customers"].columns["email"].type
    assert schema.tables["customers"].primary_key == ["id"]
    assert schema.tables["orders"].foreign_keys[0].constrained_columns == ["customer_id"]
    assert schema.tables["orders"].foreign_keys[0].referred_table == "customers"
    assert {
        foreign_key.referred_table
        for foreign_key in schema.tables["order_items"].foreign_keys
    } == {"orders", "products"}
