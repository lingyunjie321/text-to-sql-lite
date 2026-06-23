from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import SecretStr
from sqlalchemy.engine import URL

from text_to_sql_demo.api.models import ExecuteSQLRequest, QueryRequest
from text_to_sql_demo.config.env import load_env_files
from text_to_sql_demo.config.loader import load_workflow_config
from text_to_sql_demo.config.models import (
    DatabaseConnectionConfig,
    ModelAliasConfig,
    NodeConfig,
    WorkflowConfig,
)
from text_to_sql_demo.db.init_db import initialize_database
from text_to_sql_demo.exceptions import DatabaseConfigurationError
from text_to_sql_demo.execution.sql_executor import SQLExecutor
from text_to_sql_demo.llm.client import LLMClient, MockLLMClient
from text_to_sql_demo.llm.factory import build_llm_client
from text_to_sql_demo.llm.models import ModelProfile
from text_to_sql_demo.llm.providers import OpenAICompatibleLLMClient
from text_to_sql_demo.observability.context import get_log_context
from text_to_sql_demo.observability.events import (
    log_database_url_resolve_failed,
    log_database_url_resolved,
)
from text_to_sql_demo.runtime.exceptions import (
    RuntimeConfigExpiredError,
    RuntimeConfigNotFoundError,
    RuntimeProviderUnsupportedError,
    RuntimeSecretMissingError,
)
from text_to_sql_demo.runtime.models import (
    RuntimeConfig,
    RuntimeConfigCreateRequest,
    RuntimeConfigDisplay,
    RuntimeCustomDatabaseInput,
    RuntimeDatabaseConfig,
    RuntimeDatabaseSelection,
    RuntimeModelConfig,
    RuntimeModelRoutingConfig,
    RuntimeModelSelection,
)
from text_to_sql_demo.runtime.resolver import (
    DEFAULT_OPENAI_COMPATIBLE_BASE_URL,
    MOCK_PROVIDER,
    OPENAI_COMPATIBLE_PROVIDER,
    RUNTIME_MODEL_ALIASES,
    ResolvedRuntimeConfig,
    RuntimeConfigResolver,
    driver_to_dialect,
)
from text_to_sql_demo.runtime.store import RuntimeConfigStore
from text_to_sql_demo.runtime.tester import RuntimeConfigTester
from text_to_sql_demo.schema.catalog import DatabaseSchemaMetadata, read_schema_metadata
from text_to_sql_demo.sql.models import SQLError
from text_to_sql_demo.sql.validator import SQLValidator
from text_to_sql_demo.workflow.dependencies import NodeDependencies
from text_to_sql_demo.workflow.engine import WorkflowEngine
from text_to_sql_demo.workflow.factory import NodeFactory
from text_to_sql_demo.workflow.state import TraceEvent, WorkflowError, WorkflowState


class ApiError(Exception):
    """API 层统一异常。"""

    def __init__(
        self,
        *,
        status_code: int,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details


class InMemoryRunStore:
    """演示用内存运行记录存储。"""

    def __init__(self) -> None:
        self._runs: dict[str, WorkflowState] = {}

    def save(self, state: WorkflowState) -> None:
        """保存一次工作流运行结果。"""
        self._runs[state.request_id] = state

    def get(self, request_id: str) -> WorkflowState | None:
        """按 request_id 读取运行结果。"""
        return self._runs.get(request_id)


class TextToSQLApiService:
    """API 调用 WorkflowEngine 的薄应用服务。"""

    def __init__(
        self,
        *,
        config_path: str | Path = "workflow.yaml",
        database_url: str | None = None,
        llm_client: LLMClient | None = None,
        run_store: InMemoryRunStore | None = None,
        runtime_store: RuntimeConfigStore | None = None,
    ) -> None:
        load_env_files()
        self.config = load_workflow_config(config_path)
        self.database_url = database_url or _resolve_database_url(self.config)
        self.llm_client = llm_client or build_llm_client(self.config)
        self.run_store = run_store or InMemoryRunStore()
        self.runtime_store = runtime_store or RuntimeConfigStore()
        self.runtime_resolver = RuntimeConfigResolver(
            workflow_config=self.config,
            store=self.runtime_store,
            default_database_url=self.database_url,
            default_llm_client=self.llm_client,
        )
        self.runtime_tester = RuntimeConfigTester()

        # 导入节点包触发 register_node 装饰器，避免默认注册表为空。
        import text_to_sql_demo.nodes  # noqa: F401

    def get_runtime_options(self) -> dict[str, Any]:
        """返回前端可选择的运行时预设，所有字段均不包含真实密钥。"""
        return {
            "database_presets": [
                {
                    "id": preset_id,
                    "driver": connection.driver,
                    "display_name": preset_id,
                    "target_dialect": driver_to_dialect(connection.driver),
                    "read_only": connection.read_only,
                }
                for preset_id, connection in self.config.database.connections.items()
            ],
            "model_presets": self._model_preset_options(),
        }

    def _model_preset_options(self) -> dict[str, list[dict[str, Any]]]:
        """按轻量/强力槽位返回模型预设数组，保持前端响应结构稳定。"""
        return {
            alias: [
                {
                    "id": alias,
                    "provider": model_config.provider,
                    "model": model_config.model,
                    "display_name": f"{model_config.provider}/{model_config.model}",
                    "requires_secret": bool(model_config.api_key_env),
                }
            ]
            if (model_config := self.config.models.aliases.get(alias)) is not None
            else []
            for alias in RUNTIME_MODEL_ALIASES
        }

    def create_runtime_config(self, request: RuntimeConfigCreateRequest) -> dict[str, Any]:
        """创建短生命周期运行时配置，并先执行数据库和模型连通性测试。"""
        database = self._runtime_database_config(request.database)
        models = RuntimeModelRoutingConfig(
            light=self._runtime_model_config(request.models.light),
            strong=self._runtime_model_config(request.models.strong),
        )

        database_summary = self.runtime_tester.test_database(
            database.database_url.get_secret_value()
        )
        model_summaries = {
            "light": self.runtime_tester.test_model(
                client=self._runtime_model_client(models.light),
                model_alias="light",
                model_name=models.light.model,
            ),
            "strong": self.runtime_tester.test_model(
                client=self._runtime_model_client(models.strong),
                model_alias="strong",
                model_name=models.strong.model,
            ),
        }
        expires_at = datetime.now(UTC) + timedelta(seconds=request.ttl_seconds)
        runtime_config = RuntimeConfig(
            id=f"rt_{uuid4().hex}",
            expires_at=expires_at,
            database=database,
            models=models,
            display=RuntimeConfigDisplay(
                database=database.display_name,
                models={
                    "light": f"{models.light.provider}/{models.light.model}",
                    "strong": f"{models.strong.provider}/{models.strong.model}",
                },
            ),
        )
        self.runtime_store.save(runtime_config)

        return {
            "runtime_config_id": runtime_config.id,
            "expires_at": runtime_config.expires_at.isoformat(),
            "database": {
                "display_name": database.display_name,
                "driver": database.driver,
                "target_dialect": database.target_dialect,
                "table_count": database_summary["table_count"],
                "column_count": database_summary["column_count"],
                "tables": database_summary["tables"],
            },
            "models": {
                alias: {
                    "provider": summary["provider"],
                    "model": summary["model"],
                }
                for alias, summary in model_summaries.items()
            },
        }

    def run_query(self, request: QueryRequest) -> dict[str, Any]:
        """执行 Text-to-SQL 工作流并返回演示响应。"""
        resolved = self._resolve_runtime_config(request.runtime_config_id)
        self.ensure_database(database_url=resolved.database_url)
        schema = self.read_schema(database_url=resolved.database_url)
        request_id = get_log_context().get("request_id") or str(uuid4())
        state = WorkflowState(
            request_id=str(request_id),
            user_question=request.question,
            data={
                "schema": schema.model_dump(mode="python"),
                "target_dialect": resolved.target_dialect,
                "runtime_config_id": resolved.runtime_config_id,
                "max_repair_attempts": request.max_attempts,
                "debug": request.debug,
            },
        )
        engine = WorkflowEngine(
            config=self._config_for_request(
                max_attempts=request.max_attempts,
                target_dialect=resolved.target_dialect,
            ),
            node_factory=NodeFactory(dependencies=self._node_dependencies(resolved=resolved)),
        )
        final_state = engine.run(state)
        self.run_store.save(final_state)
        return serialize_run(final_state)

    def get_run(self, request_id: str) -> dict[str, Any]:
        """读取历史运行响应。"""
        state = self.run_store.get(request_id)
        if state is None:
            raise ApiError(
                status_code=404,
                code="not_found",
                message="未找到工作流运行记录",
                details={"request_id": request_id},
            )
        return serialize_run(state)

    def execute_sql(self, request: ExecuteSQLRequest) -> dict[str, Any]:
        """校验并执行用户编辑后的只读 SQL，不进入 Agent 工作流。"""
        resolved = self._resolve_runtime_config(request.runtime_config_id)
        self.ensure_database(database_url=resolved.database_url)
        schema = self.read_schema(database_url=resolved.database_url)
        validation = SQLValidator().validate(
            sql=request.sql,
            schema=schema,
            dialect=resolved.target_dialect,
        )
        if not validation.success:
            return _serialize_direct_sql(
                status="failed",
                sql=request.sql,
                result=None,
                error=validation.error,
            )

        executable_sql = validation.rendered_sql or validation.normalized_sql or request.sql
        result = SQLExecutor().execute(
            sql=executable_sql,
            database_url=resolved.database_url,
            max_rows=request.max_rows,
        )
        return _serialize_direct_sql(
            status="success" if result.success else "failed",
            sql=executable_sql,
            result=result.model_dump(mode="python"),
            error=result.error,
        )

    def get_schema(self, *, runtime_config_id: str | None = None) -> DatabaseSchemaMetadata:
        """按可选 runtime_config_id 返回对应数据库 Schema。"""
        resolved = self._resolve_runtime_config(runtime_config_id)
        self.ensure_database(database_url=resolved.database_url)
        return self.read_schema(database_url=resolved.database_url)

    def read_schema(self, *, database_url: str | None = None) -> DatabaseSchemaMetadata:
        """读取当前 demo 数据库 Schema。"""
        return read_schema_metadata(database_url or self.database_url)

    def ensure_database(self, *, database_url: str | None = None) -> None:
        """初始化缺失的 SQLite demo 数据库。"""
        db_path = _sqlite_path_from_url(database_url or self.database_url)
        if db_path is not None and not db_path.exists():
            initialize_database(db_path)

    def _node_dependencies(self, *, resolved: ResolvedRuntimeConfig) -> NodeDependencies:
        return NodeDependencies(
            values={
                "database_url": resolved.database_url,
                "llm_client": resolved.llm_client,
                "model_profiles": resolved.model_profiles,
            }
        )

    def _config_for_request(
        self,
        *,
        max_attempts: int,
        target_dialect: str,
    ) -> WorkflowConfig:
        config = self.config.model_copy(deep=True)
        config.dialect.name = target_dialect
        config.dialect.target_dialect = target_dialect
        config.workflow.max_repair_attempts = max_attempts
        for node_name, node_config in list(config.nodes.items()):
            raw_config = node_config.model_dump(mode="python")
            original_config = dict(raw_config)
            if node_config.type in {"sql_generation", "sql_validation"}:
                raw_config["target_dialect"] = target_dialect
            if node_config.type == "sql_validation":
                raw_config["render_dialect"] = target_dialect
            if node_config.type == "sql_execution":
                raw_config["execution_dialect"] = target_dialect
            if node_config.type in {"error_reflection", "error_classification"}:
                raw_config["max_repair_attempts"] = max_attempts
            if raw_config != original_config:
                config.nodes[node_name] = NodeConfig.model_validate(raw_config)
        return config

    def _resolve_runtime_config(
        self,
        runtime_config_id: str | None,
    ) -> ResolvedRuntimeConfig:
        """解析 runtime config，并在 API service 边界转换为统一错误。"""
        try:
            return self.runtime_resolver.resolve(runtime_config_id)
        except RuntimeConfigNotFoundError as exc:
            raise ApiError(
                status_code=404,
                code="runtime_config_not_found",
                message="运行时配置不存在",
                details={"runtime_config_id": runtime_config_id},
            ) from exc
        except RuntimeConfigExpiredError as exc:
            raise ApiError(
                status_code=410,
                code="runtime_config_expired",
                message="运行时配置已过期",
                details={"runtime_config_id": runtime_config_id},
            ) from exc
        except RuntimeSecretMissingError as exc:
            raise ApiError(
                status_code=400,
                code="runtime_secret_missing",
                message="运行时模型密钥未配置",
                details={"runtime_config_id": runtime_config_id},
            ) from exc
        except RuntimeProviderUnsupportedError as exc:
            raise ApiError(
                status_code=400,
                code="runtime_provider_unsupported",
                message="不支持的运行时模型 provider",
                details={"runtime_config_id": runtime_config_id},
            ) from exc

    def _runtime_database_config(
        self,
        selection: RuntimeDatabaseSelection,
    ) -> RuntimeDatabaseConfig:
        if selection.mode == "preset":
            return self._preset_database_config(_require_text(selection.preset_id, "preset_id"))

        if selection.config is None:
            raise ApiError(
                status_code=400,
                code="runtime_config_invalid",
                message="数据库 custom 模式必须提供 config",
            )
        return self._custom_database_config(selection.config)

    def _preset_database_config(self, preset_id: str) -> RuntimeDatabaseConfig:
        if preset_id not in self.config.database.connections:
            raise ApiError(
                status_code=404,
                code="runtime_preset_not_found",
                message="数据库预设不存在",
                details={"preset_id": preset_id},
            )
        connection = self.config.database.connections[preset_id]
        return RuntimeDatabaseConfig(
            driver=connection.driver,
            database_url=SecretStr(_resolve_database_url(self.config, connection_name=preset_id)),
            target_dialect=driver_to_dialect(connection.driver),
            display_name=preset_id,
        )

    def _custom_database_config(
        self,
        config: RuntimeCustomDatabaseInput,
    ) -> RuntimeDatabaseConfig:
        target_dialect = config.target_dialect or driver_to_dialect(config.driver)
        if config.driver == "sqlite":
            sqlite_path = _require_text(config.sqlite_path, "sqlite_path")
            return RuntimeDatabaseConfig(
                driver="sqlite",
                database_url=SecretStr(_sqlite_url_from_path(sqlite_path)),
                target_dialect=target_dialect,
                display_name=config.display_name or Path(sqlite_path).name,
            )

        host = _require_text(config.host, "host")
        port = _require_int(config.port, "port")
        database_name = _require_text(config.database_name, "database_name")
        username = _require_text(config.username, "username")
        password = _require_secret(config.password, "password")
        return RuntimeDatabaseConfig(
            driver=config.driver,
            database_url=SecretStr(
                URL.create(
                    drivername=SERVER_DRIVER_NAMES[config.driver],
                    username=username,
                    password=password.get_secret_value(),
                    host=host,
                    port=port,
                    database=database_name,
                ).render_as_string(hide_password=False)
            ),
            target_dialect=target_dialect,
            display_name=config.display_name or database_name,
        )

    def _runtime_model_config(
        self,
        selection: RuntimeModelSelection,
    ) -> RuntimeModelConfig:
        if selection.mode == "preset":
            return self._preset_model_config(_require_text(selection.preset_id, "preset_id"))

        provider = _require_text(selection.provider, "provider")
        model = _require_text(selection.model, "model")
        return RuntimeModelConfig(
            provider=provider,
            model=model,
            base_url=selection.base_url,
            api_key=selection.api_key,
            api_key_env=selection.api_key_env,
            temperature=selection.temperature,
            max_tokens=selection.max_tokens,
        )

    def _preset_model_config(self, preset_id: str) -> RuntimeModelConfig:
        model_config = self.config.models.aliases.get(preset_id)
        if model_config is None:
            raise ApiError(
                status_code=404,
                code="runtime_preset_not_found",
                message="模型预设不存在",
                details={"preset_id": preset_id},
            )
        return RuntimeModelConfig(
            provider=model_config.provider,
            model=model_config.model,
            base_url=_runtime_model_base_url(model_config),
            api_key_env=model_config.api_key_env,
            temperature=model_config.temperature,
            max_tokens=model_config.max_tokens,
        )

    def _runtime_model_client(self, model_config: RuntimeModelConfig) -> LLMClient:
        if model_config.provider == MOCK_PROVIDER:
            return MockLLMClient()
        if model_config.provider == OPENAI_COMPATIBLE_PROVIDER:
            api_key = _runtime_api_key(model_config)
            return OpenAICompatibleLLMClient(
                api_key=api_key,
                base_url=model_config.base_url or DEFAULT_OPENAI_COMPATIBLE_BASE_URL,
            )
        raise ApiError(
            status_code=400,
            code="runtime_provider_unsupported",
            message="不支持的运行时模型 provider",
            details={"provider": model_config.provider},
        )


def serialize_run(state: WorkflowState) -> dict[str, Any]:
    """把 WorkflowState 转换为演示 API 响应。"""
    final_status = str(state.data.get("final_status") or ("failed" if state.errors else "unknown"))
    return {
        "request_id": state.request_id,
        "status": final_status,
        "final_sql": state.data.get("final_sql") or state.data.get("current_sql"),
        "result": state.data.get("final_result") or state.data.get("execution_result"),
        "attempts": int(state.data.get("attempt_count", 0)),
        "selected_model": state.data.get("selected_model"),
        "routing_reason": state.data.get("routing_reason"),
        "linked_schema": state.data.get("schema_linking") or state.data.get("linked_schema") or {},
        "retrieved_examples": _summarize_examples(state.data.get("retrieved_examples") or []),
        "repair_history": state.data.get("repair_history", []),
        "errors": _serialize_errors(state),
        "trace": [_serialize_trace_event(event) for event in state.trace],
    }


def _serialize_direct_sql(
    *,
    status: str,
    sql: str,
    result: dict[str, Any] | None,
    error: SQLError | None,
) -> dict[str, Any]:
    """把用户编辑 SQL 的执行结果转换为前端可复用响应。"""
    errors = []
    if error is not None:
        errors.append(
            {
                "node_name": "sql_editor",
                "error_type": error.category,
                "message": error.message,
                "error": error.model_dump(mode="python"),
            }
        )
    return {
        "request_id": str(uuid4()),
        "status": status,
        "final_sql": sql,
        "result": result if status == "success" else None,
        "attempts": 0,
        "selected_model": None,
        "routing_reason": None,
        "linked_schema": {"tables": []},
        "retrieved_examples": [],
        "repair_history": [],
        "errors": errors,
        "trace": [],
    }


def _serialize_trace_event(event: TraceEvent) -> dict[str, Any]:
    return {
        "node_name": event.node_name,
        "node_type": event.node_type,
        "start_time": event.started_at.isoformat(),
        "end_time": event.ended_at.isoformat(),
        "duration_ms": event.duration_ms,
        "status": event.status,
        "outcome": event.outcome,
        "input_summary": event.input_summary,
        "output_summary": event.output_summary,
        "error": event.error,
    }


def _summarize_examples(examples: list[dict[str, Any]]) -> list[dict[str, Any]]:
    summarized = []
    for item in examples:
        example = item.get("example", item)
        summarized.append(
            {
                "natural_language": example.get("natural_language"),
                "sql": example.get("sql"),
                "dialect": example.get("dialect"),
                "involved_tables": example.get("involved_tables", []),
                "score": item.get("score"),
                "reasons": item.get("reasons", []),
            }
        )
    return summarized


def _serialize_errors(state: WorkflowState) -> list[dict[str, Any]]:
    errors = [_workflow_error_to_dict(error) for error in state.errors]
    final_error = state.data.get("final_error") or state.data.get("last_error")
    if final_error and state.data.get("final_status") != "success":
        errors.append({"node_name": state.current_node, "error": final_error})
    return errors


def _workflow_error_to_dict(error: WorkflowError) -> dict[str, Any]:
    return {
        "node_name": error.node_name,
        "error_type": error.error_type,
        "message": error.message,
    }


def _model_profiles(config: WorkflowConfig) -> dict[str, ModelProfile]:
    return {
        alias: ModelProfile(
            alias=alias,
            provider=model_config.provider,
            model_name=model_config.model,
            temperature=model_config.temperature,
            max_tokens=model_config.max_tokens,
        )
        for alias, model_config in config.models.aliases.items()
    }


SERVER_DRIVER_NAMES = {
    "postgresql": "postgresql+psycopg",
    "mysql": "mysql+pymysql",
}


def _resolve_database_url(
    config: WorkflowConfig,
    *,
    connection_name: str | None = None,
) -> str:
    connection_name = connection_name or config.database.default
    connection = config.database.connections[connection_name]
    try:
        if connection.url_env:
            env_value = os.getenv(connection.url_env)
            if env_value:
                log_database_url_resolved(
                    connection_name=connection_name,
                    database_driver=connection.driver,
                )
                return env_value

        structured_url = _build_structured_database_url(connection)
        if structured_url is not None:
            log_database_url_resolved(
                connection_name=connection_name,
                database_driver=connection.driver,
            )
            return structured_url

        if connection.fallback_url:
            log_database_url_resolved(
                connection_name=connection_name,
                database_driver=connection.driver,
            )
            return connection.fallback_url

        raise DatabaseConfigurationError(f"数据库连接 {connection_name} 缺少可用的连接配置")
    except DatabaseConfigurationError as exc:
        log_database_url_resolve_failed(
            connection_name=connection_name,
            database_driver=connection.driver,
            error=exc,
        )
        raise


def _build_structured_database_url(connection: DatabaseConnectionConfig) -> str | None:
    """根据 host/port/username/password_env 生成 SQLAlchemy 数据库 URL。"""
    driver_name = SERVER_DRIVER_NAMES.get(connection.driver)
    if driver_name is None:
        return None

    has_structured_fields = any(
        value is not None
        for value in (
            connection.host,
            connection.port,
            connection.database_name,
            connection.username,
            connection.username_env,
            connection.password_env,
        )
    )
    if not has_structured_fields:
        return None

    host = _required_config_value(connection.host, "host")
    port = connection.port
    if port is None:
        raise DatabaseConfigurationError("服务型数据库连接缺少 port")

    database_name = _required_config_value(connection.database_name, "database_name")
    username = _resolve_value_or_env(
        value=connection.username,
        env_name=connection.username_env,
        label="username",
    )
    password = _resolve_required_env(connection.password_env, "password_env")
    url = URL.create(
        drivername=driver_name,
        username=username,
        password=password,
        host=host,
        port=port,
        database=database_name,
        query=connection.query,
    )
    return url.render_as_string(hide_password=False)


def _required_config_value(value: str | None, field_name: str) -> str:
    if value:
        return value
    raise DatabaseConfigurationError(f"服务型数据库连接缺少 {field_name}")


def _resolve_value_or_env(
    *,
    value: str | None,
    env_name: str | None,
    label: str,
) -> str:
    if env_name:
        env_value = os.getenv(env_name)
        if env_value:
            return env_value
        raise DatabaseConfigurationError(f"数据库连接 {label} 环境变量未设置: {env_name}")

    if value:
        return value

    raise DatabaseConfigurationError(f"服务型数据库连接缺少 {label}")


def _resolve_required_env(env_name: str | None, label: str) -> str:
    if not env_name:
        raise DatabaseConfigurationError(
            f"服务型数据库连接必须配置 {label}，避免在配置文件中明文写入密码"
        )

    env_value = os.getenv(env_name)
    if env_value:
        return env_value

    raise DatabaseConfigurationError(f"数据库连接 {label} 环境变量未设置: {env_name}")


def _sqlite_path_from_url(database_url: str) -> Path | None:
    prefix = "sqlite:///"
    if not database_url.startswith(prefix) or database_url == "sqlite:///:memory:":
        return None
    raw_path = database_url.removeprefix(prefix)
    path = Path(raw_path)
    if not path.is_absolute():
        path = Path.cwd() / path
    return path


def _sqlite_url_from_path(sqlite_path: str) -> str:
    """把用户提交的 sqlite 路径转换为 SQLAlchemy URL。"""
    if sqlite_path == ":memory:":
        return "sqlite:///:memory:"
    path = Path(sqlite_path)
    if path.is_absolute():
        return f"sqlite:///{path}"
    return f"sqlite:///{sqlite_path}"


def _runtime_api_key(model_config: RuntimeModelConfig) -> str:
    """解析运行时模型密钥，避免把明文写入日志或响应。"""
    if model_config.api_key is not None:
        api_key = model_config.api_key.get_secret_value().strip()
        if api_key:
            return api_key
    if model_config.api_key_env:
        api_key = os.getenv(model_config.api_key_env, "").strip()
        if api_key:
            return api_key
    raise ApiError(
        status_code=400,
        code="runtime_secret_missing",
        message="运行时模型密钥未配置",
    )


def _runtime_model_base_url(model_config: ModelAliasConfig) -> str | None:
    """按 workflow 显式值、环境变量顺序解析运行时模型 base_url。"""
    if model_config.base_url:
        return model_config.base_url
    if model_config.base_url_env:
        return os.getenv(model_config.base_url_env)
    return None


def _require_text(value: str | None, field_name: str) -> str:
    """把 Pydantic 已校验字段转成非空文本，避免依赖 assert。"""
    if value is not None and value.strip():
        return value
    raise ApiError(
        status_code=400,
        code="runtime_config_invalid",
        message="运行时配置字段缺失",
        details={"field": field_name},
    )


def _require_int(value: int | None, field_name: str) -> int:
    """把 Pydantic 已校验字段转成整数，避免依赖 assert。"""
    if value is not None:
        return value
    raise ApiError(
        status_code=400,
        code="runtime_config_invalid",
        message="运行时配置字段缺失",
        details={"field": field_name},
    )


def _require_secret(value: SecretStr | None, field_name: str) -> SecretStr:
    """把 Pydantic 已校验密钥字段转成 SecretStr，避免依赖 assert。"""
    if value is not None:
        return value
    raise ApiError(
        status_code=400,
        code="runtime_config_invalid",
        message="运行时配置字段缺失",
        details={"field": field_name},
    )
