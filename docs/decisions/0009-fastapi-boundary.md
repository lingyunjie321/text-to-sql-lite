# ADR 0009：FastAPI HTTP 边界与可信启动

## 状态

Accepted

## 决策

Stage 9 固定 `fastapi==0.139.2`。测试使用 Starlette 1.3 推荐的
`httpx2==2.9.1`，不使用已弃用的 HTTPX TestClient 路径。项目暴露标准 ASGI
目标 `app.main:app`，本阶段不增加部署服务器依赖。

唯一业务接口是同步 `POST /api/v1/text-to-sql`。API 负责：

- 严格校验问题、datasource、Schema 和 debug；
- 生成独立 request/trace UUID；
- 从 FastAPI 可信依赖取得固定身份；
- 把请求转换为 Stage 8 初始 State；
- 把严格终态映射为独立 QueryResponse。

API 不复制 SQL 路由、安全校验、执行或修复逻辑。业务终态返回 HTTP 200；
非法请求由 FastAPI 返回 422；未授权 debug 返回 403；Workflow 外未知异常返回
500。403/500 仍使用 QueryResponse 形状和固定脱敏错误。

## 启动与依赖

生产 lifespan 在启动时加载并校验既有数据库/LLM 环境配置，打开 Connector，
创建 Provider 和 WorkflowContext；缺少 Secret 或数据库不可用时启动失败。关闭
时只关闭本 lifespan 创建的 Connector。导入 `app.main` 不读取配置或 Secret。

测试使用 `create_app(services=...)` 注入 frozen `ApplicationServices`，不会读取
环境或启动真实外部依赖。

## 授权

生产 Context 固定：

- datasource：`pagila`；
- Schema：`public`；
- tables：18 条 MVP Case 需要的 13 张显式限定表。

allowlist 不包含 `public.staff`。请求 `schemas` 只能由 Stage 8 权限节点缩小范围。
Provider、Connector、身份和 table allowlist 不能由请求 JSON 或 Header注入。

默认固定身份 `can_debug=False`。只有 FastAPI dependency override/未来可信认证
适配器可提供 `can_debug=True`；任意请求 Header 都不会提升权限。当前公开响应
没有 debug 扩展字段，因此授权 debug 也不会返回 Prompt、DSN 或内部 State。

## 响应安全

`QueryResponse` 不直接序列化 `SQLTaskState`：

- 成功返回当前 SQL、公开列和规范化结果；
- 澄清不返回 SQL/结果；
- 所有失败不返回当前或历史 SQL，只返回 `ErrorType`、稳定 code 和公开消息；
- 返回结构验证 FinalStatus、ErrorType、repair count 和 payload 互斥；
- `rows` 只接受递归 JSON 值，非 JSON 结果在序列化前 fail-closed；
- 请求校验 422 使用固定错误，不回显完整非法输入；
- 未知异常不返回异常文本、堆栈、DSN、Prompt 或依赖 repr。

## 超时

API 复用 Stage 8 唯一的 120 秒单调时钟预算、32 步限制和每外部调用 30 秒上限。
不再包一层无法停止后台线程的 `asyncio.wait_for`，避免 HTTP 已超时但数据库线程
继续执行的伪取消。

## 暂不实现

- Trace sink、Comparator、JSONL runner 和评测；
- 多用户认证、CORS、限流、Gateway 和部署服务器；
- 多轮 Session、Checkpoint、Memory、流式或异步任务接口。
