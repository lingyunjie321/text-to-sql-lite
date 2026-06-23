from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy.engine import URL

from text_to_sql_demo.api.models import ExecuteSQLRequest, QueryRequest
from text_to_sql_demo.config.env import load_env_files
from text_to_sql_demo.config.loader import load_workflow_config
from text_to_sql_demo.config.models import DatabaseConnectionConfig, NodeConfig, WorkflowConfig
from text_to_sql_demo.db.init_db import initialize_database
from text_to_sql_demo.execution.sql_executor import SQLExecutor
from text_to_sql_demo.llm.client import LLMClient
from text_to_sql_demo.llm.factory import build_llm_client
from text_to_sql_demo.llm.models import ModelProfile
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
    ) -> None:
        load_env_files()
        self.config = load_workflow_config(config_path)
        self.database_url = database_url or _resolve_database_url(self.config)
        self.llm_client = llm_client or build_llm_client(self.config)
        self.run_store = run_store or InMemoryRunStore()

        # 导入节点包触发 register_node 装饰器，避免默认注册表为空。
        import text_to_sql_demo.nodes  # noqa: F401

    def run_query(self, request: QueryRequest) -> dict[str, Any]:
        """执行 Text-to-SQL 工作流并返回演示响应。"""
        self.ensure_database()
        schema = self.read_schema()
        state = WorkflowState(
            user_question=request.question,
            data={
                "schema": schema.model_dump(mode="python"),
                "target_dialect": request.target_dialect,
                "max_repair_attempts": request.max_attempts,
                "debug": request.debug,
            },
        )
        engine = WorkflowEngine(
            config=self._config_for_request(max_attempts=request.max_attempts),
            node_factory=NodeFactory(dependencies=self._node_dependencies()),
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
        self.ensure_database()
        schema = self.read_schema()
        validation = SQLValidator().validate(
            sql=request.sql,
            schema=schema,
            dialect=request.target_dialect,
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
            database_url=self.database_url,
            max_rows=request.max_rows,
        )
        return _serialize_direct_sql(
            status="success" if result.success else "failed",
            sql=executable_sql,
            result=result.model_dump(mode="python"),
            error=result.error,
        )

    def read_schema(self) -> DatabaseSchemaMetadata:
        """读取当前 demo 数据库 Schema。"""
        return read_schema_metadata(self.database_url)

    def ensure_database(self) -> None:
        """初始化缺失的 SQLite demo 数据库。"""
        db_path = _sqlite_path_from_url(self.database_url)
        if db_path is not None and not db_path.exists():
            initialize_database(db_path)

    def _node_dependencies(self) -> NodeDependencies:
        return NodeDependencies(
            values={
                "database_url": self.database_url,
                "llm_client": self.llm_client,
                "model_profiles": _model_profiles(self.config),
            }
        )

    def _config_for_request(self, *, max_attempts: int) -> WorkflowConfig:
        config = self.config.model_copy(deep=True)
        config.workflow.max_repair_attempts = max_attempts
        for node_name, node_config in list(config.nodes.items()):
            if node_config.type in {"error_reflection", "error_classification"}:
                raw_config = node_config.model_dump(mode="python")
                raw_config["max_repair_attempts"] = max_attempts
                config.nodes[node_name] = NodeConfig.model_validate(raw_config)
        return config


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


def _resolve_database_url(config: WorkflowConfig) -> str:
    connection = config.database.connections[config.database.default]
    if connection.url_env:
        env_value = os.getenv(connection.url_env)
        if env_value:
            return env_value

    structured_url = _build_structured_database_url(connection)
    if structured_url is not None:
        return structured_url

    if connection.fallback_url:
        return connection.fallback_url

    raise ValueError(f"数据库连接 {config.database.default} 缺少可用的连接配置")


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
        raise ValueError("服务型数据库连接缺少 port")

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
    raise ValueError(f"服务型数据库连接缺少 {field_name}")


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
        raise ValueError(f"数据库连接 {label} 环境变量未设置: {env_name}")

    if value:
        return value

    raise ValueError(f"服务型数据库连接缺少 {label}")


def _resolve_required_env(env_name: str | None, label: str) -> str:
    if not env_name:
        raise ValueError(f"服务型数据库连接必须配置 {label}，避免在配置文件中明文写入密码")

    env_value = os.getenv(env_name)
    if env_value:
        return env_value

    raise ValueError(f"数据库连接 {label} 环境变量未设置: {env_name}")


def _sqlite_path_from_url(database_url: str) -> Path | None:
    prefix = "sqlite:///"
    if not database_url.startswith(prefix) or database_url == "sqlite:///:memory:":
        return None
    raw_path = database_url.removeprefix(prefix)
    path = Path(raw_path)
    if not path.is_absolute():
        path = Path.cwd() / path
    return path
