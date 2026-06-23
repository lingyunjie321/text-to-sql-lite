# 可运营 demo 级日志系统设计

## 背景

当前项目已经具备工作流级 `TraceEvent`，可以把单次 Text-to-SQL 运行过程返回给 API 和前端开发者调试面板。这个 Trace 适合展示链路和解释节点行为，但它不是完整日志系统：项目内还没有统一 `logging` 初始化、请求日志、结构化运行事件、文件日志、日志轮转、异常源位置记录或敏感信息脱敏。

项目也已经开始从纯面试 demo 走向更真实的服务形态：

- `workflow.yaml` 默认模型 provider 已是 `openai_compatible`，需要读取真实 API key 环境变量。
- 数据库配置支持 SQLite、PostgreSQL、MySQL，服务型数据库密码来自环境变量。
- `create_app` 已采用懒加载服务实例，避免 import 阶段读取真实 LLM 凭据。

因此日志系统第一阶段不能只围绕工作流节点做可观测性，还必须覆盖服务初始化、配置解析、LLM provider、数据库连接、异常分类和敏感信息保护。

## 目标

1. 使用 Python 标准库 `logging` 构建统一日志系统，不新增日志库依赖。
2. 同时输出控制台日志和本地文件日志，方便本地开发和持续排查。
3. 控制台日志使用人类可读文本，文件日志使用 JSON Lines。
4. 文件日志写入 `logs/app.log`，按天轮转，默认保留 14 天。
5. 每条日志携带稳定公共字段，例如 `event`、`request_id`、`workflow_name`、`node_name`、`duration_ms`。
6. 异常日志必须记录日志调用位置和异常真正抛出位置，包含文件、行号和函数名。
7. 第一阶段引入项目自定义异常体系，替换主链路中排障价值高的散乱 `ValueError`。
8. 默认不记录完整 prompt、完整 SQL、完整结果集、API key、数据库密码或完整数据库 URL。
9. SQL 日志默认只记录长度和 hash；debug 打开时才记录有限 preview。
10. 保留现有 `TraceEvent`，让 Trace 继续服务 API 响应和前端调试。
11. 用单元测试和集成测试覆盖格式化、脱敏、异常源定位、配置、请求日志、工作流日志和关键失败路径。

## 非目标

1. 第一阶段不接入 ELK、Loki、Datadog、Sentry、OpenTelemetry Collector 等外部平台。
2. 第一阶段不实现完整 metrics 系统，例如成功率、P95、节点耗时分布等聚合指标。
3. 第一阶段不把日志写入数据库。
4. 第一阶段不把完整 traceback 默认写入日志；只在 debug 或显式配置打开时输出。
5. 不重写现有工作流 Trace 模型，也不改变前端 Trace 展示主流程。
6. 不把所有第三方异常机械包裹成项目异常，只收敛项目主链路中的异常边界。

## 总体架构

日志系统作为 `observability` 横切模块存在，和 `workflow`、`api`、`nodes` 解耦。

```text
FastAPI Request
  -> RequestLoggingMiddleware
       - 生成或复用 request_id
       - 写 api.request.started / completed / failed
  -> get_service 懒加载 TextToSQLApiService
       - 写 service.initialization.started / completed / failed
       - 写 database.url.resolved / resolve_failed
       - 写 llm.client.configured / configure_failed
  -> TextToSQLApiService.run_query
       - 创建 WorkflowState，复用 request_id
  -> WorkflowEngine.run
       - 写 workflow.started / completed / failed
       - 每个节点写 workflow.node.started / completed / failed
       - 继续追加 TraceEvent 到 state.trace
  -> API Response
       - 返回原有 trace 字段
       - 控制台输出文本日志
       - logs/app.log 输出 JSON Lines
```

Trace 和 Log 的关系：

- `TraceEvent` 是面向用户、前端和调试面板的“单次运行时间线”。
- `logging` 是面向运行环境、排障和审计的“结构化事件流”。
- 两者共享 `request_id`、`node_name`、`outcome`、`duration_ms` 等字段。
- 默认日志不写完整 `TraceEvent.input_summary/output_summary`。
- 当 `debug=true` 或 `logging.privacy.include_trace_summary=debug_only` 生效时，节点日志可以额外写入脱敏后的 trace 摘要。

## 新增模块

建议新增目录：

```text
src/text_to_sql_demo/
  exceptions.py
  observability/
    __init__.py
    config.py
    context.py
    formatter.py
    logging.py
    middleware.py
    events.py
    redaction.py
```

### `exceptions.py`

统一定义项目异常体系。第一阶段将主链路中的散乱 `ValueError` 收敛为明确异常类型。

```text
TextToSQLDemoError
ConfigurationError
CredentialMissingError
DatabaseConfigurationError
DatabaseConnectionError
DatabaseExecutionError
LLMConfigurationError
LLMProviderError
WorkflowConfigurationError
NodeExecutionError
```

使用原则：

- 配置加载、配置引用、环境变量缺失使用配置类异常。
- 数据库 URL 解析、连接和执行失败使用数据库类异常。
- LLM provider 配置缺失、HTTP 调用失败、响应格式异常使用 LLM 类异常。
- 节点依赖缺失、节点执行中出现项目内可识别错误时使用节点类异常。
- 第三方库异常可以在边界处转换为项目异常，并保留原始异常作为 `__cause__`。

### `observability/config.py`

定义日志配置模型，供 `WorkflowConfig` 引用。建议配置形态：

```yaml
logging:
  enabled: true
  level: INFO

  console:
    enabled: true
    format: text

  file:
    enabled: true
    path: logs/app.log
    format: json
    rotation: daily
    backup_count: 14
    encoding: utf-8

  privacy:
    sql_preview: debug_only
    prompt_preview: disabled
    include_trace_summary: debug_only
    include_traceback: debug_only
    max_preview_chars: 160
    redact_keys:
      - password
      - token
      - api_key
      - secret
      - authorization
      - api-key
      - x-api-key
```

配置语义：

- `console.format=text` 表示控制台人类可读。
- `file.format=json` 表示 `logs/app.log` 使用 JSON Lines。
- `rotation=daily` 使用标准库 `TimedRotatingFileHandler`。
- `sql_preview=debug_only` 表示默认只记录 SQL 长度和 hash，debug 才记录 preview。
- `prompt_preview=disabled` 表示第一阶段不记录 prompt preview，只允许记录 prompt 长度、hash 和 summary。
- `include_traceback=debug_only` 表示默认不输出完整 traceback。

### `observability/context.py`

使用 `contextvars` 保存当前请求、工作流和节点上下文：

- `request_id`
- `workflow_name`
- `node_name`
- `node_type`

对外提供：

- `set_request_context`
- `set_workflow_context`
- `set_node_context`
- `clear_context`
- `get_log_context`

formatter 和 event helpers 会读取这些上下文，自动补齐日志字段。

### `observability/formatter.py`

实现两个 formatter：

- `ConsoleLogFormatter`：输出短文本，面向本地开发阅读。
- `JsonLogFormatter`：输出 JSON Lines，面向文件、检索和后续采集。

公共字段：

- `timestamp`
- `level`
- `logger`
- `event`
- `message`
- `request_id`
- `workflow_name`
- `node_name`
- `node_type`
- `duration_ms`
- `outcome`
- `attempt_count`
- `termination_reason`

源位置字段：

- `source_file`
- `source_line`
- `source_function`

异常字段：

- `error_type`
- `error_message`
- `error_file`
- `error_line`
- `error_function`
- `traceback`，仅 debug 或显式配置打开时输出。

注意：如果日志通过 `events.py` 封装，必须使用 `stacklevel`，避免 `source_file/source_line` 永远指向封装层。

### `observability/logging.py`

提供统一入口：

- `configure_logging(config: LoggingConfig) -> None`
- `get_logger(name: str) -> logging.Logger`

实现要求：

- `configure_logging` 在 FastAPI app 创建时调用。
- 测试中允许重复调用，但不能重复添加 handler。
- 创建 `logs/` 目录时使用 `mkdir(parents=True, exist_ok=True)`。
- 控制台 handler 和文件 handler 可以独立关闭。
- 文件 handler 使用 `TimedRotatingFileHandler`，默认保留 14 天。

### `observability/middleware.py`

实现 FastAPI 请求日志中间件：

- 请求开始：`api.request.started`
- 请求完成：`api.request.completed`
- 请求异常：`api.request.failed`

记录字段：

- HTTP method
- path
- status_code
- duration_ms
- request_id

请求体默认不写日志。响应体不写日志。

### `observability/events.py`

集中封装业务事件日志，避免业务代码到处手写字段：

- `log_service_initialization_started`
- `log_service_initialization_completed`
- `log_service_initialization_failed`
- `log_database_url_resolved`
- `log_database_url_resolve_failed`
- `log_llm_client_configured`
- `log_llm_client_configure_failed`
- `log_llm_request_completed`
- `log_llm_request_failed`
- `log_workflow_started`
- `log_workflow_completed`
- `log_workflow_failed`
- `log_node_started`
- `log_node_completed`
- `log_node_failed`
- `log_sql_validation_failed`
- `log_sql_execution_failed`
- `log_repair_attempted`
- `log_repair_exhausted`

边界规则：

- `WorkflowEngine` 负责通用工作流和节点生命周期事件。
- `TextToSQLApiService` 和 `get_service` 负责服务初始化、配置、数据库 URL、LLM client 配置事件。
- 具体节点只记录少量领域事件，例如 SQL 校验失败、SQL 执行失败、修复尝试和修复耗尽。
- LLM provider adapter 负责记录 provider 调用成功或失败，但不能记录 API key、Authorization header、完整 prompt。

### `observability/redaction.py`

实现递归脱敏和摘要：

- key 命中 `password`、`token`、`api_key`、`secret`、`authorization`、`api-key`、`x-api-key` 时替换为 `***REDACTED***`。
- 数据库 URL 使用 SQLAlchemy URL 或 URL parser 脱敏，隐藏 password，不输出完整凭据。
- SQL 默认输出 `sql_length` 和 `sql_hash`。
- debug 打开时输出 `sql_preview`，长度受 `max_preview_chars` 限制。
- prompt 默认输出 `prompt_length` 和 `prompt_hash`，不输出 preview。
- LLM usage 可以在 debug 日志中输出，但必须先脱敏。

脱敏逻辑是第一阶段核心能力，必须先于业务日志接入完成。

## 日志级别策略

| 级别 | 使用场景 |
| --- | --- |
| `INFO` | 请求完成、工作流开始/完成、节点成功、LLM 调用成功、数据库连接配置解析成功 |
| `WARNING` | SQL 校验失败、SQL 执行失败但进入修复、进入修复循环、修复次数耗尽、用户编辑 SQL 执行失败 |
| `ERROR` | 服务初始化失败、配置错误、凭据缺失、节点代码异常、LLM provider 调用异常、数据库连接异常、未捕获请求异常 |
| `DEBUG` | SQL preview、prompt summary、更详细 trace 摘要、LLM usage、完整 traceback |

说明：

- Text-to-SQL 工作流中的 SQL 校验失败是可恢复业务路径，默认用 `WARNING`。
- 修复耗尽表示当前请求失败，但服务本身未崩，默认用 `WARNING`。
- 配置、凭据、外部 provider、数据库连接等不可恢复问题用 `ERROR`。

## 事件命名

第一阶段稳定支持以下事件：

| 事件 | 触发位置 | 级别 |
| --- | --- | --- |
| `api.request.started` | FastAPI middleware | `INFO` |
| `api.request.completed` | FastAPI middleware | `INFO` |
| `api.request.failed` | FastAPI middleware | `ERROR` |
| `service.initialization.started` | `get_service` | `INFO` |
| `service.initialization.completed` | `get_service` | `INFO` |
| `service.initialization.failed` | `get_service` | `ERROR` |
| `database.url.resolved` | 数据库 URL 解析成功 | `INFO` |
| `database.url.resolve_failed` | 数据库 URL 解析失败 | `ERROR` |
| `llm.client.configured` | LLM client 构建成功 | `INFO` |
| `llm.client.configure_failed` | LLM client 构建失败 | `ERROR` |
| `llm.request.completed` | LLM provider 调用成功 | `INFO` |
| `llm.request.failed` | LLM provider 调用失败 | `ERROR` |
| `workflow.started` | `WorkflowEngine.run` | `INFO` |
| `workflow.completed` | `WorkflowEngine.run` | `INFO` |
| `workflow.failed` | `WorkflowEngine.run` | `ERROR` |
| `workflow.node.started` | `WorkflowEngine._execute_node` | `INFO` |
| `workflow.node.completed` | `WorkflowEngine._execute_node` | `INFO` |
| `workflow.node.failed` | `WorkflowEngine._execute_node` | `ERROR` |
| `sql.validation.failed` | SQL 校验节点 | `WARNING` |
| `sql.execution.failed` | SQL 执行节点 | `WARNING` |
| `repair.attempted` | SQL 修复节点 | `WARNING` |
| `repair.exhausted` | 错误反思或终止节点 | `WARNING` |

## 异常处理原则

成熟边界是：

```text
底层函数：
  发现无法继续 -> raise 明确项目异常

边界层：
  捕获异常 -> 记录结构化 log -> 转换成 API 响应 / 工作流错误 / 终止状态
```

不建议每个函数都 `logger.error(...)` 后再 `raise`，因为会导致重复日志、缺少完整上下文和噪声过大。

第一阶段应重点改造这些主链路：

- LLM client 构建和 provider 调用。
- 数据库 URL 解析和数据库执行。
- 工作流配置引用错误。
- 节点依赖缺失。
- 服务初始化失败。

异常日志默认包含两类位置：

```json
{
  "source_file": "调用 logger 的文件",
  "source_line": 123,
  "source_function": "调用 logger 的函数",
  "error_file": "真正抛异常的文件",
  "error_line": 45,
  "error_function": "真正抛异常的函数"
}
```

实现方式：

- `source_*` 从 `logging.LogRecord` 的 `pathname`、`lineno`、`funcName` 获取。
- `error_*` 从异常 `__traceback__` 最后一帧获取。
- event helpers 必须正确设置 `stacklevel`。

## 安全与隐私策略

默认不记录：

- 完整 prompt。
- 完整 SQL。
- 完整查询结果集。
- API key。
- Authorization header。
- 数据库密码。
- 完整数据库 URL。
- `.env.local` 内容。

默认允许记录：

- SQL 长度。
- SQL hash。
- prompt summary 中的计数信息。
- 模型 alias。
- provider 名称。
- database connection name。
- database driver。
- 错误类型。
- 错误摘要。

debug 时可记录：

- SQL preview，最多 `max_preview_chars`。
- trace input/output summary 的脱敏摘要。
- LLM usage。
- 完整 traceback。

debug 时仍不允许记录：

- API key。
- Authorization header。
- 数据库密码。
- 完整 prompt。

## 测试计划

新增测试：

1. `tests/unit/observability/test_redaction.py`
   - 脱敏 password/token/api_key/authorization。
   - 嵌套 dict/list 能递归脱敏。
   - 数据库 URL 脱敏不泄露密码。
   - SQL 默认只输出长度和 hash，debug 才输出 preview。
   - prompt 默认不输出 preview。

2. `tests/unit/observability/test_json_formatter.py`
   - JSON 字段稳定。
   - context 字段能自动注入。
   - source file/source line/source function 存在。
   - exception 字段包含 error file/error line/error function。

3. `tests/unit/observability/test_console_formatter.py`
   - 控制台输出为可读文本。
   - 关键字段不丢失。
   - 敏感字段不出现在文本日志中。

4. `tests/unit/observability/test_logging_config.py`
   - `configure_logging` 不重复添加 handler。
   - 同时创建 console handler 和 timed rotating file handler。
   - `enabled=false` 时不输出项目业务事件。

5. `tests/unit/test_project_exceptions.py`
   - 项目异常继承关系稳定。
   - 核心异常类型可被统一捕获为 `TextToSQLDemoError`。

6. `tests/integration/test_observability_service.py`
   - 服务初始化成功产生初始化日志。
   - LLM key 缺失产生 `service.initialization.failed` 和 `llm.client.configure_failed`。
   - 日志中不出现真实 key 或数据库密码。

7. `tests/integration/test_observability_workflow.py`
   - 成功工作流产生 `workflow.started/completed` 和节点 completed 事件。
   - 节点异常产生 `workflow.node.failed` 和 `workflow.failed`。
   - 修复耗尽产生 `repair.exhausted`。
   - 异常日志包含 `error_file` 和 `error_line`。

8. `tests/integration/test_observability_api.py`
   - API 请求日志包含 method、path、status_code、duration_ms、request_id。
   - API 响应中的 trace 不因日志系统改变而丢失。
   - `logs/app.log` 产生 JSON Lines。

完成前继续运行：

```bash
ruff check .
pytest
```

## 分阶段实施

### 阶段 1：异常体系与脱敏基础

- 新增 `exceptions.py`。
- 新增 `observability/redaction.py`。
- 新增 `observability/config.py`。
- 替换主链路中的散乱 `ValueError` 为项目异常。
- 完成异常和脱敏单元测试。

### 阶段 2：日志基础设施

- 新增 `context.py`、`formatter.py`、`logging.py`。
- 实现控制台文本 formatter。
- 实现 JSON Lines formatter。
- 实现每日轮转文件 handler。
- 在 `create_app` 中初始化日志。
- 完成 formatter 和 logging config 测试。

### 阶段 3：API 与服务初始化接入

- 增加请求日志中间件。
- 在 `get_service` 和 `TextToSQLApiService.__init__` 边界记录初始化事件。
- 在数据库 URL 解析和 LLM client 构建边界记录成功/失败事件。
- 保证初始化失败日志不泄露凭据。

### 阶段 4：工作流接入

- 在 `WorkflowEngine.run` 和 `_execute_node` 中记录工作流、节点事件。
- 保持现有 `TraceEvent` 行为不变。
- debug 时允许节点日志携带脱敏 trace summary。
- 增加成功、失败和终止路径集成测试。

### 阶段 5：领域事件接入

- 在 SQL 校验、SQL 执行、修复相关节点中记录领域事件。
- 在 LLM provider adapter 中记录 provider 调用成功/失败事件。
- 确保 SQL、prompt、结果预览默认不泄露。
- 更新 README、整体架构、工作流文档和完成度分析。

### 阶段 6：后续扩展预留

- 如项目进入部署阶段，再增加 metrics 或 OpenTelemetry 适配。
- 适配时应复用当前事件字段和 `request_id` 语义，避免重写业务节点。

## 设计约束

1. 不让业务节点导入 FastAPI 或外部日志平台 SDK。
2. 不在 API route 中拼接 prompt 或写复杂日志逻辑。
3. 不把完整 prompt、凭据、数据库 URL、结果集写入 INFO/WARNING 日志。
4. 不改变 `NodeFactory`、`NodeRegistry` 的扩展规则。
5. 每个新增核心模块都要有测试。
6. 注释、docstring 和文档正文优先使用中文。
7. 日志系统异常不能影响业务主流程。
8. 文件日志路径必须可配置，默认 `logs/app.log`。
9. `logs/` 应加入 `.gitignore`，避免提交本地运行日志。

## 验收标准

1. 启动 API 后，每次 `/api/v1/query` 请求至少产生请求开始、请求完成、工作流开始、节点完成、工作流完成日志。
2. 同一个请求的日志和 API trace 使用同一个 `request_id`。
3. 控制台日志为人类可读文本。
4. `logs/app.log` 为 JSON Lines，并按天轮转。
5. SQL 默认只记录长度和 hash；debug 打开时才记录 preview。
6. 服务初始化失败时，日志能定位到配置、LLM 或数据库阶段。
7. 异常日志包含日志调用位置和异常源位置。
8. SQL 修复失败三次时，日志能看出每轮修复和最终 `repair.exhausted`。
9. 测试能证明 API key、Authorization、数据库密码不会出现在日志输出中。
10. `ruff check .` 和 `pytest` 通过。

