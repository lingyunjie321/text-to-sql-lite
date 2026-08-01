import json
from pathlib import Path
from typing import Self

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

SUPPORTED_DATABASE_TYPES = frozenset({"postgresql", "mysql", "starrocks"})


def _resolve_env_file(env_file: Path | None) -> Path:
    from app.config import _resolved_env_file

    return _resolved_env_file(env_file)


class DatabaseSettings(BaseSettings):
    """Single datasource configuration.

    Supports PostgreSQL via DSN and MySQL/StarRocks via host-based settings.
    """

    model_config = SettingsConfigDict(
        env_prefix="TEXT_TO_SQL_DATABASE_",
        extra="ignore",
    )

    type: str = "postgresql"
    datasource_id: str = "pagila"
    dsn: SecretStr | None = None
    host: str = "127.0.0.1"
    port: int = 5432
    database: str = "pagila"
    username: str = "text_to_sql_reader"
    password: SecretStr | None = None
    min_pool_size: int = Field(default=1, ge=1)
    max_pool_size: int = Field(default=4, ge=1)
    pool_timeout_seconds: float = Field(default=5.0, gt=0)
    statement_timeout_seconds: int = Field(default=30, ge=1, le=30)
    max_result_rows: int = Field(default=1000, ge=1, le=1000)
    connection_retry_count: int = Field(default=1, ge=0, le=3)
    allowed_schemas: tuple[str, ...] = ()
    allowed_tables: tuple[str, ...] = ()

    @property
    def dsn_value(self) -> str | None:
        if self.dsn is None:
            return None
        return self.dsn.get_secret_value()

    @property
    def password_value(self) -> str | None:
        if self.password is None:
            return None
        return self.password.get_secret_value()

    @model_validator(mode="after")
    def validate_database(self) -> Self:
        if self.min_pool_size > self.max_pool_size:
            raise ValueError("min_pool_size cannot exceed max_pool_size")
        if self.type not in SUPPORTED_DATABASE_TYPES:
            raise ValueError(
                f"database type must be one of {sorted(SUPPORTED_DATABASE_TYPES)}"
            )
        if self.type == "postgresql":
            if self.dsn is None:
                raise ValueError("dsn is required for PostgreSQL datasource")
            dsn_str = self.dsn_value
            assert dsn_str is not None
            if not dsn_str.startswith("postgresql://") and not dsn_str.startswith(
                "postgres://"
            ):
                raise ValueError("dsn must be a valid PostgreSQL connection string")
        else:
            if not self.host.strip():
                raise ValueError("host is required for MySQL/StarRocks datasource")
            if self.port < 1 or self.port > 65535:
                raise ValueError("port is invalid")
            if not self.database.strip():
                raise ValueError("database is required")
            if not self.username.strip():
                raise ValueError("username is required")
            if self.password is None:
                raise ValueError("password is required for MySQL/StarRocks datasource")
        return self


def load_database_settings(env_file: Path | None = None) -> DatabaseSettings:
    return DatabaseSettings(_env_file=_resolve_env_file(env_file))


class DatasourceAllowList(BaseSettings):
    """Per-datasource security boundary (allowed schemas + tables)."""

    model_config = SettingsConfigDict(
        env_prefix="TEXT_TO_SQL_",
        extra="ignore",
    )

    allowed_schemas: str = ""
    allowed_tables: str = ""

    def parse(self) -> tuple[tuple[str, ...], tuple[str, ...]]:
        """Parse the comma-separated environment allowlist."""
        schemas = tuple(
            schema.strip()
            for schema in self.allowed_schemas.split(",")
            if schema.strip()
        )
        tables = tuple(
            table.strip()
            for table in self.allowed_tables.split(",")
            if table.strip()
        )
        return schemas, tables


def load_datasource_allowlist(
    env_file: Path | None = None,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    return DatasourceAllowList(_env_file=_resolve_env_file(env_file)).parse()


def load_datasources_from_file(path: Path) -> dict[str, DatabaseSettings]:
    """Load extra datasource configs from a JSON file.

    Each datasource may declare ``allowed_schemas`` and ``allowed_tables``.
    Those values become explicit ``DatabaseSettings`` fields.
    """
    if not path.is_file():
        return {}

    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or "datasources" not in raw:
        raise ValueError("datasources JSON must contain a 'datasources' key")

    result: dict[str, DatabaseSettings] = {}
    for ds_id, ds_config in raw["datasources"].items():
        if not isinstance(ds_config, dict):
            raise ValueError(f"datasource '{ds_id}' config must be an object")
        ds_type = ds_config.get("type", "mysql")
        common_settings: dict[str, object] = {
            "type": ds_type,
            "datasource_id": ds_id,
            "min_pool_size": ds_config.get("min_pool_size", 1),
            "max_pool_size": ds_config.get("max_pool_size", 4),
            "pool_timeout_seconds": ds_config.get("pool_timeout_seconds", 5.0),
            "statement_timeout_seconds": ds_config.get(
                "statement_timeout_seconds", 30
            ),
            "max_result_rows": ds_config.get("max_result_rows", 1000),
            "connection_retry_count": ds_config.get("connection_retry_count", 1),
            "allowed_schemas": tuple(ds_config.get("allowed_schemas", [])),
            "allowed_tables": tuple(ds_config.get("allowed_tables", [])),
        }
        if ds_type == "postgresql":
            dsn = ds_config.get("dsn")
            if not dsn:
                raise ValueError(f"PostgreSQL datasource '{ds_id}' requires 'dsn'")
            common_settings["dsn"] = dsn
        else:
            common_settings.update(
                host=ds_config.get("host", "127.0.0.1"),
                port=ds_config.get(
                    "port", 3306 if ds_type == "mysql" else 9030
                ),
                database=ds_config.get("database", ""),
                username=ds_config.get("username", ""),
                password=ds_config.get("password", ""),
            )
        result[ds_id] = DatabaseSettings(**common_settings)
    return result
