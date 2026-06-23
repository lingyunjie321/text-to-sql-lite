from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import create_engine, inspect
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError


class ColumnMetadata(BaseModel):
    """数据库 introspection 返回的列元数据。"""

    name: str
    type: str
    description: str | None = None
    nullable: bool
    default: Any = None
    primary_key: bool = False


class ForeignKeyMetadata(BaseModel):
    """外键关系元数据。"""

    name: str | None = None
    constrained_columns: list[str]
    referred_table: str
    referred_columns: list[str]


class TableMetadata(BaseModel):
    """包含字段和键关系的表元数据。"""

    name: str
    description: str | None = None
    columns: dict[str, ColumnMetadata] = Field(default_factory=dict)
    primary_key: list[str] = Field(default_factory=list)
    foreign_keys: list[ForeignKeyMetadata] = Field(default_factory=list)


class DatabaseSchemaMetadata(BaseModel):
    """数据库连接的完整 Schema 元数据。"""

    database_url: str
    tables: dict[str, TableMetadata] = Field(default_factory=dict)


def read_schema_metadata(database_url: str) -> DatabaseSchemaMetadata:
    """从数据库读取表、列、主键和外键元数据。"""
    engine = create_engine(database_url)
    inspector = inspect(engine)
    tables: dict[str, TableMetadata] = {}

    try:
        for table_name in sorted(inspector.get_table_names()):
            primary_key = inspector.get_pk_constraint(table_name).get("constrained_columns") or []
            columns = {
                column["name"]: ColumnMetadata(
                    name=column["name"],
                    type=str(column["type"]),
                    nullable=bool(column["nullable"]),
                    default=column.get("default"),
                    primary_key=column["name"] in primary_key,
                )
                for column in inspector.get_columns(table_name)
            }
            foreign_keys = [
                ForeignKeyMetadata(
                    name=foreign_key.get("name"),
                    constrained_columns=list(foreign_key.get("constrained_columns") or []),
                    referred_table=str(foreign_key.get("referred_table")),
                    referred_columns=list(foreign_key.get("referred_columns") or []),
                )
                for foreign_key in inspector.get_foreign_keys(table_name)
            ]
            tables[table_name] = TableMetadata(
                name=table_name,
                columns=columns,
                primary_key=list(primary_key),
                foreign_keys=foreign_keys,
            )
    finally:
        engine.dispose()

    return DatabaseSchemaMetadata(database_url=_redact_database_url(database_url), tables=tables)


def _redact_database_url(database_url: str) -> str:
    """返回可展示的数据库 URL，避免把密码带入 API 响应或 prompt。"""
    try:
        return make_url(database_url).render_as_string(hide_password=True)
    except ArgumentError:
        return database_url
