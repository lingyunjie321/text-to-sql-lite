from __future__ import annotations

import argparse
from collections.abc import Sequence
from datetime import date, datetime
from pathlib import Path

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    MetaData,
    Numeric,
    String,
    Table,
    create_engine,
    text,
)


def build_ecommerce_metadata() -> MetaData:
    """构建 demo 电商 Schema 的 SQLAlchemy Core metadata。"""
    metadata = MetaData()

    Table(
        "regions",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("name", String(80), nullable=False, unique=True),
    )
    Table(
        "customers",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("region_id", Integer, ForeignKey("regions.id"), nullable=False),
        Column("name", String(120), nullable=False),
        Column("email", String(180), nullable=False, unique=True),
        Column("created_at", DateTime, nullable=False),
    )
    Table(
        "products",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("sku", String(40), nullable=False, unique=True),
        Column("name", String(160), nullable=False),
        Column("category", String(80), nullable=False),
        Column("unit_price", Numeric(10, 2), nullable=False),
        Column("active", Boolean, nullable=False),
    )
    Table(
        "orders",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("customer_id", Integer, ForeignKey("customers.id"), nullable=False),
        Column("order_date", Date, nullable=False),
        Column("status", String(40), nullable=False),
        Column("amount", Numeric(10, 2), nullable=False),
    )
    Table(
        "order_items",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("order_id", Integer, ForeignKey("orders.id"), nullable=False),
        Column("product_id", Integer, ForeignKey("products.id"), nullable=False),
        Column("quantity", Integer, nullable=False),
        Column("unit_price", Numeric(10, 2), nullable=False),
        Column("line_total", Numeric(10, 2), nullable=False),
    )

    return metadata


def initialize_database(db_path: str | Path, *, reset: bool = True) -> Path:
    """创建可重复生成的 SQLite 电商数据库，并写入 demo 数据。"""
    database_path = Path(db_path)
    database_path.parent.mkdir(parents=True, exist_ok=True)
    if reset and database_path.exists():
        database_path.unlink()

    engine = create_engine(f"sqlite:///{database_path}")
    metadata = build_ecommerce_metadata()
    metadata.create_all(engine)

    with engine.begin() as connection:
        connection.execute(text("PRAGMA foreign_keys=ON"))
        _seed_database(metadata, connection)

    engine.dispose()
    return database_path


def _seed_database(metadata: MetaData, connection) -> None:  # type: ignore[no-untyped-def]
    regions = metadata.tables["regions"]
    customers = metadata.tables["customers"]
    products = metadata.tables["products"]
    orders = metadata.tables["orders"]
    order_items = metadata.tables["order_items"]

    connection.execute(
        regions.insert(),
        [
            {"id": 1, "name": "North America"},
            {"id": 2, "name": "Europe"},
            {"id": 3, "name": "Asia Pacific"},
        ],
    )
    connection.execute(
        customers.insert(),
        [
            {
                "id": 1,
                "region_id": 1,
                "name": "Ava Chen",
                "email": "ava.chen@example.com",
                "created_at": datetime(2024, 1, 5, 10, 30),
            },
            {
                "id": 2,
                "region_id": 2,
                "name": "Noah Smith",
                "email": "noah.smith@example.com",
                "created_at": datetime(2024, 2, 12, 9, 15),
            },
            {
                "id": 3,
                "region_id": 3,
                "name": "Mia Tanaka",
                "email": "mia.tanaka@example.com",
                "created_at": datetime(2024, 3, 20, 14, 45),
            },
        ],
    )
    connection.execute(
        products.insert(),
        [
            {
                "id": 1,
                "sku": "KBD-001",
                "name": "Mechanical Keyboard",
                "category": "Accessories",
                "unit_price": 129.99,
                "active": True,
            },
            {
                "id": 2,
                "sku": "MSE-002",
                "name": "Wireless Mouse",
                "category": "Accessories",
                "unit_price": 49.99,
                "active": True,
            },
            {
                "id": 3,
                "sku": "MON-027",
                "name": "27 Inch Monitor",
                "category": "Displays",
                "unit_price": 299.99,
                "active": True,
            },
            {
                "id": 4,
                "sku": "USB-010",
                "name": "USB-C Hub",
                "category": "Adapters",
                "unit_price": 79.99,
                "active": True,
            },
        ],
    )
    connection.execute(
        orders.insert(),
        [
            {
                "id": 1,
                "customer_id": 1,
                "order_date": date(2024, 4, 1),
                "status": "paid",
                "amount": 179.98,
            },
            {
                "id": 2,
                "customer_id": 2,
                "order_date": date(2024, 4, 3),
                "status": "shipped",
                "amount": 299.99,
            },
            {
                "id": 3,
                "customer_id": 3,
                "order_date": date(2024, 4, 8),
                "status": "paid",
                "amount": 209.98,
            },
        ],
    )
    connection.execute(
        order_items.insert(),
        [
            {
                "id": 1,
                "order_id": 1,
                "product_id": 1,
                "quantity": 1,
                "unit_price": 129.99,
                "line_total": 129.99,
            },
            {
                "id": 2,
                "order_id": 1,
                "product_id": 2,
                "quantity": 1,
                "unit_price": 49.99,
                "line_total": 49.99,
            },
            {
                "id": 3,
                "order_id": 2,
                "product_id": 3,
                "quantity": 1,
                "unit_price": 299.99,
                "line_total": 299.99,
            },
            {
                "id": 4,
                "order_id": 3,
                "product_id": 4,
                "quantity": 2,
                "unit_price": 79.99,
                "line_total": 159.98,
            },
            {
                "id": 5,
                "order_id": 3,
                "product_id": 2,
                "quantity": 1,
                "unit_price": 49.99,
                "line_total": 49.99,
            },
        ],
    )


def main(argv: Sequence[str] | None = None) -> int:
    """创建 demo SQLite 数据库的 CLI 入口。"""
    parser = argparse.ArgumentParser(description="初始化电商 demo SQLite 数据库。")
    parser.add_argument(
        "--db-path",
        type=Path,
        default=Path("data/sqlite/demo.db"),
        help="SQLite 数据库文件路径。",
    )
    parser.add_argument(
        "--keep-existing",
        action="store_true",
        help="创建表前不要删除已有数据库文件。",
    )
    args = parser.parse_args(argv)

    database_path = initialize_database(args.db_path, reset=not args.keep_existing)
    print(f"已初始化电商 demo 数据库：{database_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
