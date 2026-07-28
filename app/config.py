from ipaddress import ip_address
from pathlib import Path
from typing import Literal, Self

from psycopg.conninfo import conninfo_to_dict
from pydantic import (
    Field,
    HttpUrl,
    SecretStr,
    field_validator,
    model_validator,
)
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


class LLMSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="LLM_",
        extra="ignore",
    )

    base_url: HttpUrl
    api_key: SecretStr
    model: str
    timeout_seconds: float = Field(default=30, ge=1, le=30)
    temperature: Literal[0] = 0

    @property
    def api_key_value(self) -> str:
        return self.api_key.get_secret_value()

    @field_validator("api_key")
    @classmethod
    def validate_api_key(cls, value: SecretStr) -> SecretStr:
        stripped = value.get_secret_value().strip()
        if not stripped or any(
            not 33 <= ord(character) <= 126
            for character in stripped
        ):
            raise ValueError("api_key is invalid")
        return SecretStr(stripped)

    @field_validator("model")
    @classmethod
    def validate_model(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("model cannot be empty")
        return stripped

    @model_validator(mode="after")
    def validate_base_url(self) -> Self:
        if (
            self.base_url.username is not None
            or self.base_url.password is not None
            or self.base_url.query is not None
            or self.base_url.fragment is not None
        ):
            raise ValueError("base_url must not contain credentials or metadata")
        if self.base_url.scheme == "http":
            host = (self.base_url.host or "").strip("[]").casefold()
            is_loopback = host == "localhost"
            if not is_loopback:
                try:
                    is_loopback = ip_address(host).is_loopback
                except ValueError:
                    is_loopback = False
            if not is_loopback:
                raise ValueError(
                    "base_url must use HTTPS outside loopback"
                )
        return self


def load_llm_settings(env_file: Path | None = None) -> LLMSettings:
    return LLMSettings(_env_file=env_file)
