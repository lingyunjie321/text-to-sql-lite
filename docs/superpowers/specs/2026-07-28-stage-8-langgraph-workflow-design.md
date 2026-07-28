# 第八开发阶段：九节点 LangGraph Workflow 设计

## 目标

用 LangGraph 串联 Stage 1–7，形成从请求预处理、可信权限、Schema Linking、单模型
生成、安全校验、真实执行、有限反思、澄清到唯一终态的可运行闭环。Workflow
使用确定性 Stub 可覆盖全部路由，并可用真实 Pagila Connector 完成端到端执行。

## 依赖决策

固定 `langgraph==1.2.9`。这是主规格明确要求的生产能力，使用官方
`StateGraph`、Pydantic state schema、`context_schema` 和 `Runtime`，不使用
prebuilt agent、checkpoint、memory、tool calling 或 LangChain 模型封装。

业务状态自己记录最多 32 个节点步骤并在第 32 步内进入 Finalize；调用时额外设置
LangGraph recursion limit 作为框架级第二道防线。总请求预算为 120 秒，节点在
任何外部调用前检查单调时钟 deadline；LLM 和数据库各自仍有最大 30 秒超时。

## 模块

```text
app/workflow/
├── __init__.py
├── models.py
├── preprocess.py
├── permissions.py
├── nodes.py
└── graph.py
```

注册且只注册九个业务节点：

1. `request_preprocess`
2. `permission_resolve`
3. `schema_linking`
4. `generate_sql`
5. `validate_sql`
6. `execute_sql`
7. `reflect_sql`
8. `clarification`
9. `finalize`

## State

`SQLTaskState` 是 Pydantic `BaseModel`，主要字段与主规格第 4 节一致：

- request/trace/question/datasource/dialect；
- 请求 Schema 范围和可信授权 Schema/表；
- candidates、fields、join paths、schema version；
- current SQL、attempts、seen fingerprints；
- validation/execution/database error；
- error type、repair strategy、repair/infrastructure retry count；
- clarification、final status、公开错误；
- token usage、逐调用模型/Prompt 版本观测、node timings、step count；
- 仅供当前运行使用的授权 `SchemaSnapshot`。

State 配置 `extra="forbid"`，输入和最终输出均执行 Pydantic 验证。attempt 字段
必须能重建有效 `AttemptHistory`；终态互斥：

- 成功必须有 SQL 和 execution result；
- 澄清必须有 clarification 且无 execution result；
- 拒绝/失败必须无成功 execution result，并有脱敏公开错误。

完整 Prompt、API key、DSN、驱动原文和未脱敏结果不进入 State。

每次成功返回结构化模型结果时，追加 `GenerationObservation`：调用序号、目标
attempt、Provider 返回的模型配置 ID 和 Prompt 版本、Workflow 生效 Prompt
版本、修复策略和本次 Token。初始调用的生效版本等于 Provider 版本；修复调用
固定为 `<provider_version>+repair-v1`。State 验证逐调用 Token 合计必须等于
总 Token，避免 Trace 证据丢失或错配。

## Runtime Context

`WorkflowContext` 是 frozen dataclass，保存本次运行的可信依赖：

- `LLMProvider`；
- 同时支持元数据读取和 SQL 执行的 Connector；
- 服务端 datasource、Schema、table allowlist；
- 可注入当前时间和单调时钟。

请求只能缩小服务端 Schema 范围，不能扩大 datasource/Schema/table 权限。
Connector 和 Provider 不存入 State。

PostgreSQL Connector 的公开 `execute()`/`read_metadata()` 契约不暴露其内部同
调用重试次数。为满足 Trace，具体 Connector 用私有 `ContextVar` 钩子保存当前
调用实际重试数，Workflow 在公开调用完成或失败后立即消费并累加；公开签名和
返回类型保持不变，其他测试 Connector 没有该私有能力时计为 0。

## 节点行为

### RequestPreprocess

- Unicode NFKC、折叠空白；
- 问题长度 1～2000；
- 用 `Asia/Shanghai` 的注入时钟规范 `今天/昨天/明天` 与
  `today/yesterday/tomorrow`；
- 无效请求写固定公开错误，路由 Finalize。

### PermissionResolve

- datasource 必须等于服务端固定值；
- 请求 Schema 与服务端 allowlist 求交；空请求使用服务端默认；
- table allowlist 只保留已授权 Schema；
- 空范围或越权写 `PERMISSION_DENIED`，不读元数据。

### SchemaLinking

- Connector 读取当前授权快照；
- 调用 Stage 4 `link_schema()`；
- 写 candidates、fields、paths、schema version 和授权 Snapshot；
- 无候选进入 Clarification；连接/权限/超时等 Connector 错误按统一路由终止；
- Schema 修复时重新读取并 Linking。

### GenerateSQL

- 初始和修复都使用 Stage 5 固定授权 Prompt；
- 修复时只在 User JSON 数据包中增加 attempt、当前脱敏 `ErrorType` 和
  `RepairStrategy`，不加入数据库原文错误；
- SQL 输出通过 Stage 7 注册 attempt；重复/超预算在校验、执行前终止；
- 澄清输出不创建 attempt，进入 Clarification；
- 累加 Token；模型超时、连接或格式错误不盲重试。

### ValidateSQL

- 用服务端授权和同版本 Snapshot 调用 Stage 3；
- 将结果绑定当前 attempt；
- 合法进入 Execute；语法/Schema/方言进入 Reflect；权限/安全/资源直接
  Finalize。

### ExecuteSQL

- 只调用 Stage 6 的同 Snapshot 重新校验执行入口；
- 成功进入 Finalize；
- 数据库语法/Schema/方言进入 Reflect；
- 连接、权限、超时、资源和未知错误直接 Finalize；
- Workflow 不添加第二套数据库重试。

### ReflectSQL

- 调用 Stage 7 确定性路由；
- Schema 错误 → SchemaLinking；
- 语法/方言 → GenerateSQL；
- 语义类 → Clarification；
- 预算、重复和硬错误 → Finalize。

### Clarification / Finalize

Clarification 只创建固定、最小、无未授权对象的提示，不执行 SQL。Finalize 根据
唯一完整路由表生成：

- `SUCCEEDED_FIRST_PASS`
- `SUCCEEDED_REPAIRED`
- `CLARIFICATION_REQUIRED`
- `REJECTED_SECURITY`
- `FAILED_REPAIR_EXHAUSTED`
- `FAILED_DUPLICATE_LOOP`
- `FAILED_TIMEOUT`
- `FAILED_CONNECTION`
- `FAILED_RESOURCE_RISK`
- `FAILED_INTERNAL`

## 通用节点 wrapper

所有九节点经同一个 wrapper：

- 外部调用前检查 120 秒 deadline；
- 在第 32 个业务节点内强制进入 Finalize；
- 捕获未知异常并只写 `FAILED_INTERNAL` 所需的固定公开错误；
- 追加节点名、attempt 和耗时；
- `run_workflow()` 根据真实节点序列补齐每个节点的实际下一路由；
- 不记录异常 repr、SQL、Prompt 或依赖配置。

Trace sink 本阶段不实现；State 中的安全观测字段供 Stage 10 sink 使用。

## 测试

- State/模型：默认值、严格结构、attempt 一致性、终态互斥；
- 预处理/权限：长度、NFKC、相对日期、可信交集和越权零依赖调用；
- 图结构：九节点精确集合和规定边；
- Stub Workflow：首次成功、合法空结果、澄清、Schema 修复、重复、三次耗尽；
- 安全：DML、多 statement、危险函数零执行/零修复，连接/超时不调用 LLM
  修复；
- 终止：步骤在 32 内，deadline 在外部调用前终止；
- 集成：Stub Provider + 真实 Pagila 完成生成、校验、执行、一次修复和 Finalize。

## 完成标准

- 九节点和完整路由表可运行；
- 所有修复重新 Validate 和 Execute，最多三次不同修复；
- 权限/安全零执行、重复零执行、连接/超时零 LLM 修复；
- 32 步和 120 秒预算 fail-closed；
- Token、模型/Prompt 版本、节点耗时、attempt 和终态进入 State，不含敏感
  内容；
- Stage 1–7 接口保持兼容；
- 全量单元、安全、集成和此前阶段回归通过；
- 独立审查 `blocking=0`、`high=0`；
- 三份受保护文件未修改；
- 未实现 Stage 9+。
