# ADR 0005：OpenAI-compatible 结构化 SQL 生成

## 状态

已验证，2026-07-28。

## 决策

第五开发阶段使用单一 OpenAI-compatible `chat/completions` Provider，并通过
项目自有 `LLMProvider` 协议隔离业务层。默认实现使用 Python 标准库 HTTP，
不加入厂商 SDK 或新的生产依赖。

模型输出严格映射为 Pydantic `GeneratedSQL`：

- `sql` 与 `clarification_reason` 必须且只能出现一个非空值；
- 拒绝额外字段、空字符串、Markdown fence、前后说明和不可解析 JSON；
- SQL 只去除首尾空白，不执行、不修复、不自动视为安全。

## 配置

`LLMSettings` 从环境读取：

- `LLM_BASE_URL`；
- `LLM_API_KEY`；
- `LLM_MODEL`；
- `LLM_TIMEOUT_SECONDS`，默认及最大 30 秒；
- `LLM_TEMPERATURE`，只能为 0。

Base URL 仅接受 HTTP(S)，拒绝内嵌用户名/密码、query 和 fragment；远程地址
必须为 HTTPS，仅 localhost 和回环 IP 可使用 HTTP。API key 使用 `SecretStr`，
拒绝空白、控制字符和非可打印 ASCII，只有 Provider 构建认证头时取明文。配置
或异常 repr 不显示 key。

## Prompt 与授权上下文

Prompt 版本为 `mvp-v1`。System message 固定声明 PostgreSQL、单条只读
SELECT/受控 CTE、明确字段、禁止 wildcard/危险能力、只使用提供对象和严格
JSON 二选一输出，并携带 Stage 3 `mvp-v1` 的精确函数白名单和默认/最大
1000 行结果约束。

User message 是确定性 JSON 数据包。生成前必须证明：

- 方言为 `postgres`、问题和候选非空，候选数不超过 Stage 4 `TOP_K=10`；
- Linking 与授权快照 `schema_version` 相同；
- 候选表字段存在且字段类型/nullable 与快照一致；
- JOIN Path 每条边都是快照真实 FK，并连接相邻候选表。

只序列化候选表字段、候选端点内的 PK/FK 和返回 JOIN Path。未选中快照对象、
Gold Case/SQL、Few-shot、RAG、DSN 和 API key 不进入 Prompt。不一致只返回
`generation context is invalid`，不包含对象名。关系类型、字段类型、nullable
和 comments 从同版本快照读取，候选对象只提供命中分数和证据。

问题和元数据 comments 都作为不可信 JSON 数据，不能改写 System message。
Prompt 约束只是提高生成质量，不替代 Stage 3 SQLGlot 安全门。

## HTTP 与错误边界

Provider POST 到配置 Base URL 下的 `/chat/completions`，固定发送：

- 配置模型；
- `temperature=0`；
- System/User messages；
- `response_format={"type": "json_object"}`。

认证只在 Bearer Header。独立 urllib opener 禁止全部 HTTP 重定向，避免认证头
被转发。响应最多读取 1 MiB；envelope、choices、content、usage Token 和
GeneratedSQL 任一不合法都 fail-closed，且 `finish_reason` 必须精确为 `stop`。
不完整响应、底层 HTTP 协议异常、异常深度 JSON 和超大整数解析失败均被归一化，
不向调用方传播原始异常或响应片段。

公开错误固定为：

- `LLM_TIMEOUT`；
- `LLM_CONNECTION_ERROR`；
- `LLM_HTTP_ERROR`；
- `LLM_INVALID_RESPONSE`；
- `LLM_INVALID_OUTPUT`。

公开异常不包含 Base URL、API key、Prompt、HTTP body、模型原文、SQL 或底层
异常链。Stage 5 不自动重试；后续 Workflow 按主规格路由模型超时和格式失败。

## 验证证据

- Stage 1–5 单元测试：276 项通过；
- Stage 1–5 安全测试：37 项通过；
- Stage 1–5 集成测试：54 项通过；
- 本机临时 HTTP server 验证真实 OpenAI-compatible 请求、结构响应和禁用
  redirect；
- 确定性 Stub 验证 Linking → Generate → Validate 的单表、JOIN 和澄清；
- DELETE、多 statement 和 `pg_sleep` 模型输出均未执行，并被 Stage 3 拒绝；
- `.env` 配置结构和 Secret repr 已安全验证，不输出值。

真实外部模型调用不是 Stage 5 确定性门禁；发布质量和 Gold Result 基线按主规格
在 Stage 10 E2E 执行。本阶段的可选外部烟测因外部数据发送权限未获批准而未
执行，不降低本地 Provider 协议和安全测试。

## 延后

SQL attempt、指纹、修复计数、反思、真实执行、LangGraph、FastAPI、Trace、
Comparator、评测 runner 和真实模型 Pagila E2E 属于 Stage 6–10。
