from dataclasses import dataclass, field
from collections.abc import Mapping
from ipaddress import ip_address
from pathlib import Path
from typing import Literal, Self

from pydantic import (
    Field,
    HttpUrl,
    SecretStr,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict

_DEFAULT_ENV_FILE = Path(".env")
SUPPORTED_DATABASE_TYPES = frozenset({"postgresql", "mysql", "starrocks"})


def _resolved_env_file(env_file: Path | None) -> Path:
    return _DEFAULT_ENV_FILE if env_file is None else env_file


class DatabaseSettings(BaseSettings):
    """Single datasource configuration.

    Supports PostgreSQL (via DSN) and MySQL/StarRocks (via host-based params).
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
            # MySQL / StarRocks: host-based config
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


def load_database_settings(
    env_file: Path | None = None,
) -> DatabaseSettings:
    return DatabaseSettings(
        _env_file=_resolved_env_file(env_file)
    )


# ── Multi-datasource support ────────────────────────────────────


class DatasourceAllowList(BaseSettings):
    """Per-datasource security boundary (allowed schemas + tables)."""

    model_config = SettingsConfigDict(
        env_prefix="TEXT_TO_SQL_",
        extra="ignore",
    )

    allowed_schemas: str = ""
    allowed_tables: str = ""

    def parse(
        self,
    ) -> tuple[tuple[str, ...], tuple[str, ...]]:
        """Return (allowed_schemas, allowed_tables) from env vars.

        Comma-separated strings from env, e.g.:
        TEXT_TO_SQL_ALLOWED_SCHEMAS=public,analytics
        TEXT_TO_SQL_ALLOWED_TABLES=public.film,public.actor
        """
        schemas = tuple(
            s.strip() for s in self.allowed_schemas.split(",") if s.strip()
        )
        tables = tuple(
            t.strip() for t in self.allowed_tables.split(",") if t.strip()
        )
        return schemas, tables


def load_datasource_allowlist(
    env_file: Path | None = None,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    settings = DatasourceAllowList(
        _env_file=_resolved_env_file(env_file)
    )
    return settings.parse()


def load_datasources_from_file(
    path: Path,
) -> dict[str, DatabaseSettings]:
    """Load extra datasource configs from a JSON file.

    Expected format::

        {
          "datasources": {
            "mysql_prod": {
              "type": "mysql",
              "host": "127.0.0.1",
              "port": 3306,
              "database": "analytics",
              "username": "reader",
              "password": "secret",
              "allowed_schemas": ["analytics"],
              "allowed_tables": ["analytics.orders"]
            }
          }
        }
    """
    import json

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

        if ds_type == "postgresql":
            dsn = ds_config.get("dsn")
            if not dsn:
                raise ValueError(f"PostgreSQL datasource '{ds_id}' requires 'dsn'")
            settings = DatabaseSettings(
                type=ds_type,
                datasource_id=ds_id,
                dsn=dsn,
                min_pool_size=ds_config.get("min_pool_size", 1),
                max_pool_size=ds_config.get("max_pool_size", 4),
                pool_timeout_seconds=ds_config.get("pool_timeout_seconds", 5.0),
                statement_timeout_seconds=ds_config.get(
                    "statement_timeout_seconds", 30
                ),
                max_result_rows=ds_config.get("max_result_rows", 1000),
                connection_retry_count=ds_config.get("connection_retry_count", 1),
            )
        else:
            settings = DatabaseSettings(
                type=ds_type,
                datasource_id=ds_id,
                host=ds_config.get("host", "127.0.0.1"),
                port=ds_config.get("port", 3306 if ds_type == "mysql" else 9030),
                database=ds_config.get("database", ""),
                username=ds_config.get("username", ""),
                password=ds_config.get("password", ""),
                min_pool_size=ds_config.get("min_pool_size", 1),
                max_pool_size=ds_config.get("max_pool_size", 4),
                pool_timeout_seconds=ds_config.get("pool_timeout_seconds", 5.0),
                statement_timeout_seconds=ds_config.get(
                    "statement_timeout_seconds", 30
                ),
                max_result_rows=ds_config.get("max_result_rows", 1000),
                connection_retry_count=ds_config.get("connection_retry_count", 1),
            )
        result[ds_id] = settings

        # Store allowlist in an internal dict (non-Pydantic metadata)
        allowed = ds_config.get("allowed_schemas") or ds_config.get(
            "allowed_tables"
        )
        if allowed:
            if not hasattr(settings, "_extra"):
                object.__setattr__(settings, "_extra", {})
            settings._extra["allowed_schemas"] = tuple(
                ds_config.get("allowed_schemas", [])
            )
            settings._extra["allowed_tables"] = tuple(
                ds_config.get("allowed_tables", [])
            )

    return result


class AuthSettings(BaseSettings):
    """应用级安全与请求级覆写策略配置。

    ``allow_adhoc_datasources`` 控制是否允许请求体内联数据源连接信息。
    生产环境必须保持 ``false``（默认）；仅在受控调试环境显式开启。
    """

    model_config = SettingsConfigDict(
        env_prefix="TEXT_TO_SQL_",
        extra="ignore",
    )

    api_key: SecretStr | None = None
    debug_key: SecretStr | None = None
    allow_adhoc_datasources: bool = False

    @property
    def api_key_value(self) -> str | None:
        if self.api_key is None:
            return None
        return self.api_key.get_secret_value()

    @property
    def debug_key_value(self) -> str | None:
        if self.debug_key is None:
            return None
        return self.debug_key.get_secret_value()


def load_auth_settings(
    env_file: Path | None = None,
) -> AuthSettings:
    return AuthSettings(_env_file=_resolved_env_file(env_file))


def load_database_settings(
    env_file: Path | None = None,
) -> DatabaseSettings:
    return DatabaseSettings(
        _env_file=_resolved_env_file(env_file)
    )


class LLMSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="LLM_",
        extra="ignore",
    )

    base_url: HttpUrl
    api_key: SecretStr
    model: str
    timeout_seconds: float = Field(default=30, ge=1, le=120)
    temperature: Literal[0] = 0
    max_input_tokens: int = Field(
        default=32_768,
        ge=1,
        le=1_000_000,
    )
    max_output_tokens: int = Field(
        default=2_048,
        ge=1,
        le=100_000,
    )

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

    @field_validator(
        "max_input_tokens",
        "max_output_tokens",
        mode="before",
    )
    @classmethod
    def validate_token_limit_input(cls, value: object) -> object:
        if type(value) is not int:
            raise ValueError("token limit must be an integer")
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
                raise ValueError(
                    "base_url must use HTTPS outside loopback"
                )
        if self.max_output_tokens >= self.max_input_tokens:
            raise ValueError(
                "max_output_tokens must be less than max_input_tokens"
            )
        return self


def load_llm_settings(env_file: Path | None = None) -> LLMSettings:
    return LLMSettings(_env_file=_resolved_env_file(env_file))


class _LLMRouteOverrideSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    base_url: HttpUrl | None = None
    api_key: SecretStr | None = None
    model: str | None = None
    timeout_seconds: float | None = None
    temperature: Literal[0] | None = None
    max_input_tokens: int | None = None
    max_output_tokens: int | None = None

    def overlay(
        self,
        base: LLMSettings,
    ) -> tuple[LLMSettings, bool]:
        names = (
            "base_url",
            "api_key",
            "model",
            "timeout_seconds",
            "temperature",
            "max_input_tokens",
            "max_output_tokens",
        )
        overrides = {
            name: value
            for name in names
            if (value := getattr(self, name)) is not None
        }
        if not overrides:
            return base, False
        values: dict[str, object] = {
            "base_url": base.base_url,
            "api_key": base.api_key,
            "model": base.model,
            "timeout_seconds": base.timeout_seconds,
            "temperature": base.temperature,
            "max_input_tokens": base.max_input_tokens,
            "max_output_tokens": base.max_output_tokens,
        }
        values.update(overrides)
        return LLMSettings(**values), True


class _ModelRoutingPolicySettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="MODEL_ROUTING_",
        extra="ignore",
    )

    data_boundary_id: str = Field(
        default="production-primary-boundary-v1",
        repr=False,
        min_length=1,
        max_length=128,
    )
    simple_fallback_enabled: bool = False
    standard_fallback_enabled: bool = False
    complex_fallback_enabled: bool = False

    @field_validator("data_boundary_id")
    @classmethod
    def validate_data_boundary_id(cls, value: str) -> str:
        if value != value.strip() or any(
            not 33 <= ord(character) <= 126
            for character in value
        ):
            raise ValueError("data_boundary_id is invalid")
        return value


_ROUTE_IDS = (
    "simple_route",
    "standard_route",
    "complex_route",
)


def _llm_public_identity(
    settings: LLMSettings,
) -> tuple[object, ...]:
    return (
        str(settings.base_url),
        settings.model,
        settings.timeout_seconds,
        settings.temperature,
        settings.max_input_tokens,
        settings.max_output_tokens,
    )


@dataclass(frozen=True, slots=True)
class LLMRouteSettings:
    simple: LLMSettings = field(repr=False)
    standard: LLMSettings = field(repr=False)
    complex: LLMSettings = field(repr=False)
    fallback: LLMSettings | None = field(
        default=None,
        repr=False,
    )
    fallback_route_ids: tuple[
        Literal[
            "simple_route",
            "standard_route",
            "complex_route",
        ],
        ...,
    ] = ()
    data_boundary_id: str = field(
        default="production-primary-boundary-v1",
        repr=False,
    )

    def __post_init__(self) -> None:
        route_settings = {
            "simple_route": self.simple,
            "standard_route": self.standard,
            "complex_route": self.complex,
        }
        ordered_fallback_routes = tuple(
            route_id
            for route_id in _ROUTE_IDS
            if route_id in self.fallback_route_ids
        )
        if (
            any(
                not isinstance(settings, LLMSettings)
                for settings in route_settings.values()
            )
            or type(self.fallback_route_ids) is not tuple
            or self.fallback_route_ids
            != ordered_fallback_routes
            or len(self.fallback_route_ids)
            != len(set(self.fallback_route_ids))
            or (
                self.fallback is None
                and self.fallback_route_ids
            )
            or (
                self.fallback is not None
                and not self.fallback_route_ids
            )
            or not isinstance(self.data_boundary_id, str)
            or not self.data_boundary_id
            or self.data_boundary_id
            != self.data_boundary_id.strip()
        ):
            raise ValueError(
                "model routing settings are invalid"
            )
        if self.fallback is None:
            return
        if not isinstance(self.fallback, LLMSettings):
            raise ValueError(
                "model routing settings are invalid"
            )
        for route_id in self.fallback_route_ids:
            primary = route_settings[route_id]
            if (
                self.fallback.max_input_tokens
                != primary.max_input_tokens
                or self.fallback.max_output_tokens
                != primary.max_output_tokens
                or _llm_public_identity(self.fallback)
                == _llm_public_identity(primary)
            ):
                raise ValueError(
                    "model routing settings are invalid"
                )


def _load_llm_route_override(
    *,
    prefix: str,
    env_file: Path | None,
    base: LLMSettings,
) -> tuple[LLMSettings, bool]:
    override = _LLMRouteOverrideSettings(
        _env_prefix=prefix,
        _env_file=env_file,
    )
    return override.overlay(base)


def load_llm_route_settings(
    env_file: Path | None = None,
) -> LLMRouteSettings:
    resolved_env_file = _resolved_env_file(env_file)
    base = load_llm_settings(resolved_env_file)
    simple, _ = _load_llm_route_override(
        prefix="LLM_SIMPLE_",
        env_file=resolved_env_file,
        base=base,
    )
    standard, _ = _load_llm_route_override(
        prefix="LLM_STANDARD_",
        env_file=resolved_env_file,
        base=base,
    )
    complex_settings, _ = _load_llm_route_override(
        prefix="LLM_COMPLEX_",
        env_file=resolved_env_file,
        base=base,
    )
    fallback, fallback_configured = (
        _load_llm_route_override(
            prefix="LLM_FALLBACK_",
            env_file=resolved_env_file,
            base=base,
        )
    )
    policy = _ModelRoutingPolicySettings(
        _env_file=resolved_env_file
    )
    fallback_route_ids = tuple(
        route_id
        for route_id, enabled in (
            (
                "simple_route",
                policy.simple_fallback_enabled,
            ),
            (
                "standard_route",
                policy.standard_fallback_enabled,
            ),
            (
                "complex_route",
                policy.complex_fallback_enabled,
            ),
        )
        if enabled
    )
    if fallback_configured != bool(fallback_route_ids):
        raise ValueError(
            "model routing settings are invalid"
        )
    return LLMRouteSettings(
        simple=simple,
        standard=standard,
        complex=complex_settings,
        fallback=(
            fallback if fallback_configured else None
        ),
        fallback_route_ids=fallback_route_ids,  # type: ignore[arg-type]
        data_boundary_id=policy.data_boundary_id,
    )


class EmbeddingSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="EMBEDDING_",
        extra="ignore",
    )

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
                raise ValueError(
                    "base_url must use HTTPS outside loopback"
                )
        return self


def load_embedding_settings(
    env_file: Path | None = None,
) -> EmbeddingSettings:
    return EmbeddingSettings(
        _env_file=_resolved_env_file(env_file)
    )
