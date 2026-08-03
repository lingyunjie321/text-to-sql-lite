"""Non-sensitive local model and datasource profile definitions."""

from __future__ import annotations

from ipaddress import ip_address
import re
from typing import Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    StrictInt,
    StrictStr,
    field_validator,
    model_validator,
)

PROFILE_ID_PATTERN = re.compile(
    r"^[a-z0-9](?:[a-z0-9_-]{0,62}[a-z0-9])?$"
)
_HOST_PATTERN = re.compile(
    r"^[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?$"
)


def _has_control_characters(value: str) -> bool:
    return any(ord(character) < 32 or ord(character) == 127 for character in value)


def validate_profile_id(value: str) -> str:
    if not PROFILE_ID_PATTERN.fullmatch(value):
        raise ValueError("profile id is invalid")
    return value


def _normalize_text(value: str, *, field_name: str, max_length: int) -> str:
    stripped = value.strip()
    if (
        not stripped
        or len(stripped) > max_length
        or _has_control_characters(stripped)
    ):
        raise ValueError(f"{field_name} is invalid")
    return stripped


def _validate_endpoint(value: HttpUrl, *, field_name: str) -> HttpUrl:
    if (
        value.username is not None
        or value.password is not None
        or value.query is not None
        or value.fragment is not None
    ):
        raise ValueError(f"{field_name} is invalid")
    if value.scheme == "http":
        host = (value.host or "").strip("[]").casefold()
        is_loopback = host == "localhost"
        if not is_loopback:
            try:
                is_loopback = ip_address(host).is_loopback
            except ValueError:
                is_loopback = False
        if not is_loopback:
            raise ValueError(f"{field_name} is invalid")
    return value


class ModelProfile(BaseModel):
    """Persisted model configuration without API credentials."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        hide_input_in_errors=True,
    )

    id: StrictStr
    name: StrictStr
    provider_type: Literal["openai_compatible"]
    base_url: HttpUrl
    model_name: StrictStr
    embedding_base_url: HttpUrl | None = None
    embedding_model: StrictStr | None = None
    embedding_dimension: StrictInt | None = Field(
        default=None,
        ge=1,
        le=1_000_000,
    )

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        return validate_profile_id(value)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        return _normalize_text(value, field_name="name", max_length=100)

    @field_validator("model_name")
    @classmethod
    def validate_model_name(cls, value: str) -> str:
        return _normalize_text(value, field_name="model_name", max_length=200)

    @field_validator("embedding_model")
    @classmethod
    def validate_embedding_model(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _normalize_text(
            value,
            field_name="embedding_model",
            max_length=200,
        )

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: HttpUrl) -> HttpUrl:
        return _validate_endpoint(value, field_name="base_url")

    @field_validator("embedding_base_url")
    @classmethod
    def validate_embedding_base_url(
        cls,
        value: HttpUrl | None,
    ) -> HttpUrl | None:
        if value is None:
            return None
        return _validate_endpoint(value, field_name="embedding_base_url")

    @model_validator(mode="after")
    def validate_embedding_pair(self) -> Self:
        configured = (
            self.embedding_base_url is not None,
            self.embedding_model is not None,
            self.embedding_dimension is not None,
        )
        if len(set(configured)) != 1:
            raise ValueError("embedding configuration is incomplete")
        return self


class DatasourceProfile(BaseModel):
    """Persisted datasource configuration without passwords or DSNs."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        hide_input_in_errors=True,
    )

    id: StrictStr
    name: StrictStr
    database_type: Literal["postgresql", "mysql"]
    host: StrictStr
    port: StrictInt = Field(ge=1, le=65535)
    database: StrictStr
    username: StrictStr
    allowed_schemas: tuple[StrictStr, ...] = Field(min_length=1)
    allowed_tables: tuple[StrictStr, ...] = Field(min_length=1)

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        return validate_profile_id(value)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        return _normalize_text(value, field_name="name", max_length=100)

    @field_validator("host")
    @classmethod
    def validate_host(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped or _has_control_characters(stripped):
            raise ValueError("host is invalid")
        try:
            ip_address(stripped.strip("[]"))
        except ValueError:
            labels = stripped.split(".")
            if (
                not _HOST_PATTERN.fullmatch(stripped)
                or ".." in stripped
                or any(
                    label.startswith("-") or label.endswith("-")
                    for label in labels
                )
            ):
                raise ValueError("host is invalid")
        return stripped

    @field_validator("database")
    @classmethod
    def validate_database(cls, value: str) -> str:
        return _normalize_text(value, field_name="database", max_length=128)

    @field_validator("username")
    @classmethod
    def validate_username(cls, value: str) -> str:
        return _normalize_text(value, field_name="username", max_length=128)

    @field_validator("allowed_schemas")
    @classmethod
    def validate_allowed_schemas(
        cls,
        value: tuple[str, ...],
    ) -> tuple[str, ...]:
        normalized = tuple(
            _normalize_text(schema, field_name="allowed_schemas", max_length=128)
            for schema in value
        )
        if len(normalized) != len(set(normalized)):
            raise ValueError("allowed_schemas contains duplicates")
        return normalized

    @field_validator("allowed_tables")
    @classmethod
    def validate_allowed_tables(
        cls,
        value: tuple[str, ...],
    ) -> tuple[str, ...]:
        normalized = tuple(
            _normalize_text(table, field_name="allowed_tables", max_length=257)
            for table in value
        )
        if len(normalized) != len(set(normalized)):
            raise ValueError("allowed_tables contains duplicates")
        return normalized

    @model_validator(mode="after")
    def validate_table_schemas(self) -> Self:
        allowed_schemas = set(self.allowed_schemas)
        for table in self.allowed_tables:
            schema, separator, table_name = table.partition(".")
            if (
                separator != "."
                or not schema
                or not table_name
                or "." in table_name
                or schema not in allowed_schemas
            ):
                raise ValueError("allowed_tables is invalid")
        return self
