from ipaddress import ip_address
from pathlib import Path
from typing import Literal, Self

from pydantic import Field, HttpUrl, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _resolve_env_file(env_file: Path | None) -> Path:
    from app.config import _resolved_env_file

    return _resolved_env_file(env_file)


class EmbeddingSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="EMBEDDING_", extra="ignore")

    base_url: HttpUrl = Field(repr=False)
    api_key: SecretStr
    model: str = Field(repr=False)
    dimension: int = Field(ge=1)
    timeout_seconds: float = Field(default=10, gt=0, le=10)
    max_batch_documents: Literal[10] = 10
    max_response_bytes: Literal[4_194_304] = 4_194_304

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

    @field_validator("dimension", mode="before")
    @classmethod
    def validate_dimension_input(cls, value: object) -> int:
        if type(value) is int:
            return value
        if isinstance(value, str):
            stripped = value.strip()
            if stripped.isascii() and stripped.isdecimal():
                return int(stripped)
        raise ValueError("dimension must be an integer")

    @field_validator("timeout_seconds", mode="before")
    @classmethod
    def reject_boolean_timeout(cls, value: object) -> object:
        if isinstance(value, bool):
            raise ValueError("timeout_seconds must be numeric")
        return value

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
                raise ValueError("base_url must use HTTPS outside loopback")
        return self


def load_embedding_settings(env_file: Path | None = None) -> EmbeddingSettings:
    return EmbeddingSettings(_env_file=_resolve_env_file(env_file))
