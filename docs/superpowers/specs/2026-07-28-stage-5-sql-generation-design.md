# 第五开发阶段：OpenAI-compatible 结构化 SQL 生成设计

## 目标

在 Stage 4 授权 Schema 候选和 Stage 3 确定性 SQL 安全门之间，实现单模型、
结构化、可替换 Provider 的 SQL 生成。模型只能返回 PostgreSQL SQL 或澄清
原因二者之一；生成结果不执行，也不因 Prompt 约束而被视为安全。

## 范围

### 包含

- `LLM_BASE_URL`、`LLM_API_KEY`、`LLM_MODEL` 环境配置；
- OpenAI-compatible `chat/completions` Provider；
- `LLMProvider` 协议和可注入传输层；
- Pydantic `GeneratedSQL` XOR 契约；
- 确定性、版本化生成 Prompt；
- 候选表、字段、类型、PK/FK 和 JOIN Path 上下文；
- Token usage 与模型标识的统一结果；
- 超时、HTTP、连接、JSON 和结构错误的公开脱敏；
- Stub、真实本地 HTTP 协议集成和生成后安全校验测试。

### 不包含

- SQL 执行、数据库重试或安全放行；
- SQL attempt、指纹、修复计数和反思路由；
- LangGraph、FastAPI、Trace sink 和 Comparator；
- Few-shot、Gold SQL、Embedding、RAG、Rerank；
- 多模型路由、流式响应、工具调用和厂商 SDK；
- Prompt 持久化、完整 Prompt 日志或模型响应日志。

## 公共契约

新增：

```text
app/generation/
├── __init__.py
├── models.py
├── prompt.py
├── provider.py
└── service.py
```

核心模型：

```python
class GeneratedSQL(BaseModel):
    sql: str | None = None
    clarification_reason: str | None = None


@dataclass(frozen=True, slots=True)
class GenerationContext:
    question: str
    normalized_question: str | None
    normalized_time: str | None
    dialect: str
    schema_linking: SchemaLinkingResult
    snapshot: SchemaSnapshot
    max_result_rows: int = 1000


@dataclass(frozen=True, slots=True)
class GenerationResult:
    output: GeneratedSQL
    input_tokens: int
    output_tokens: int
    model: str
    prompt_version: str
```

`GeneratedSQL` 配置 `extra="forbid"` 和 frozen，并强制 `sql` 与
`clarification_reason` 必须且只能有一个非空值。SQL 只去除首尾空白，不解析、
修改或执行。

公共入口：

```python
def generate_sql(
    context: GenerationContext,
    *,
    provider: LLMProvider,
) -> GenerationResult:
    ...
```

## 上下文边界

调用前执行 fail-closed 检查：

- 问题非空，方言精确为 `postgres`；
- 候选表非空且不超过 Stage 4 `TOP_K=10`；
- `snapshot.schema_version` 与 Linking 结果一致；
- 每个候选表和字段都存在于快照；
- 每条 JOIN edge 都存在于快照真实 FK；
- 关系类型、字段类型、nullable 和 comments 等描述性元数据从同版本快照读取，
  不信任候选对象中的重复副本；
- `max_result_rows` 必须为 1～1000 的整数且不能是 bool；
- Prompt 只序列化候选对象及候选端点内的约束。

不一致只抛出 `ValueError("generation context is invalid")`，不包含对象名或
Prompt。Stage 4 返回的是授权视图版本，因此 Workflow 必须传入同一授权快照，
不能混用原始宽快照或新版本。

## Prompt

`PROMPT_VERSION="mvp-v1"`。System message 是固定规则：

- 只生成 PostgreSQL；
- 只能使用提供对象；
- 只允许单条只读 SELECT/受控 CTE；
- 使用明确列，禁止 wildcard；
- 只能调用 Stage 3 `mvp-v1` 的精确函数白名单；
- 必须遵守上下文中的 `max_result_rows`，默认且最大为 1000；
- 优先使用提供 FK JOIN 条件；
- 不能唯一决定时返回澄清；
- 只返回 JSON 对象，键严格为 `sql`、`clarification_reason`。

User message 是 `json.dumps(..., ensure_ascii=False, sort_keys=True)` 的数据包，
包含问题、规范化问题/时间、方言、Schema 版本、候选表字段、PK、FK 和 JOIN
Path。问题、comments 和模型文本都按不可信数据处理，不拼入 System 指令。

Prompt 不读取 Case 文件，不包含 Gold SQL、Few-shot、业务 RAG、凭据或 DSN，
也不进入异常和日志。

## Provider

`LLMProvider` 是 `Protocol`，业务服务只依赖该协议。默认
`OpenAICompatibleLLMProvider` 使用 Python 标准库向
`{LLM_BASE_URL}/chat/completions` POST：

- `Authorization: Bearer ...`；
- `model` 使用配置值；
- `temperature=0`；
- `response_format={"type": "json_object"}`；
- timeout 固定默认 30 秒且配置上限 30 秒。

Provider 最多读取 1 MiB 响应，严格解析 `choices[0].message.content` JSON，
再交给 `GeneratedSQL`。不接受 Markdown fence、前后说明、额外字段或从非法
文本中截取 JSON；`finish_reason` 必须精确为 `stop`。禁止全部 HTTP redirect。
不完整响应、HTTP 协议异常、异常深度 JSON 和超大整数等解析异常都在 Provider
边界内归一化。兼容服务参数差异只允许封装在 Provider 内，不扩散到业务层。

统一错误：

- `LLM_TIMEOUT`；
- `LLM_CONNECTION_ERROR`；
- `LLM_HTTP_ERROR`；
- `LLM_INVALID_RESPONSE`；
- `LLM_INVALID_OUTPUT`。

公开消息固定，不包含 URL、API key、请求、完整 Prompt、HTTP body、模型原文
或底层异常。Stage 5 不自动重试；后续 Workflow 按规格将模型超时/格式无效
路由到 Finalize。

## 配置

在 `app.config` 增加独立 `LLMSettings`：

- `base_url: HttpUrl`；
- `api_key: SecretStr`；
- `model: str`；
- `timeout_seconds: 30`，范围 1～30；
- `temperature: Literal[0] = 0`。

缺少任一必需值、空模型、含凭据/查询/fragment 的 URL 或非零 temperature
启动失败。远程地址必须使用 HTTPS，仅 localhost 和回环 IP 可使用 HTTP。
API key 还必须是无空白、无控制字符的可打印 ASCII。Secret 只通过
`api_key_value` 在 Provider 请求头中使用，repr 不显示明文。

## 测试

- 契约：SQL/澄清 XOR、空值、额外字段、不可变；
- 配置：环境加载、缺值、HTTPS/回环 URL、固定温度、Secret repr；
- Prompt：确定性、Top-K、快照元数据、PK/FK/路径、函数白名单、结果行上限、
  无 Gold/凭据；
- Provider：请求格式、结构输出、`finish_reason`、Token、响应上限、禁用重定向
  和错误脱敏；
- Service：上下文版本/对象/FK 一致性、空候选不调用模型；
- 安全：恶意问题/注释不能改变 System message，危险 SQL 仍被 Stage 3 拒绝，
  Provider 不触碰 Connector；
- 集成：本地 HTTP server 验证真实协议栈，Stub 串联 Linking → Generate →
  Validate。

## 完成标准

- 单模型 OpenAI-compatible Provider 可用且无新生产依赖；
- 结构输出严格 XOR，错误 fail-closed；
- Prompt 只含授权候选，不含 Gold 或 Secret；
- 危险模型 SQL 不执行并被 Stage 3 拒绝；
- 单元、安全、集成和 Stage 1–4 回归通过；
- 独立审查 `blocking=0`、`high=0`；
- 三份受保护文件未修改；
- 未实现 Stage 6+ 功能。
