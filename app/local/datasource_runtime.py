"""动态数据源连接构建、临时验证与 Workflow 运行时组装。"""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
from typing import Protocol
from urllib.parse import quote

from pydantic import SecretStr

from app.config import DatabaseSettings
from app.connectors.base import DatabaseConnector
from app.connectors.catalog import (
    DiscoveredMetadata,
    MetadataLimits,
    discover_metadata,
    validate_allowlist,
)
from app.connectors.errors import DatabaseConnectorError, ErrorType
from app.connectors.factory import ConnectorFactory
from app.connectors.scoped import ProfileScopedConnector
from app.local.profile_models import DatasourceProfile
from app.workflow import WorkflowContext

logger = logging.getLogger(__name__)


class _ContextFactory(Protocol):
    def create(self, **kwargs: object) -> WorkflowContext: ...


@dataclass(frozen=True, slots=True)
class DatasourceConnectionConfig:
    datasource_id: str
    database_type: str
    host: str
    port: int
    database: str
    username: str

    @classmethod
    def from_profile(
        cls,
        profile: DatasourceProfile,
    ) -> DatasourceConnectionConfig:
        return cls(
            datasource_id=profile.id,
            database_type=profile.database_type,
            host=profile.host,
            port=profile.port,
            database=profile.database,
            username=profile.username,
        )


class DatasourceRuntimeError(RuntimeError):
    """数据源运行时对外稳定、脱敏的错误。"""

    def __init__(
        self,
        *,
        code: str,
        public_message: str,
        status_code: int,
    ) -> None:
        super().__init__(public_message)
        self.code = code
        self.public_message = public_message
        self.status_code = status_code


@dataclass(frozen=True, slots=True)
class DatasourceRuntime:
    profile: DatasourceProfile
    connector: DatabaseConnector = field(repr=False)
    context: WorkflowContext = field(repr=False)


class DatasourceRuntimeService:
    """创建临时 Connector，并组装受 Profile 限制的长期运行时。"""

    def __init__(
        self,
        *,
        connector_factory: ConnectorFactory,
        context_factory: _ContextFactory,
        model_routing: object,
        embedding_provider: object,
        limits: MetadataLimits = MetadataLimits(),
    ) -> None:
        self._connector_factory = connector_factory
        self._context_factory = context_factory
        self._model_routing = model_routing
        self._embedding_provider = embedding_provider
        self._limits = limits

    def test_connection(
        self,
        config: DatasourceConnectionConfig,
        password: SecretStr | None,
    ) -> DiscoveredMetadata:
        connector = self._create_connector(config, password)
        try:
            self._open_connector(connector)
            try:
                return discover_metadata(
                    connector,
                    dialect=connector.dialect_name,
                    limits=self._limits,
                )
            except Exception as error:
                raise _metadata_runtime_error(error) from None
        finally:
            _close_connector(connector)

    def validate_profile(
        self,
        profile: DatasourceProfile,
        password: SecretStr | None,
    ):
        connector = self._create_connector(
            DatasourceConnectionConfig.from_profile(profile),
            password,
        )
        try:
            self._open_connector(connector)
            try:
                return validate_allowlist(
                    connector,
                    database_type=profile.database_type,
                    allowed_schemas=profile.allowed_schemas,
                    allowed_tables=profile.allowed_tables,
                    timeout_seconds=self._limits.timeout_seconds,
                )
            except Exception as error:
                raise _metadata_runtime_error(error) from None
        finally:
            _close_connector(connector)

    def build_runtime(
        self,
        profile: DatasourceProfile,
        password: SecretStr | None,
    ) -> DatasourceRuntime:
        connector = self._create_connector(
            DatasourceConnectionConfig.from_profile(profile),
            password,
        )
        try:
            self._open_connector(connector)
            try:
                validate_allowlist(
                    connector,
                    database_type=profile.database_type,
                    allowed_schemas=profile.allowed_schemas,
                    allowed_tables=profile.allowed_tables,
                    timeout_seconds=self._limits.timeout_seconds,
                )
            except Exception as error:
                raise _metadata_runtime_error(error) from None

            scoped_connector = ProfileScopedConnector(
                delegate=connector,
                allowed_schemas=profile.allowed_schemas,
                allowed_tables=profile.allowed_tables,
            )
            try:
                context = self._context_factory.create(
                    connector=scoped_connector,
                    model_routing=self._model_routing,
                    datasource_id=profile.id,
                    allowed_schemas=profile.allowed_schemas,
                    allowed_tables=profile.allowed_tables,
                    embedding_provider=self._embedding_provider,
                    semantic_version="0.0.0",
                )
            except Exception:
                raise _runtime_unavailable_error() from None
            return DatasourceRuntime(
                profile=profile,
                connector=connector,
                context=context,
            )
        except BaseException:
            _close_connector(connector)
            raise

    def _create_connector(
        self,
        config: DatasourceConnectionConfig,
        password: SecretStr | None,
    ) -> DatabaseConnector:
        if password is None:
            raise _credential_missing_error()
        try:
            settings = _build_database_settings(config, password)
            return self._connector_factory.create(settings)
        except DatasourceRuntimeError:
            raise
        except Exception:
            raise _connection_failed_error() from None

    @staticmethod
    def _open_connector(connector: DatabaseConnector) -> None:
        try:
            connector.open()
        except Exception:
            raise _connection_failed_error() from None


def _build_database_settings(
    config: DatasourceConnectionConfig,
    password: SecretStr,
) -> DatabaseSettings:
    common: dict[str, object] = {
        "type": config.database_type,
        "datasource_id": config.datasource_id,
        "host": config.host,
        "port": config.port,
        "database": config.database,
        "username": config.username,
        "min_pool_size": 1,
        "max_pool_size": 4,
        "pool_timeout_seconds": 5.0,
        "statement_timeout_seconds": 30,
        "max_result_rows": 1000,
        "connection_retry_count": 1,
    }
    if config.database_type == "postgresql":
        host = config.host.strip("[]")
        rendered_host = f"[{host}]" if ":" in host else host
        username = quote(config.username, safe="")
        secret = quote(password.get_secret_value(), safe="")
        database = quote(config.database, safe="")
        common["dsn"] = SecretStr(
            f"postgresql://{username}:{secret}@{rendered_host}:"
            f"{config.port}/{database}"
        )
    elif config.database_type == "mysql":
        common["password"] = password
    else:
        raise ValueError("database type is unsupported")
    return DatabaseSettings(**common)


def _metadata_runtime_error(error: Exception) -> DatasourceRuntimeError:
    if isinstance(error, DatasourceRuntimeError):
        return error
    if isinstance(error, DatabaseConnectorError):
        if error.details.code == "DB_ALLOWLIST_MISMATCH":
            return DatasourceRuntimeError(
                code="DATASOURCE_ALLOWLIST_INVALID",
                public_message="The datasource allowlist is invalid.",
                status_code=409,
            )
        if error.details.error_type is ErrorType.TIMEOUT:
            return DatasourceRuntimeError(
                code="DATASOURCE_METADATA_TIMEOUT",
                public_message="Datasource metadata discovery timed out.",
                status_code=504,
            )
        if error.details.error_type is ErrorType.CONNECTION_ERROR:
            return _connection_failed_error()
    return DatasourceRuntimeError(
        code="DATASOURCE_METADATA_UNAVAILABLE",
        public_message="Datasource metadata is unavailable.",
        status_code=503,
    )


def _credential_missing_error() -> DatasourceRuntimeError:
    return DatasourceRuntimeError(
        code="DATASOURCE_CREDENTIAL_MISSING",
        public_message="The datasource password is not available.",
        status_code=409,
    )


def _connection_failed_error() -> DatasourceRuntimeError:
    return DatasourceRuntimeError(
        code="DATASOURCE_CONNECTION_FAILED",
        public_message="The datasource connection failed.",
        status_code=503,
    )


def _runtime_unavailable_error() -> DatasourceRuntimeError:
    return DatasourceRuntimeError(
        code="DATASOURCE_RUNTIME_UNAVAILABLE",
        public_message="The datasource runtime is unavailable.",
        status_code=503,
    )


def _close_connector(connector: DatabaseConnector) -> None:
    try:
        connector.close()
    except Exception:
        logger.warning("datasource_connector_close_failed")
