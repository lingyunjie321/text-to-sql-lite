# 第九开发阶段：FastAPI 同步接口设计

## 目标

提供主规格唯一的同步 `POST /api/v1/text-to-sql`，把可信服务端依赖和静态 Pagila
授权注入 Stage 8 Workflow，并把严格终态映射为稳定、脱敏的 API 响应。

## 依赖

- 生产依赖固定 `fastapi==0.139.2`；
- 测试依赖固定 `httpx2==2.9.1`，仅用于 Starlette 1.3 `TestClient`；
- 不增加厂商 SDK、异步任务队列、认证平台、Session 或多租户能力；
- 不增加 Uvicorn 等部署依赖，本阶段交付标准 ASGI `app`。

## 模块

```text
app/
├── api/
│   ├── __init__.py
│   ├── application.py
│   ├── bootstrap.py
│   └── models.py
└── main.py
```

## API 契约

### QueryRequest

- `question: str`：去除首尾空白后长度 1～2000；
- `datasource_id: str = "pagila"`：非空，是否授权由 Workflow 的可信 Context
  判断；
- `schemas: list[str]`：每项非空，只能由 Workflow 缩小服务端 Schema；
- `debug: bool = False`：严格布尔值；
- 额外字段拒绝。

API 保留问题正文供 Stage 8 做 NFKC、空白和相对日期规范；API 只做早期长度和结构
验证。

### QueryResponse

固定字段与主规格一致：

- `request_id`、`trace_id`、`status`；
- 成功时的 `sql`、`columns`、`rows`、行数和截断标记；
- `attempts`、`repair_count`；
- 澄清或脱敏公开错误。

成功、澄清和失败三类响应严格互斥。只有成功返回 SQL/结果；权限、安全和其他失败
不返回当前或历史 SQL。合法空结果仍是成功。

业务终态使用 HTTP 200；请求结构错误使用 FastAPI 422。普通固定身份请求
`debug=true` 时，在 Workflow 前返回 HTTP 403 + `REJECTED_SECURITY` 的同一
响应模型。Workflow 外的未知异常返回 HTTP 500 + `FAILED_INTERNAL`，不返回异常
文本、堆栈或依赖配置。

## 可信依赖与启动

`ApplicationServices` 保存 Stage 8 `WorkflowContext` 和 Workflow runner。
生产 `app` 在 FastAPI lifespan 中：

1. 加载并校验现有数据库和 LLM 环境配置；
2. 创建并打开 PostgreSQL Connector；
3. 创建 OpenAI-compatible Provider；
4. 注入固定 `pagila` datasource、`public` Schema 和 Gold MVP 所需的显式
   `schema.table` allowlist；
5. 关闭时只关闭本次 lifespan 创建的 Connector。

缺少 DSN、模型、API Key 或数据库不可用时，启动失败，不进入宽松模式。导入
`app.main` 本身不读取 Secret，便于 ASGI discovery 和无凭据单元测试。

测试通过 `create_app(services=...)` 注入 Stub；请求正文不能声明 Provider、
Connector、身份或表 allowlist。

## 身份与 debug

MVP 使用可信依赖返回固定 `RequestIdentity`，不从请求 JSON、Header 或 Cookie
构造身份。默认身份 `can_debug=False`；测试可用 FastAPI dependency override
注入可信 debug 身份。当前响应契约没有额外 debug 字段，即使授权也不会返回
Prompt、DSN、完整 Trace 或未脱敏错误。

## ID、超时与错误

- API 为每个已解析请求生成独立 UUID `request_id` 和 `trace_id`；
- Stage 8 的单调时钟、120 秒总预算、每外部调用最大 30 秒和 32 步限制保持唯一
  Workflow timeout 实现；
- API 不添加会让后台线程继续执行的第二套 `asyncio.wait_for`；
- 任何未知 API/runner 异常只映射固定 `API_INTERNAL_ERROR`；
- Pydantic/FastAPI 序列化不直接暴露 `SQLTaskState`。

## 静态 Pagila 授权

生产 allowlist 只包含 18 条 MVP Case 所需的 13 张 `public` 表：

`actor`、`address`、`category`、`city`、`country`、`customer`、`film`、
`film_actor`、`film_category`、`inventory`、`language`、`payment`、`rental`。

不包含 `staff` 或其他可见对象。请求只能用 `schemas` 缩小 `public`，不能扩大
table 范围。

## 测试

- 请求模型：空白、超过 2000、未知字段、非法 Schema、严格 debug；
- 响应模型：全部 FinalStatus 的互斥和字段映射；
- API：成功、空结果、澄清、权限、安全、修复耗尽和内部失败；
- 安全：未知 datasource、扩大 Schema、未授权 debug 零 Provider/Connector；
- 错误脱敏：不返回 DSN、Prompt、驱动消息或堆栈；
- OpenAPI：路径、方法、Request/Response schema；
- lifespan：注入服务不读取环境，生产缺配置启动失败；
- 集成：Stub Provider + 真实 Pagila 经 HTTP TestClient 完成首次成功和一次修复。

## 暂不实现

- Trace sink、Comparator、Case runner 和评测报告；
- 多用户认证、debug 扩展载荷、限流、CORS、Gateway 和部署服务器；
- 后台任务、流式响应、多轮 Session、Checkpoint 和 Memory。
