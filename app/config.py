from pathlib import Path
from typing import Self

from psycopg.conninfo import conninfo_to_dict
from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class DatabaseSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="TEXT_TO_SQL_DATABASE_",
        extra="ignore",
    )

    datasource_id: str = "pagila"
    dsn: SecretStr
    min_pool_size: int = Field(default=1, ge=1)
    max_pool_size: int = Field(default=4, ge=1)
    pool_timeout_seconds: float = Field(default=5.0, gt=0)
    statement_timeout_seconds: int = Field(default=30, ge=1, le=30)
    max_result_rows: int = Field(default=1000, ge=1, le=1000)
    connection_retry_count: int = Field(default=1, ge=0, le=3)

    @property
    def dsn_value(self) -> str:
        return self.dsn.get_secret_value()

    @model_validator(mode="after")
    def validate_database(self) -> Self:
        if self.min_pool_size > self.max_pool_size:
            raise ValueError("min_pool_size cannot exceed max_pool_size")
        try:
            conninfo = conninfo_to_dict(self.dsn_value)
        except Exception as error:
            raise ValueError("dsn must be valid PostgreSQL conninfo") from error
        if conninfo.get("dbname") != "pagila":
            raise ValueError("Stage 1 datasource must use the pagila database")
        return self


def load_database_settings(
    env_file: Path | None = None,
) -> DatabaseSettings:
    return DatabaseSettings(_env_file=env_file)
