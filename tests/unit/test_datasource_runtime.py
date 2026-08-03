from __future__ import annotations

from contextlib import contextmanager

import pytest
from pydantic import SecretStr

from app.connectors.errors import (
    DatabaseConnectorError,
    DatabaseError,
    ErrorType,
)
from app.connectors.metadata import (
    ColumnMetadata,
    TableMetadata,
    build_schema_snapshot,
    empty_schema_snapshot,
)
from app.connectors.models import ExecutionResult
from app.local.datasource_runtime import (
    DatasourceConnectionConfig,
    DatasourceRuntimeError,
    DatasourceRuntimeService,
)
from app.local.profile_models import DatasourceProfile


def _profile(**overrides: object) -> DatasourceProfile:
    values: dict[str, object] = {
        "id": "orders",
        "name": "Orders",
        "database_type": "postgresql",
        "host": "127.0.0.1",
        "port": 5432,
        "database": "orders/db",
        "username": "reader@example.com",
        "allowed_schemas": ("public",),
        "allowed_tables": ("public.orders",),
    }
    values.update(overrides)
    return DatasourceProfile(**values)


def _database_error(
    error_type: ErrorType,
    *,
    code: str,
    message: str = "safe",
) -> DatabaseConnectorError:
    return DatabaseConnectorError(
        DatabaseError(
            sqlstate=None,
            error_type=error_type,
            code=code,
            retryable=False,
            public_message=message,
        )
    )


class ConnectorFake:
    dialect_name = "postgres"

    def __init__(
        self,
        *,
        open_error: Exception | None = None,
        execute_error: Exception | None = None,
        metadata_snapshot=None,
        metadata_error: Exception | None = None,
        close_error: Exception | None = None,
    ) -> None:
        self.open_error = open_error
        self.execute_error = execute_error
        self.metadata_snapshot = metadata_snapshot or empty_schema_snapshot()
        self.metadata_error = metadata_error
        self.close_error = close_error
        self.events: list[str] = []

    def open(self) -> None:
        self.events.append("open")
        if self.open_error is not None:
            raise self.open_error

    def close(self) -> None:
        self.events.append("close")
        if self.close_error is not None:
            raise self.close_error

    def check_connection(self) -> None:
        self.events.append("check")

    def execute(self, sql: str, *, timeout_seconds=None):
        del sql, timeout_seconds
        self.events.append("execute")
        if self.execute_error is not None:
            raise self.execute_error
        return ExecutionResult(
            columns=(),
            rows=[],
            returned_row_count=0,
            truncated=False,
            execution_time_ms=0.0,
        )

    def read_metadata(
        self,
        allowed_schemas,
        allowed_tables,
        *,
        timeout_seconds=None,
    ):
        del allowed_schemas, allowed_tables, timeout_seconds
        self.events.append("metadata")
        if self.metadata_error is not None:
            raise self.metadata_error
        return self.metadata_snapshot

    @contextmanager
    def read_only_snapshot(self):
        yield self


class ConnectorFactoryFake:
    def __init__(self, connectors: list[ConnectorFake]) -> None:
        self.connectors = connectors
        self.settings = []

    def create(self, settings):
        self.settings.append(settings)
        return self.connectors.pop(0)


class ContextFactoryFake:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[dict[str, object]] = []
        self.context = object()

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.context


def _service(
    connector: ConnectorFake,
    *,
    context_factory: ContextFactoryFake | None = None,
    model_routing: object | None = object(),
) -> tuple[DatasourceRuntimeService, ConnectorFactoryFake, ContextFactoryFake]:
    factory = ConnectorFactoryFake([connector])
    contexts = context_factory or ContextFactoryFake()
    service = DatasourceRuntimeService(
        connector_factory=factory,
        context_factory=contexts,
        model_routing=model_routing,
        embedding_provider=object(),
    )
    return service, factory, contexts


def test_temporary_connector_is_closed_when_open_fails():
    connector = ConnectorFake(
        open_error=RuntimeError("password=private-secret")
    )
    service, _, _ = _service(connector)

    with pytest.raises(DatasourceRuntimeError) as captured:
        service.test_connection(
            DatasourceConnectionConfig.from_profile(_profile()),
            SecretStr("private-secret"),
        )

    assert captured.value.code == "DATASOURCE_CONNECTION_FAILED"
    assert captured.value.status_code == 503
    assert "private-secret" not in str(captured.value)
    assert connector.events == ["open", "close"]


def test_postgresql_settings_encode_credentials_database_and_ipv6():
    connector = ConnectorFake()
    service, factory, _ = _service(connector)
    profile = _profile(host="2001:db8::1")

    service.test_connection(
        DatasourceConnectionConfig.from_profile(profile),
        SecretStr("p@ss/word"),
    )

    settings = factory.settings[0]
    assert settings.type == "postgresql"
    assert settings.datasource_id == "orders"
    assert settings.dsn_value == (
        "postgresql://reader%40example.com:p%40ss%2Fword@"
        "[2001:db8::1]:5432/orders%2Fdb"
    )
    assert "p@ss/word" not in repr(settings)


def test_mysql_settings_use_profile_identity_and_default_limits():
    connector = ConnectorFake()
    connector.dialect_name = "mysql"
    service, factory, _ = _service(connector)
    profile = _profile(
        database_type="mysql",
        port=3306,
        database="sakila",
        username="reader",
    )

    service.test_connection(
        DatasourceConnectionConfig.from_profile(profile),
        SecretStr("private-secret"),
    )

    settings = factory.settings[0]
    assert settings.type == "mysql"
    assert settings.host == "127.0.0.1"
    assert settings.port == 3306
    assert settings.database == "sakila"
    assert settings.username == "reader"
    assert settings.password_value == "private-secret"
    assert settings.statement_timeout_seconds == 30
    assert settings.max_result_rows == 1000


def test_dynamic_pool_limits_do_not_inherit_static_environment(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("TEXT_TO_SQL_DATABASE_MIN_POOL_SIZE", "2")
    monkeypatch.setenv("TEXT_TO_SQL_DATABASE_MAX_POOL_SIZE", "3")
    monkeypatch.setenv("TEXT_TO_SQL_DATABASE_POOL_TIMEOUT_SECONDS", "9")
    monkeypatch.setenv("TEXT_TO_SQL_DATABASE_CONNECTION_RETRY_COUNT", "3")
    connector = ConnectorFake()
    service, factory, _ = _service(connector)

    service.test_connection(
        DatasourceConnectionConfig.from_profile(_profile()),
        SecretStr("private-secret"),
    )

    settings = factory.settings[0]
    assert settings.min_pool_size == 1
    assert settings.max_pool_size == 4
    assert settings.pool_timeout_seconds == 5.0
    assert settings.connection_retry_count == 1


def test_metadata_timeout_has_distinct_public_error_and_closes_connector():
    connector = ConnectorFake(
        execute_error=_database_error(
            ErrorType.TIMEOUT,
            code="DB_TIMEOUT",
            message="driver timeout password=private-secret",
        )
    )
    service, _, _ = _service(connector)

    with pytest.raises(DatasourceRuntimeError) as captured:
        service.test_connection(
            DatasourceConnectionConfig.from_profile(_profile()),
            SecretStr("private-secret"),
        )

    assert captured.value.code == "DATASOURCE_METADATA_TIMEOUT"
    assert captured.value.status_code == 504
    assert "private-secret" not in str(captured.value)
    assert connector.events == ["open", "execute", "close"]


def test_allowlist_mismatch_maps_to_stable_profile_error():
    connector = ConnectorFake(metadata_snapshot=empty_schema_snapshot())
    service, _, _ = _service(connector)

    with pytest.raises(DatasourceRuntimeError) as captured:
        service.validate_profile(_profile(), SecretStr("private-secret"))

    assert captured.value.code == "DATASOURCE_ALLOWLIST_INVALID"
    assert captured.value.status_code == 409
    assert connector.events == ["open", "metadata", "close"]


def test_runtime_build_owns_connector_before_open_and_closes_on_context_error():
    table = TableMetadata(
        schema_name="public",
        table_name="orders",
        relation_kind="table",
        comment=None,
        columns=(
            ColumnMetadata(
                schema_name="public",
                table_name="orders",
                column_name="id",
                ordinal_position=1,
                data_type="integer",
                formatted_type="integer",
                nullable=False,
                comment=None,
            ),
        ),
    )
    connector = ConnectorFake(
        metadata_snapshot=build_schema_snapshot(
            tables=(table,),
            primary_keys=(),
            foreign_keys=(),
            unique_constraints=(),
            unique_indexes=(),
        )
    )
    contexts = ContextFactoryFake(
        error=RuntimeError("dsn=private-secret")
    )
    service, _, _ = _service(connector, context_factory=contexts)

    with pytest.raises(DatasourceRuntimeError) as captured:
        service.build_runtime(_profile(), SecretStr("private-secret"))

    assert captured.value.code == "DATASOURCE_RUNTIME_UNAVAILABLE"
    assert "private-secret" not in str(captured.value)
    assert connector.events == ["open", "metadata", "close"]


def test_runtime_build_returns_raw_connector_and_scoped_context():
    from app.connectors.scoped import ProfileScopedConnector

    table = TableMetadata(
        schema_name="public",
        table_name="orders",
        relation_kind="table",
        comment=None,
        columns=(
            ColumnMetadata(
                schema_name="public",
                table_name="orders",
                column_name="id",
                ordinal_position=1,
                data_type="integer",
                formatted_type="integer",
                nullable=False,
                comment=None,
            ),
        ),
    )
    connector = ConnectorFake(
        metadata_snapshot=build_schema_snapshot(
            tables=(table,),
            primary_keys=(),
            foreign_keys=(),
            unique_constraints=(),
            unique_indexes=(),
        )
    )
    service, _, contexts = _service(connector)

    runtime = service.build_runtime(
        _profile(),
        SecretStr("private-secret"),
    )

    assert runtime.profile == _profile()
    assert runtime.connector is connector
    assert runtime.context is contexts.context
    assert runtime.semantic_version == "0.0.0"
    assert isinstance(contexts.calls[0]["connector"], ProfileScopedConnector)
    assert contexts.calls[0]["datasource_id"] == "orders"
    assert contexts.calls[0]["semantic_version"] == "0.0.0"
    assert connector.events == ["open", "metadata"]


def test_runtime_builds_scoped_connector_without_static_model() -> None:
    from app.connectors.scoped import ProfileScopedConnector

    table = TableMetadata(
        schema_name="public",
        table_name="orders",
        relation_kind="table",
        comment=None,
        columns=(
            ColumnMetadata(
                schema_name="public",
                table_name="orders",
                column_name="id",
                ordinal_position=1,
                data_type="integer",
                formatted_type="integer",
                nullable=False,
                comment=None,
            ),
        ),
    )
    connector = ConnectorFake(
        metadata_snapshot=build_schema_snapshot(
            tables=(table,),
            primary_keys=(),
            foreign_keys=(),
            unique_constraints=(),
            unique_indexes=(),
        )
    )
    service, _, contexts = _service(
        connector,
        model_routing=None,
    )

    runtime = service.build_runtime(
        _profile(),
        SecretStr("private-secret"),
    )

    assert runtime.context is None
    assert isinstance(runtime.workflow_connector, ProfileScopedConnector)
    assert contexts.calls == []
