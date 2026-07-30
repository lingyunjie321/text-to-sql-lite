# ADR 0011：显式 ComplexityRouteNode 与两遍 Schema Linking

## 状态

Accepted，2026-07-29。用户确认采用显式 `ComplexityRouteNode`。

本 ADR 只 supersede ADR 0008 中“业务节点恰好九个”和对应固定边集合；
ADR 0008 的 State/Runtime Context、安全边界、32 步、120 秒、attempt 和
错误路由决策继续有效。Stage 8 的九节点设计与验证记录保留为历史证据。

## 当前实施与资格状态

截至 2026-07-29，显式 `ComplexityRouteNode`、探测—路由—物化两遍
Schema Linking、动态 5/10/20、双路召回、RRF、Rerank、上下文裁剪和
可配置模型路由已进入代码与确定性测试。`WorkflowContext.model_routing`
显式持有 `ModelRoutingRuntime`，生产启动按
`LLM_SIMPLE_`、`LLM_STANDARD_`、`LLM_COMPLEX_` 和可选
`LLM_FALLBACK_` 配置构建路由；缺失所声明路由的必要配置时 fail closed。

Embedding Provider 已在确定性测试之后完成恰好一次真实环境调用：
阿里云百炼北京区 OpenAI-compatible 接口，模型
`text-embedding-v4`，维度 `1024`。响应通过模型、数量、索引、维度、有限值
和非零向量校验，因此
`embedding_provider.real_environment_validated=true`。测试和报告不记录
API Key、原始端点、输入正文、响应正文或向量。

这不等于 Stage 1 总体验收通过。目前仍缺至少两个真实生成模型在不同复杂度
路由上的验证，以及新版 Pagila/Gold 正式评测，所以
`stage1.real_environment_validated=false`。Stage 10 的历史报告只证明当时
九节点基线，不作为本 ADR 或 Stage 1 的新验收证据，也不得被回写。

## 背景

增强阶段 1 必须同时实现：

- 可解释复杂度路由；
- 5/10/20 动态 Schema Top-K；
- Embedding 与 BM25 双路召回、RRF 和可解释 Rerank；
- 模型路由与上下文裁剪；
- 授权过滤、Schema/索引版本隔离和 Gold 防污染。

复杂度判断需要候选表、相关 JOIN Path、问题结构和修复历史；动态 Top-K 又必须
在最终候选物化前确定。若只在 Schema Linking 前按问题关键词分类，会丢失候选
和 JOIN 证据；若只在 Linking 后分类而不重新物化，Top-K 不会真实影响输出。

## 决策

### 十种显式业务节点

当前 Workflow 注册十种业务节点：

1. `request_preprocess`
2. `permission_resolve`
3. `schema_linking`
4. `complexity_route`
5. `generate_sql`
6. `validate_sql`
7. `execute_sql`
8. `reflect_sql`
9. `clarification`
10. `finalize`

`ComplexityRouteNode` 使用节点名 `complexity_route`，由现有通用 wrapper 负责
deadline、32 步预算、异常脱敏、`NodeTiming` 和下一路由证据。它不伪装成
`NodeTiming` 子事件，也不散落在 Linking 或 Generate 内部。

### 正常检索周期

```text
PermissionResolve
→ SchemaLinking(probe, K=20)
→ ComplexityRoute
→ SchemaLinking(materialize, K=5/10/20)
→ GenerateSQL
```

探测 Linking：

- 从 Connector 读取当前授权快照；
- 在授权过滤后以最大候选预算 20 生成探测结果；
- 保存候选、JOIN Path、快照和 `schema_version`；
- 不调用生成模型。

`ComplexityRouteNode`：

- 只读取规范化问题、探测结果、相关 JOIN Path、派生的
  `has_repair_history` 和版本化本地策略；
- 生成 frozen、strict 的 `ComplexityDecision`；
- 不调用 Connector、Embedding、Reranker、LLM 或数据库；
- 不读取 `EvaluationCase.difficulty`、Gold SQL/fields/result/fixture。

物化 Linking：

- 复用探测阶段同一个授权 `SchemaSnapshot`，不第二次读取数据库元数据；
- 按决策中的 5/10/20 重新构建最终候选；
- 结果和 Prompt 继续绑定同一个 `schema_version`。

### Schema 修复

`SCHEMA_ERROR → ReflectSQL(RELINK_SCHEMA)` 清除当前复杂度决策，重新执行完整
探测、路由和物化周期。语法或方言修复沿用当前候选和决策，直接回到
`GenerateSQLNode`。

最坏情况下，初始请求加三个 Schema 修复仍必须在 32 个业务步骤内终止；
不得通过增加 recursion limit 掩盖业务步骤超限。

### `complexity-v1` 决策

等级为 `simple`、`medium`、`complex`，对应 Schema Top-K 为 5、10、20。
理由码使用封闭枚举，至少覆盖：

- `aggregation_requested`
- `window_or_ranking_requested`
- `subquery_or_anti_join_requested`
- `time_analysis_requested`
- `multiple_positive_tables`
- `relevant_join_path`
- `long_join_path`
- `repair_history`
- `default_simple`

相关候选只指 BM25/融合分数大于零的授权候选。JOIN Path 只有连接至少两个正分
候选时才构成复杂度证据，避免宽授权 fallback 使所有问题被误判为复杂。
`has_repair_history=True` 产生 `repair_history`。Workflow 在已有 SQL attempt
且进入修复流程，或 `repair_count > 0` 时派生该值；这是因为现有
`repair_count` 只在新修复 SQL 被接受后递增，不能单独表示待执行的首次
Schema 修复。

判定顺序固定：

1. 存在窗口/排名、子查询/反连接、长 JOIN Path 或修复历史 → `complex/20`；
2. 否则，中等信号中至少两类命中 → `complex/20`；
3. 否则，任一聚合、时间、正分多表或相关 JOIN Path 命中 → `medium/10`；
4. 否则 → `simple/5`，理由为 `default_simple`。

同一规范化问题、探测结果、修复历史和策略版本必须得到相同决策、理由顺序和
Top-K。词表、规则顺序和版本属于代码及评测冻结项。

### 检索与生成边界

- `link_schema()` 接收服务端内部的封闭预算 5/10/20；API 请求不增加 Top-K、
  complexity、model 或 context budget 参数。
- 探测使用 20，最终候选不得超过决策预算，FK 中间表计入预算。
- Stage 1 后续双路检索、RRF 和 Rerank 只能在授权视图内工作，并复用本 ADR
  的探测—决策—物化边界。
- 复杂度只选择服务端批准的检索、模型和上下文策略，不能改变 Validator、
  Connector、函数策略、只读限制或修复预算。

### State 与 Trace

State 保存当前 `ComplexityDecision`；决策至少包含：

- `level`
- `schema_top_k`
- `reason_codes`
- `policy_version`

Trace 保存同一组脱敏字段和 `complexity_route` 节点耗时。不得记录问题、
Prompt、SQL、Schema 名称、结果行、模型密钥或原始异常。

权限、预处理或基础设施错误在路由前终止时，复杂度证据可以为空；到达最终
Linking 的请求必须有合法决策，且候选数不得超过其预算。

## 选择理由

- 满足用户确认的显式节点要求，并让复杂度行为可单独测试和观测；
- 真实使用候选与 JOIN 证据，不把复杂度降格为关键词标签；
- 两次 Linking 复用同一授权快照，不增加第二次元数据读取或版本竞态；
- 动态 Top-K 对最终候选有真实行为，不只是 Trace 标签；
- 保留现有 Connector、Validator、Execution、attempt、Finalize 和安全路由。

## 被拒方案

### 九节点内嵌 RoutingPolicy

改动更小，但用户已明确选择显式 `ComplexityRouteNode`，且节点级失败、耗时和
路由证据不够直接。不采用。

### Permission 后、Linking 前只按问题分类

可以直接决定 K，但不满足候选表、JOIN Path 和修复历史共同参与的完整契约。
不作为最终阶段 1 方案。

### Linking 后分类但不重新物化

复杂度会成为只写 Trace 的标签，无法证明 5/10/20 实际控制最终上下文。
不采用。

### LLM 复杂度分类

增加延迟、成本、不确定性和 Prompt 注入面，也需要在获取授权候选前发送更多
数据。阶段 1 使用确定性策略；LLM 只生成 SQL。

### 使用 Pagila `difficulty` 或 Gold 失败原因

这些是评测标签和最终验收信息，会造成生产路径与 Gold 污染。明确禁止。

## 兼容与迁移

- `WORKFLOW_NODE_NAMES` 从九种变为十种；图结构、节点序列、步数和 Trace 测试
  必须显式迁移。
- 历史 Stage 8/10 报告继续描述当时九节点基线，不重写历史结果。
- Stage 1 修改 `app/`、`evaluation/` 或配置后，Stage 10 controlled code hash
  失效；真实评测前必须建立新 baseline。
- API 请求不增加客户端路由字段，现有调用方保持兼容。
- 不新增生产依赖即可完成本 ADR 的首个 TDD 切片。

## 验证要求

- 纯函数规则覆盖每个理由码、边界、稳定顺序和错误输入；
- 图只注册上述十种节点，并覆盖探测—路由—物化和 Schema 修复边；
- 同一检索周期只读取一次元数据；
- 5/10/20 均有候选上限、FK 中间表和权限隔离测试；
- Trace 能复盘决策且不包含问题、SQL、表名或结果；
- 安全 Case 保持零执行、零修复、零模型回退；
- 单元、安全、必要集成和真实 Pagila 回归按测试规格实际运行。
