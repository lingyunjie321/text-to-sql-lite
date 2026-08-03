# 本地模型与离线模式阶段 4 设计

## 1. 目标与边界

本阶段把阶段 2 保存的 `ModelProfile` 接入真实 OpenAI-compatible Provider，
补齐保存前连接测试、动态模型运行时、单模型默认路由和可选 Embedding，使应用在
没有静态模型或 Embedding `.env` 的情况下仍可启动并通过 Profile 完成查询。

调用关系：

```text
API
→ ModelProfileService / ModelRuntimeService
→ LocalProfileStore + InMemoryCredentialStore
→ ModelProviderFactory / OpenAICompatibleEmbeddingProvider
→ ModelRuntimeRegistry
→ ProfileResolver + DatasourceRuntime
→ WorkflowContextFactory
→ Text-to-SQL Workflow
```

本阶段只实现后端纵向闭环，不修改前端模型设置页、工作台选择或 localStorage。
这些内容继续属于阶段 5。本阶段也不新增 Provider 协议、模型厂商适配层、复杂路由
UI、fallback、凭据持久化、数据库类型、Workflow 节点、State、Comparator 或 Gold。

## 2. 方案选择

采用独立的 `ModelRuntimeService + ModelRuntimeRegistry`：Profile CRUD 继续只负责
配置和进程内凭据；Runtime Service 负责构造与测试 Provider；Registry 负责按
Profile ID 懒创建、复用和失效。该结构与阶段 3 的动态数据源模式一致，同时避免把
资源创建和缓存重新塞入 Profile Resolver。

不采用以下方案：

- 不把动态 Provider 直接创建在 `StaticProfileResolver` 中，避免解析、资源创建、
  缓存和错误映射重新耦合。
- 不在每次查询时临时创建 Provider，避免重复构造以及 Embedding 索引无法复用。

## 3. ModelProfile 与固定运行参数

`ModelProfile` 保持单个生成模型，并增加可选的 `embedding_dimension`：

```text
id
name
provider_type = openai_compatible
base_url
model_name
embedding_base_url（可选）
embedding_model（可选）
embedding_dimension（可选）
```

Embedding 的地址、模型和维数必须同时提供或同时省略。维数为显式正整数，不在查询
过程中猜测，保证索引版本稳定且响应维数可以 fail closed。SQLite 使用前向迁移增加
该非敏感字段；API Key 仍不进入数据库。

动态 Profile 使用服务端固定运行参数：生成超时 30 秒、输入上限 32,768 Token、
输出上限 2,048 Token、temperature 0；Embedding 超时 10 秒、每批最多 10 个文档、
响应最多 4 MiB。阶段 4 不把这些高级参数暴露给普通用户。

生成和 Embedding API Key 都允许为空，以支持不鉴权的本地 Ollama、vLLM 和
LM Studio。配置了 Key 时发送 Bearer Header；未配置时不发送 Authorization。
Secret 仍只在当前进程内存中存在。远程或本地 endpoint 都遵守既有 URL 规则：
非 loopback 必须使用 HTTPS，只有 `localhost` 和 IP loopback 允许 HTTP；禁止 URL
凭据、query 和 fragment，并继续拒绝重定向。

## 4. 保存前模型测试

新增：

```text
POST /api/v1/local/models/test
```

请求接收临时生成模型配置、可选 Embedding 配置和 write-only Key，不要求 Profile
已经保存。服务构造临时 Provider，执行一次满足项目结构化输出契约的最小生成调用；
如果配置了 Embedding，再执行一次单文本向量调用并校验维数。测试完成后立即丢弃
临时对象，不写 SQLite、Credential Store、Runtime Registry、Trace 或查询历史。

返回分别报告生成和 Embedding 状态：

- 生成成功且未配置 Embedding：`generation=connected`、
  `embedding=not_configured`。
- 两者成功：均为 `connected`。
- 生成失败：返回相应 4xx/5xx 和稳定脱敏错误码，整体测试失败。
- 生成成功但 Embedding 失败：返回 200，`generation=connected`、
  `embedding=unavailable`，附稳定脱敏的 Embedding 原因；这明确表示基础
  BM25-only 查询仍可用。

测试不得返回原始响应正文、Prompt、模型输出、API Key、endpoint、请求 Header、
异常文本或内部地址。

## 5. 单模型默认路由

每个 ModelProfile 只创建一个生成 Provider，并通过现有
`build_single_provider_routing_runtime` 映射到三条主路由：

```text
simple   → selected_model
standard → selected_model
complex  → selected_model
```

阶段 4 的动态 Profile 不配置 fallback。底层静态多模型路由与旧 Override 路径继续
保留兼容，但普通 Profile 查询不能从请求选择具体 Route 或 Provider。

模型配置 Hash 继续排除 API Key，绑定 endpoint、model、Prompt/Provider 契约、
Token 上限和超时。Registry 的运行时身份另外绑定凭据版本；Key 被设置、清除或替换
时必须使旧运行时失效，不能继续使用先前 Header。

## 6. 可选 Embedding 与 BM25-only

`WorkflowContextFactory` 接受 `embedding_provider=None`：

- 未配置 Embedding 时不创建 `RetrievalRuntime`，Schema Linking 直接走现有
  BM25 路径。
- 配置 Embedding 时创建 `RetrievalRuntime`，使用当前授权先过滤、Embedding、
  RRF 和 Rerank 流程。
- Embedding 超时、连接失败、限流、响应无效或维数不匹配时，沿用既有降级矩阵，
  仅在当前授权范围、当前 Schema 版本且 BM25 有安全候选时降级为 BM25-only。
- HTTP 失败、输入无效等不在批准矩阵内的错误继续 fail closed；不得用陈旧索引、
  扩大权限或隐藏降级。

动态模型运行时持有 `EmbeddingIndexRegistry`，不同数据源和授权范围仍由既有索引键
隔离。查询创建轻量 `WorkflowContext` 时复用该 Registry，避免每次查询丢失索引。

## 7. 动态运行时与 Context 组合

`ModelRuntimeRegistry` 以 Model Profile ID 为键，懒创建并复用：

```text
ModelRoutingRuntime
Optional[EmbeddingProvider]
EmbeddingIndexRegistry
runtime identity
```

首次并发访问同一 Profile 只创建一次；失败不缓存并允许下次重试。Profile endpoint、
model、Embedding 配置或任一 Key 变化时使旧运行时失效。删除 Profile 和应用退出时
清除 Registry 与索引引用；Provider 当前没有长连接 close 契约，因此不发明无效的
资源关闭接口。

Profile Resolver 分别解析模型运行时和数据源运行时，再通过
`WorkflowContextFactory` 组合：

```text
DatasourceRuntime: Connector + allowlist + datasource semantic version
ModelRuntime: ModelRoutingRuntime + optional Embedding + index registry
→ WorkflowContext
```

阶段 3 的 Connector 生命周期仍由 `RuntimeRegistry` 持有。为保持旧代码兼容，
静态 Context 可以继续使用；Profile 模式只要 ModelProfile 与 DatasourceProfile
有效且凭据条件满足，就不再要求它们与启动时静态身份相同。任一动态解析失败都在
进入 Workflow 前返回，不回退到默认 `.env` 资源。

## 8. 可选静态配置与兼容

生成模型和 Embedding 的静态环境配置改为“全有或全无”：

- 静态生成模型完整：继续构造原有静态三路/多路 Runtime。
- 静态生成模型完全缺省：应用仍可启动，等待 ModelProfile。
- 任一静态生成配置只提供部分字段：启动失败。
- 静态 Embedding 完整：保持原有增强检索。
- 静态 Embedding 完全缺省：所有静态 Context 使用 BM25-only。
- 任一静态 Embedding 只提供部分字段：启动失败。

数据库静态配置继续遵循阶段 3 的可选行为。旧普通查询没有可用静态 Context 时仍
安全拒绝；Profile 查询不依赖默认 `.env`。旧 Override、静态多模型路由、Pagila、
PostgreSQL/MySQL 方言、安全校验、修复次数和 32 步上限保持不变。

## 9. 错误与脱敏

| HTTP | 错误码 | 场景 |
|---:|---|---|
| 404 | `MODEL_PROFILE_NOT_FOUND` | Profile 不存在 |
| 409 | `MODEL_RUNTIME_STALE` | 更新后旧 Profile 尝试重建 |
| 422 | `MODEL_TEST_INVALID_OUTPUT` | 服务可达但不满足结构化输出契约 |
| 503 | `MODEL_CONNECTION_FAILED` | 认证、拒绝连接或连接中断 |
| 504 | `MODEL_TEST_TIMEOUT` | 测试调用超时 |
| 503 | `MODEL_RUNTIME_UNAVAILABLE` | 动态运行时无法建立 |

缺失 API Key 本身不再是错误；真正需要鉴权的服务会返回脱敏连接/HTTP 错误。公开
响应、OpenAPI、日志、Trace 和异常不得包含 Key、Authorization Header、endpoint、
模型原始响应、Prompt、问题原文、SQL 原文或底层 HTTP 异常。

## 10. 测试与验收

- ModelProfile SQLite 迁移、Embedding 三字段一致性和 Secret 不落盘通过。
- 保存前测试覆盖无鉴权 loopback、带 Key HTTPS、结构化输出错误、超时、限流、
  连接失败、Embedding 未配置/成功/失败及脱敏。
- 单模型三路映射使用同一 Provider 配置，不启用 fallback；复杂度路由行为不变。
- ModelRuntimeRegistry 覆盖并发单建、复用、失败重试、Key/配置更新失效、删除和
  应用退出清理。
- 无静态 LLM/Embedding 的应用可启动；半配置继续 fail closed。
- Profile-ID 查询同时覆盖 PostgreSQL/Pagila 和 MySQL/Sakila；请求只含两个
  Profile ID，不使用默认模型或数据源回退。
- BM25-only 覆盖启动、Schema Linking 和完整 Workflow；配置 Embedding 后的批准
  失败降级有 Trace 证据且不扩大授权。
- 原有 unit、security、Pagila integration、MySQL integration、Python 全量和前端
  基线不回归；unit+security 分支覆盖率不低于 83%。
- Workflow 图、节点、State、Comparator、Gold 内容以及 `16 verified / 2 draft`
  状态不变。
- `compileall`、`pip check`、真实 loopback OpenAI-compatible 契约、
  `git diff --check` 通过。
