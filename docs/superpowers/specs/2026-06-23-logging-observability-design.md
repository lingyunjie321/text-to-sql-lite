# 可运营 demo 级日志系统设计

## 背景

当前项目已经具备工作流级 `TraceEvent`，可以把单次 Text-to-SQL 运行过程返回给 API 和前端开发者调试面板。这个 Trace 很适合面试展示和链路解释，但还不是完整日志系统：项目内没有统一 `logging` 初始化、请求日志、结构化运行事件、敏感信息脱敏或日志配置开关。

项目接下来不再只面向一次性面试演示，因此第一阶段目标是构建“可运营 demo”级 observability：本地或小规模部署时能排障、能审计一次请求链路、能理解工作流失败原因，同时保持项目清晰、轻量、易测。

## 目标

1. 使用 Python 标准库 `logging` 构建统一日志基础设施，默认输出结构化 JSON 日志。
2. 给每个 API 请求、工作流运行和节点执行绑定稳定 `request_id`。
3. 记录请求、工作流、节点、SQL 校验/执行、修复循环等关键事件。
4. 保留现有 `TraceEvent`，让 Trace 继续服务 API 响应和前端调试。
5. 默认脱敏 prompt、数据库连接串、token、password、api_key、secret、authorization 等敏感信息。
6. 通过配置控制日志开关、日志级别、输出格式和敏感字段策略。
7. 用单元测试和集成测试覆盖日志格式、脱敏、上下文注入和关键事件。

## 非目标

1. 第一阶段不接入 ELK、Loki、Datadog、Sentry、OpenTelemetry Collector 等外部平台。
2. 第一阶段不实现完整 metrics 系统，例如成功率、P95、节点耗时分布等聚合指标。
3. 第一阶段不把完整 prompt、完整 SQL、完整结果集写入日志。
4. 不重写现有工作流 Trace 模型，也不改变前端 Trace 展示主流程。

## 总体架构

日志系统作为 `observability` 横切模块存在，和 `workflow`、`api`、`nodes` 解耦。

```text
FastAPI Request
  -> RequestLoggingMiddleware
       - 生成或复用 request_id
       - 写 api.request.started / completed / failed
  -> TextToSQLApiService.run_query
       - 创建 WorkflowState
       - 将 request_id 写入上下文
  -> WorkflowEngine.run
       - 写 workflow.started / completed / failed
       - 每个节点写 workflow.node.started / completed / failed
       - 继续追加 TraceEvent 到 state.trace
  -> API Response
       - 返回原有 trace 字段
       - 运行环境收到 JSON log
```

Trace 和 Log 的关系：

- `TraceEvent` 是面向用户、前端和调试面板的“单次运行时间线”。
- `logging` 是面向运行环境、排障和审计的“结构化事件流”。
- 两者共享 `request_id`、`node_name`、`outcome`、`duration_ms` 等字段，但输出渠道和详细程度不同。

## 新增模块

建议新增目录：

```text
src/text_to_sql_demo/observability/
  __init__.py
  context.py
  formatter.py
  logging.py
  middleware.py
  events.py
  redaction.py
```

### `context.py`

使用 `contextvars` 保存当前请求和节点上下文：

- `request_id`
- `workflow_name`
- `node_name`
- `node_type`

对外提供 `set_request_context`、`set_node_context`、`clear_context`、`get_log_context` 等函数。日志 formatter 会读取这些上下文，自动补齐字段。

### `formatter.py`

实现 `JsonLogFormatter`。每条日志至少包含：

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
- `error_type`
- `error_message`

缺失字段输出为 `null` 或直接省略，优先保持 JSON 稳定、可测试。

### `logging.py`

提供统一入口：

- `configure_logging(config: LoggingConfig) -> None`
- `get_logger(name: str) -> logging.Logger`

`configure_logging` 只在 FastAPI app 创建时调用一次。测试中允许重复调用，但必须避免重复添加 handler。

### `middleware.py`

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

请求体默认不写日志。

### `events.py`

集中封装业务事件日志，避免业务代码到处手写字段：

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

`WorkflowEngine` 负责通用工作流和节点事件。具体节点只在领域信息明确时记录领域事件。

### `redaction.py`

实现递归脱敏：

- key 命中 `password`、`token`、`api_key`、`secret`、`authorization` 时替换为 `***REDACTED***`
- 数据库 URL 隐藏用户名、密码和 host 之外的敏感信息
- prompt 默认只记录长度、hash 和短摘要
- SQL 默认只记录长度、hash 和可选 preview

脱敏逻辑应被单元测试覆盖，且任何日志事件在输出前都通过脱敏处理。

## 配置设计

在现有 `WorkflowConfig` 中新增 `logging` 配置段：

```yaml
logging:
  enabled: true
  level: INFO
  format: json
  include_sql: false
  include_prompt: false
  include_result_preview: false
  max_preview_chars: 160
  redact_keys:
    - password
    - token
    - api_key
    - secret
    - authorization
```

说明：

- `enabled=false` 时只保留框架自身日志，不输出项目业务事件。
- `format` 第一阶段支持 `json` 和 `text`。
- `include_sql/include_prompt/include_result_preview` 默认关闭。
- 即使开启 include，也必须先经过脱敏和长度限制。

## 事件命名

第一阶段稳定支持以下事件：

| 事件 | 触发位置 | 用途 |
| --- | --- | --- |
| `api.request.started` | FastAPI middleware | 请求进入服务 |
| `api.request.completed` | FastAPI middleware | 请求正常结束 |
| `api.request.failed` | FastAPI middleware | 请求异常退出 |
| `workflow.started` | `WorkflowEngine.run` | 工作流开始 |
| `workflow.completed` | `WorkflowEngine.run` | 工作流正常结束 |
| `workflow.failed` | `WorkflowEngine.run` | 工作流异常或节点错误终止 |
| `workflow.node.started` | `WorkflowEngine._execute_node` | 节点开始 |
| `workflow.node.completed` | `WorkflowEngine._execute_node` | 节点成功 |
| `workflow.node.failed` | `WorkflowEngine._execute_node` | 节点异常 |
| `sql.validation.failed` | SQL 校验节点 | 记录校验错误分类 |
| `sql.execution.failed` | SQL 执行节点 | 记录执行错误分类 |
| `repair.attempted` | SQL 修复节点 | 记录修复尝试 |
| `repair.exhausted` | 错误反思或终止节点 | 记录修复耗尽 |

## 错误处理

日志系统不能影响业务主流程：

- 日志格式化、脱敏或 handler 失败时，不应让 API 请求失败。
- 节点异常仍由 `WorkflowEngine` 捕获并写入 `WorkflowState.errors` 和 `TraceEvent`。
- 日志中的错误字段只保存错误类型和摘要信息，不保存完整 traceback，除非 `level=DEBUG` 且测试明确覆盖。

## 测试计划

新增测试：

1. `tests/unit/observability/test_redaction.py`
   - 脱敏 password/token/api_key/authorization。
   - 嵌套 dict/list 能递归脱敏。
   - SQL 和 prompt 默认只输出摘要。

2. `tests/unit/observability/test_json_formatter.py`
   - JSON 字段稳定。
   - context 字段能自动注入。
   - exception 字段被摘要化。

3. `tests/unit/observability/test_logging_config.py`
   - `configure_logging` 不重复添加 handler。
   - `enabled=false` 时不输出业务事件。

4. `tests/integration/test_observability_workflow.py`
   - 成功工作流产生 `workflow.started/completed` 和节点 completed 事件。
   - 节点异常产生 `workflow.node.failed` 和 `workflow.failed`。
   - 修复耗尽产生 `repair.exhausted`。

5. `tests/integration/test_observability_api.py`
   - API 请求日志包含 method、path、status_code、duration_ms、request_id。
   - API 响应中的 trace 不因日志系统改变而丢失。

完成前继续运行：

```bash
ruff check .
pytest
```

## 分阶段实施

### 阶段 1：基础设施

- 新增 `observability` 模块。
- 新增 `LoggingConfig`。
- 在 `create_app` 中初始化日志。
- 增加请求日志中间件。
- 完成 formatter、context、redaction 单元测试。

### 阶段 2：工作流接入

- 在 `WorkflowEngine.run` 和 `_execute_node` 中记录工作流、节点事件。
- 保持现有 `TraceEvent` 行为不变。
- 增加成功、失败和终止路径集成测试。

### 阶段 3：领域事件

- 在 SQL 校验、SQL 执行、修复相关节点中记录领域事件。
- 确保 SQL、prompt、结果预览默认不泄露。
- 更新文档中的架构说明和工作流说明。

### 阶段 4：后续扩展预留

- 如项目进入部署阶段，再增加 metrics 或 OpenTelemetry 适配。
- 适配时应复用当前事件字段和 `request_id` 语义，避免重写业务节点。

## 设计约束

1. 不让业务节点导入 FastAPI 或外部日志平台 SDK。
2. 不在 API route 中拼接 prompt 或写复杂日志逻辑。
3. 不把完整 prompt、凭据、数据库 URL、结果集写入 INFO 日志。
4. 不改变 `NodeFactory`、`NodeRegistry` 的扩展规则。
5. 每个新增核心模块都要有测试。
6. 注释、docstring 和文档正文优先使用中文。

## 验收标准

1. 启动 API 后，每次 `/api/v1/query` 请求至少产生请求开始、请求完成、工作流开始、节点完成、工作流完成日志。
2. 同一个请求的日志和 API trace 使用同一个 `request_id`。
3. SQL 修复失败三次时，日志能看出每轮修复和最终 `repair.exhausted`。
4. 测试能证明敏感字段不会出现在日志输出中。
5. `ruff check .` 和 `pytest` 通过。

