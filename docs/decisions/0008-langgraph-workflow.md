# ADR 0008：九节点 LangGraph Workflow

## 状态

Accepted for MVP Stage 8。节点数量和固定边集合于 2026-07-29 被
ADR 0011 部分 supersede；其余 State、Runtime Context、安全、预算和错误路由
决策继续有效。

## 决策

Stage 8 固定使用 `langgraph==1.2.9` 的 `StateGraph`、Pydantic State、
`context_schema` 和 `Runtime`，显式注册主规格要求的九个业务节点。不使用
prebuilt agent、checkpoint、memory、tool calling 或 LangChain 模型封装。

`SQLTaskState` 只保存请求、可信授权结果、Schema 候选、SQL attempt、脱敏错误、
终态和观测数据。Provider、Connector、服务端 allowlist 与注入时钟放在 frozen
`WorkflowContext`，不进入可序列化 State。

Stage 1–7 仍是元数据、Linking、Prompt、SQL 校验、执行和反思的唯一实现：
Workflow 只负责编排，不复制或放宽安全策略。修复 Prompt 在 Stage 5 的规范用户
JSON 上增加当前 attempt SQL、结构化 `ErrorType` 和 `RepairStrategy`，不加入
数据库原文错误。Provider 返回的模型配置 ID 和基础 Prompt 版本逐调用保留；
修复调用的 Workflow 生效版本固定记为 `<provider_version>+repair-v1`。

Stage 1 Connector 的同调用连接重试保留在原有公开方法内部。具体
`PostgreSQLConnector` 新增私有、`ContextVar` 隔离的重试观测钩子，Workflow
在每次元数据或执行调用后消费并累加到 State；没有改变 Connector 的公开签名、
返回类型或 Stage 6 单次公开调用边界。

业务层在最多 32 个节点步骤内进入 Finalize，并在每次外部调用前检查 120 秒总
预算；LangGraph `recursion_limit=34` 是独立的框架保护。若最后一次执行跨过总
预算，结果会被丢弃并返回 `FAILED_TIMEOUT`。最终 State 根据真实执行过的节点
序列补齐每个节点的下一路由，供 Stage 10 Trace 使用。

## 理由

- 九节点与条件路由能直接对应主规格和测试断言；
- Pydantic State 提供输入、最终输出和跨节点不变量检查；
- Runtime Context 防止请求正文扩大数据源、Schema 或表权限；
- 复用既有安全边界，避免 Workflow 与 Stage 3/6 产生策略分叉；
- 业务步骤和框架递归双重限制使修复循环确定终止。

## 兼容性说明

Stage 1 的 `ExecutionResult` 含递归 `JsonValue` 类型，Pydantic 为其生成 JSON
Schema 时会递归溢出。Workflow 将 `SQLAttempt` 和 `ExecutionResult` 在 State
Schema 中视作 opaque object，再在 State model validator 中强制检查其真实运行
时类型并重建 `AttemptHistory`。这不修改 Stage 1–7 的公共模型或接口。

## 暂不实现

- FastAPI 请求/响应和认证依赖；
- Trace sink、持久化、Checkpoint、Session 和 Memory；
- Comparator、Pagila 离线评测和真实模型发布阈值；
- Workflow 层第二套数据库重试。
