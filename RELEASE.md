# Text-to-SQL Agent 发布状态与路线图

## 当前快照

- 记录日期：2026-08-01
- 包版本：`0.1.0`
- 当前分支：`main`
- 定位：工程预览，不是生产发布
- MVP 工程实现：已形成 PostgreSQL + Pagila 的端到端闭环
- MVP Stage 10 发布资格：`not_passed`
- 增强 Stage 1 总体资格：`not_passed`
- Stage 2～5：尚未开始实现
- 交付前改进：安全回归已修复，全量 1264 测试通过，Override 接线完成
- Stage 1 正式配置：用户已确认三模型组合，选定配置与校准冻结已重建并验证
- Stage 1 正式候选：自动证据 `11/18`（等待独立逐条审核）

本文件记录当前版本的完成情况和后续建设计划。安装、配置和 API 用法请阅读
[README.md](README.md)；精确行为与验收门禁以仓库主规格和测试规格为准。

## 已完成

### PostgreSQL / Pagila MVP 闭环

- 锁定 PostgreSQL 16.14 和 Pagila 3.1.0 数据快照。
- PostgreSQL 连接池、授权元数据读取、确定性 `schema_version` 和只读执行。
- SQLGlot PostgreSQL 安全策略：单 statement、只读 `SELECT` / 受控 CTE、
  授权对象与字段、函数 allowlist、危险 AST 默认拒绝。
- 确定性 BM25 Schema Linking、字段召回、授权 FK 路径和语义别名 manifest。
- OpenAI-compatible Chat Completions Provider 和严格结构化 SQL / 澄清输出。
- 初始 SQL 后最多三次不同修复、SQL 指纹去重和 Workflow 32 步 / 120 秒边界。
- FastAPI `POST /api/v1/text-to-sql`、严格联合响应、公开错误脱敏。
- 安全 Trace、结果 Comparator、18 条 Pagila Case、冻结基线、证据报告和
  逐 Case 审核门。

### 增强 Stage 1 已落地的工程能力

- 显式 `ComplexityRouteNode`，Workflow 从历史九种节点迁移到十种节点。
- 同一授权快照上的 `SchemaLinking(probe K=20) → ComplexityRoute →
  SchemaLinking(materialize K=5/10/20)`。
- 可解释 `simple / medium / complex` 复杂度判定和封闭理由码。
- 授权过滤后的 BM25 与 Embedding 双路召回、RRF `k=60`、可解释 Rerank。
- Embedding 索引的 Schema、语义、Provider 和策略版本隔离。
- 服务端拥有的 simple / standard / complex 模型路由、上下文裁剪和受限
  fallback 配置。
- Metadata 和 SQL execute 使用 Workflow 剩余 deadline；Embedding 无安全
  BM25 降级路径时产生脱敏失败 Trace。
- 非 Gold development / calibration 数据集、选定配置和校准冻结。

这些能力已经进入真实可达代码和确定性测试，但“代码存在”不等于 Stage 1
总体发布资格通过。

## 当前验证证据

### 确定性与本地集成

- 单元与安全回归：`1173 passed`（含 12 项 Override 接线测试）
- 完整 Pagila integration：`91 passed`（真实 Pagila + 临时只读角色）
- 全量合计：`1264 passed, 0 failed`
- Stage 1 synthetic development：`6/6` 通过
- Stage 1 synthetic calibration：`6/6` 通过
- 前端：typecheck 0 错误、vitest 49 测试通过、next build 成功
- 覆盖率基线：unit+security 分支覆盖 **81%**（31 文件 100%）
- 依赖漏洞扫描：`pip-audit` **0 漏洞**
- `compileall`、`pip check` 通过

完整 Pagila integration 使用临时随机只读角色，测试后撤销授权并删除角色；
清理后 `codex_stage1_%` 残留角色数为 `0`。

### Stage 1 冻结摘要

| 冻结项 | SHA-256 / ID |
|---|---|
| Stage 1 选定配置 | `bd66c666151db8c3236b2454696d23b20cd60fbff8ecf37c46d45c54abb422db` |
| development 原始文件 | `0ce763b3122b09a6b6718975789122918e4594b455b35d51197a37b359b595f0` |
| development 规范化 | `c1746bea22d588578929b25afb1a3a29d13c7e978f5687e2b6352b7029668dd7` |
| calibration 原始文件 | `07070687fb39592e26b02fb21891b5108b38bc0f5337240de25a4df3ac638845` |
| calibration 规范化 | `d7e7d7d60a157ec78e00ba16fbf722dddd5552eb833863310a8d9ed95797b8bd` |
| 受控代码 | `1f9e93e6749c2c8e081e54ab5c16679c4c7c3860fbea063159c9257c52b3a921` |
| calibration baseline | `70f424307045b748b82e71c5b22707da14ad7d7da53c4143bf427dae62c8a4d6` |
| 当前 Pagila baseline | `5e4f9ee633cd7d7f753cc3f3667fcaa7030e25619eb059b48f125fb77e6b2d16` |

这些摘要属于本次工程快照。契约标识已完成 Stage 1 迁移
（`baseline_version=stage1-freeze-v1`、`PROMPT_VERSION=stage1-retrieval-routing-v1`、
report 契约 `stage1-report-v1`）。`evaluation/pagila_baseline.json` 目前仍绑定
上一份 selected configuration 与受控代码摘要，正式候选前必须用真实 Pagila
容器重建 baseline。任何受控代码、配置、依赖、数据或语义 manifest 变化后，
都必须重新建立相应冻结，不能跨版本复用。

### 真实 Embedding

确定性 Provider 测试完成后，已对获批的阿里云百炼中国北京区
OpenAI-compatible 服务执行且仅执行一次真实调用：

- 模型：`text-embedding-v4`
- 配置维数：`1024`
- 返回向量数量：`1`
- 校验：模型、数量、index、维数、有限值和非零范数全部通过
- 单项状态：`embedding_provider.real_environment_validated=true`

资格记录不保存 API Key、原始 Base URL、请求正文、响应正文或向量值。该证据
只证明 Embedding Provider 的协议兼容性，不能证明授权 Schema 索引、混合检索
质量、多模型路由或整个 Workflow 已完成真实环境验证。

### Stage 1 正式候选（2026-08-01）

在冻结的配置、代码与真实 Pagila 环境上运行唯一正式候选：

- 自动证据：`11/18` 通过；失败 `7` 条：
  - PG-MVP-010/011/012：standard route 真实调用返回 `LLM_HTTP_ERROR`
    （外部模型服务瞬时失败，工作流按设计 `FAILED_INTERNAL` 收尾）；
  - PG-MVP-003/008：生成 SQL 超出授权范围，被安全门正确拒绝；
  - PG-MVP-005：已执行但结果列与 Gold 不一致。
- 未发现可由非 Gold 测试证明的通用 blocking/high 实现缺陷，按两次运行终局
  规则不启动第二次运行；未按失败 Case 修改任何策略。
- baseline ID：
  `a7b3bd95e68810874b4f7ebcbc54bd1dcec41d35a6a5489c9090fbefafa29628`
- 完整逐 Case 结果见
  [pagila_mvp_stage1.md](evaluation/reports/pagila_mvp_stage1.md)。
- 真实 Pagila 集成回归：`78 passed / 9 skipped / 0 failed`；测试后
  `codex_stage1_%` 残留角色数为 `0`。

## 未完成与已知限制

### 交付前改进（2026-08-01）

本次改进已修复的安全回归与工程缺口：

- `QueryRequest`/`QueryResponse` 恢复 `extra="forbid"`，未知字段重新被 422 拒绝。
- `ModelOverride`/`DatasourceOverride` 后端接线完成（含 SSRF/凭据安全约束）。
- `SchemaCandidate.schema` 遮蔽告警消除。
- Stage 1 选定配置与校准冻结已按用户确认的三模型组合重建（匹配当前受控代码
  哈希），env 派生配置与冻结配置完全一致。
- Task 1 的三项 complexity mutation checks 已执行（3/3 被测试拦截）并恢复，
  `functional_complete=true`。
- 后端 Dockerfile、部署与回滚文档、GitHub Actions CI、覆盖率配置就绪。
- MySQL/StarRocks 契约测试套件（无实例时 skip）与 compose 模板就绪。
- pip-audit 0 漏洞；workflow 节点 docstring 覆盖从 0% 提升至全量。

仍需解决的阻塞项：

- **P0-3 正式候选已完成**：自动证据 `11/18`。当前阻塞为 18 条 Case 的独立
  逐条审核（approve/reject）与 `verify-case` 更新 Gold 状态；只有
  `18/18` 自动证据且 `18/18` 独立审核通过才可宣称 Stage 1 完成。
- Stage 1 focused diff 的独立 blocking/high 清零审查尚未形成完成记录。

### MVP 历史资格

MVP Stage 10 的正式候选结果为：

- 自动证据：`12/18`
- 独立审核：`12 approved / 6 rejected`
- Gold 状态：`draft=18 / verified=0`
- 发布资格：`not_passed`

历史报告位于
[`evaluation/reports/pagila_mvp_stage10.md`](evaluation/reports/pagila_mvp_stage10.md)。
它绑定的是增强 Stage 1 之前的九节点代码冻结，只能作为历史回归参照。

### Stage 1 剩余门禁

当前必须保持：

```text
stage1.functional_complete=true
stage1.integration_complete=false
stage1.real_environment_validated=false
```

三层状态有各自尚未闭环的依据：

- `functional_complete=true`：Prompt/baseline/report/evidence 契约已迁移到
  Stage 1 标识；三项 mutation checks 已执行并被测试拦截；单元与安全
  `1173 passed`、synthetic development/calibration 质量门通过。
- `integration_complete=false`：尚无新的 Stage 1 正式报告契约与证据（report
  已生成 `stage1-report-v1` 正式候选报告，但 18 条 Case 独立逐条审核未完成）；
  完整 Stage 1 focused diff 的独立
  blocking/high 清零审查也没有形成完成记录。
- `real_environment_validated=false`：正式候选已在真实 Pagila + 真实
  Embedding + 三模型路由上运行（自动 `11/18`），但未达到 `18/18` 自动证据，
  且独立审核未完成。

当前冻结的选定配置中三条 route 已绑定三个不同真实生成模型
（deepseek-v4-flash / deepseek-chat-v4 / deepseek-reasoner），确定性测试证明
路由行为可达；真实环境端到端验证尚未完成，不能因此宣称真实环境门禁通过。

### 当前产品边界

- 生产 Bootstrap 只支持 `pagila` 数据源、PostgreSQL 方言、`public` Schema
  和固定 13 张表。
- API 是同步单轮接口；没有 `session_id`、Checkpoint 或长期 Memory。
- 固定请求身份只适合本地演示；尚无完整认证、用户级隔离或多租户数据模型。
- 没有 MySQL、StarRocks、跨数据源 QueryPlan 或受限结果合并。
- 没有动态 Few-shot、业务指标知识库、业务 RAG 或参考 SQL 审批生命周期。
- 没有结果缓存、异步导出、Dashboard、告警、限流、熔断、资源组、Secret
  轮换、部署升级回滚和数据保留演练。
- Python 包不固定 ASGI server；部署方需要自行选择运行服务器。
- 当前 wheel 不携带 `evaluation/`、`infrastructure/` 和语义 manifest，生产
  Bootstrap 依赖完整仓库检出。
- 仓库尚未包含 `LICENSE`，公开可见不等于已授予开源使用许可。

## 后续建设顺序

后续能力仍属于最终交付范围，不因本次暂停而取消。恢复开发时按依赖顺序推进：

### 1. 收口增强 Stage 1

先完成 Prompt、baseline、report、evidence 等 Stage 1 契约版本迁移及缺失的
mutation / 独立审查门，再补齐第二个真实生成模型和路由配置；随后进行一次真实
授权 Schema Embedding 索引验证，最后重新冻结并运行唯一正式 Pagila 候选与
独立审核。三层状态分别按自身证据更新，整阶段只有全部通过后才可宣称完成。

### 2. Stage 2：业务知识与动态 Few-shot

- 结构化术语、指标公式、粒度、过滤条件、时间口径和适用数据源。
- 动态 Few-shot 检索和业务 RAG。
- 参考 SQL 的验证、人工审核、版本、失效与撤销。
- 未执行、未对账或未批准 SQL 不进入长期知识。

### 3. Stage 3：Session、Checkpoint 与 Memory

- `session_id`、结构化会话状态、澄清后安全恢复和 Checkpoint。
- Session Compaction，以及任务级、会话级、项目级 Memory 隔离。
- 恢复时重新校验身份、权限、数据源、Schema 和知识版本。
- 不保存无上限原始聊天记录。

### 4. Stage 4：多数据库、多方言与跨数据源

- 稳定 Connector Contract 和 Dialect Profile。
- MySQL、StarRocks 真实数据库契约测试和方言专项验证。
- 跨数据源 QueryPlan、子查询下推、受限执行与结果合并。
- 不能把 SQLGlot 可解析当作真实数据库兼容证据。

### 5. Stage 5：缓存、导出与生产治理

- 权限和版本安全的 Schema、Few-shot、结果缓存及失效/撤销。
- 分页、异步导出和结果存储。
- 完整指标、Trace、日志、审计、Dashboard 和告警。
- 用户、可信 tenant、数据源三级限流，以及熔断、并发、容量和资源组。
- Secret 管理、部署、升级、回滚、备份恢复和数据保留/删除演练。

安全、授权、版本隔离、可观测性和测试是所有阶段的横切门禁，不能集中推迟到
Stage 5。

## 恢复开发前的首要决策

唯一首要外部决策是：选择并批准第二个真实生成模型及其数据处理边界。推荐让
`simple` 与 `standard` 暂时共享当前模型，把 `complex` 配置为第二个能力更强
且位于同一批准数据边界的模型；fallback 继续默认关闭。这样能用最小配置变化
满足多模型真实路由验证，同时避免提前扩大数据出境和降级范围。

## 详细资格记录

- [增强 Stage 1 资格报告](evaluation/reports/enhancement_stage1_qualification.md)
- [MVP Stage 10 历史资格报告](evaluation/reports/pagila_mvp_stage10.md)
- [Stage 1 设计](docs/superpowers/specs/2026-07-29-enhancement-stage-1-retrieval-routing-design.md)
- [Stage 1 实施计划](docs/superpowers/plans/2026-07-29-enhancement-stage-1-retrieval-routing.md)
- [ADR 0011：显式 ComplexityRouteNode](docs/decisions/0011-explicit-complexity-route-node.md)
