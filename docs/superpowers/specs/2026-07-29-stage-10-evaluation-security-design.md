# 第十开发阶段：评测、Trace 与安全回归设计

## 目标

完成主规格要求的 Trace、Comparator、JSONL Case runner 和真实 Pagila
评测，并在不泄露凭据、完整 Prompt、SQL 或结果值的前提下形成可复核证据。
18 条 Case 必须逐条执行和审核；只有证据完整且通过的 Case 才从 `draft`
更新为 `verified`。

## 已锁定验收基线

基线写入 `evaluation/pagila_baseline.json`：

- Pagila `pagila-v3.1.0`，commit
  `fef9675714cfba1756df4719b5e36075a7ddf90e`；
- PostgreSQL Docker image
  `postgres:16.14-bookworm@sha256:92620daddcd947f8d5ab5ba66e848702fe443d87fed30c4cea8e389fd78dfc55`；
- 运行版本 `16.14 (Debian 16.14-1.pgdg12+1)`；
- archive、schema 和 data 文件 SHA-256；
- 当前只读 `pg_dump --data-only --no-owner --no-privileges` 输出在将每次
  随机生成的 `restrict/unrestrict` nonce 规范化为固定 `TOKEN` 后的
  SHA-256；
- 当前只读 schema-only dump 的规范化 SHA-256；
- 初始 Gold 文件 SHA-256 及忽略 `status` 后的规范内容 SHA-256。

PostgreSQL 16.14 的 plain dump 每次会为 `restrict/unrestrict` 生成新的
nonce；直接对原始输出求 SHA-256 不稳定，因此该控制 nonce 不作为数据内容。
两次连续规范化导出的 SHA-256 均为
`e584f0beb3817d1a6f3e35518192ba66cc8b14c50df08c34527d5b15e77bd567`。
schema-only dump SHA-256 为
`74de0ad271945ff3ce8e21d9065d1c0178f01994a8f25c613afebcebed5933b2`。
每次正式评测前都重新验证这些值。运行时 dump 不一致时立即停止，不在变化后的
数据快照上继续比较。正式 CLI 必须在读取 DSN/模型凭据前完成 manifest、
fixture、image、服务端版本、行数和 dump 的全部核对，并要求 DSN 使用容器
实际发布的 loopback 端口和 `text_to_sql_reader` 身份。

## 方案选择

### 采用：证据报告与状态更新分离

第一阶段只加载 Case、执行 Gold、运行预测、比较和生成脱敏证据报告，不修改
Gold。第二阶段由调用者逐条审核报告后，对单个通过 Case 调用状态更新器。

优点：

- 不会预先或批量把 Case 标为 `verified`；
- 失败或证据不足的 Case 自然保持 `draft`；
- 更新器可证明每次只替换一个 `"status":"draft"` token；
- 评测失败可以保留完整、脱敏的诊断证据。

### 未采用：Runner 自动批量更新

实现较短，但无法形成独立审核门，也容易在部分失败时产生不可解释的批量状态
变化。

### 未采用：独立 verification manifest 代替 Gold 状态

不会修改受保护文件，但不满足测试规格“18 条 Case 从 draft 转为 verified”的
明确门禁。

## 模块边界

```text
app/connectors/
├── view_semantics.py  # 冻结语义模型、验证、快照增强和 Connector wrapper
└── ...

app/observability/
├── __init__.py
├── models.py       # 安全 Trace 模型
└── tracing.py      # State → Trace、Sink、Runner wrapper

evaluation/
├── __init__.py
├── code_freeze.py  # Stage 10 代码集合的确定性摘要
├── models.py       # Case、容差、证据和报告模型
├── loader.py       # JSONL 与 18 Case 契约校验
├── comparator.py   # 结果比较
├── runner.py       # Gold/预测执行与证据生成
├── status.py       # 单 Case 原子状态更新
├── pagila_baseline.json
└── reports/
    └── pagila_mvp_stage10.json

tools/
├── freeze_view_semantics.py
└── run_pagila_evaluation.py

infrastructure/pagila/
├── view_semantic_candidates.json  # 仅供受控审核的候选账本
├── view_semantic_review.json      # 逐条审核决定及摘要
└── view_semantics.json            # 运行时只读冻结清单
```

不增加生产依赖。使用现有 Pydantic、SQLGlot、Connector、Workflow 和
OpenAI-compatible Provider。

## 冻结视图语义元数据

### 方案

采用“两阶段候选提取 + 逐条审核冻结”。普通用户请求绝不读取
`pg_get_viewdef`。冻结工具只在重新建立基线时读取锁定 PostgreSQL 的 Schema
和视图定义：

1. 用服务器 allowlist 读取基础表、字段和类型，形成原始
   `SchemaSnapshot`；
2. 读取锁定 Schema 中的普通视图定义，并对定义集合规范化排序后计算聚合
   SHA-256；
3. SQLGlot 只接受单条 PostgreSQL `SELECT`，建立确定性的
   table-alias → 授权基础表 lineage；
4. 整个视图只要引用未授权表、未授权字段、`SELECT *`、不确定 search path、
   CTE/子查询或无法唯一解析的 lineage，就不生成任何候选；
5. 机械提取候选，但不直接供运行时或 Prompt 使用；
6. 独立审核每个候选，并用候选摘要生成 review digest；
7. 仅将审核通过的候选写入运行时清单。

不采用动态请求期视图扫描；不修改数据库字段注释；不加入“优先 boolean”或
任何 Case/字段特例。

### 通用提取规则

首版只允许两个规则：

- `direct_projection_alias_v1`：投影表达式恰好是一个已授权、表别名限定且
  lineage 唯一的基础字段，输出别名可作为该字段的候选 alias；
- `simple_boolean_case_label_v1`：投影表达式恰好是简单 `CASE`，条件只能是一个
  已授权 PostgreSQL boolean 字段本身或显式 `IS TRUE/IS FALSE`；不得包含
  `NOT`、函数、强转、比较常量、子查询或第二个字段。候选记录 label 的
  true/false polarity，但运行时只把审核通过的 label 作为字段 alias，不把它
  自动转换为 SQL 过滤值。PostgreSQL 规范化视图定义为字符串字面量附加的一层
  显式 `::text` 可作为无损 AST 包装解开；条件强转、非文本 cast、函数或拼接
  仍全部拒绝。

字符串 label 在进入候选账本前必须 NFKC 规范化，并满足固定长度、字符集、
数量、冲突和保留词上限。机械过滤不是敏感性批准：候选仍必须逐条审核。
审核者只批准明显的非敏感 Schema 状态词；任何人名、账号、邮箱、URL、标识符、
自由文本、健康/财务等敏感分类或证据不足的 label 一律拒绝。

候选和审核模型均 `extra="forbid"`。每条候选包含：

- 授权基础字段 object ID；
- rule ID 和 polarity；
- 规范化 alias；
- 输入绑定 schema/view identity、定义文本和依赖集合的
  source-definition SHA-256；账本只持久化摘要，不保存原始视图名或 SQL；
- 候选 evidence SHA-256。

候选账本和审核清单都不保存原始视图 SQL。运行时清单进一步移除被拒候选和审核
说明，并按 `(object_id, alias, rule, polarity)` 聚合重复权威来源，只保留
授权字段、alias、规则、polarity 及 source/evidence/review 集合 digest。

### 清单可信锚与运行时使用

`view_semantics.json` 绑定：

- manifest/extractor/policy 版本；
- datasource ID；
- runtime schema-only dump SHA-256；
- 原始完整 allowlist 快照的 `schema_version`；
- 增强后完整快照的 `schema_version`；
- allowlist scope SHA-256；
- 规范化视图定义集合 SHA-256；
- 候选账本和审核清单 SHA-256；
- 逐条审核通过的语义项。

预期运行时清单 SHA-256 固定到 `evaluation/pagila_baseline.json`，不能由清单
自证。生产 bootstrap 和正式评测 CLI 都先读取完整服务器 allowlist 快照，
验证基线和清单，再构造 `FrozenSemanticConnector`。该 wrapper 保持原
Connector 协议：每次 `read_metadata` 先委托数据库，再只对本次请求快照中
存在的授权字段合并冻结 alias，重算 `schema_version`；`execute`、重试计数和
`read_only_snapshot` 原样委托。

Schema Linking 已使用 `ColumnMetadata.aliases`。生成 Prompt 仅新增候选字段的
冻结 `aliases` 数组，并从可信增强快照读取；不加入视图名、原始 SQL、polarity、
审核说明或未授权对象。Trace 和响应仍只记录 Schema 版本与既有白名单字段。

## 新评测冻结契约

正式候选运行前重新生成 `evaluation/pagila_baseline.json`。新基线除既有
Pagila/PostgreSQL/data/schema/Gold 摘要外，还绑定：

- `view_semantics.json` SHA-256；
- 原始和增强后的 `schema_version`；
- 视图定义集合 SHA-256；
- semantic extractor/policy 版本；
- Prompt 版本；
- Comparator 版本；
- Stage 10 冻结代码文件集合及内容 SHA-256；
- Gold status-neutral SHA-256 和全 `draft` 文件 SHA-256；
- 模型配置摘要；
- 由上述规范化字段计算的 `evaluation_baseline_id`。

代码摘要覆盖 `app/`、`evaluation/` 和两个 Stage 10 工具的受控 Python 文件，
排除报告、缓存和 Gold 的可变 `status`。正式 CLI 在加载模型凭据前校验全部
摘要，且要求 18 条 Case 此时均为 `draft`。任何代码、Prompt、Comparator、
Case 规范内容、Schema、数据、语义清单或模型配置漂移都必须重新冻结，不能沿用
旧报告。

## Case 加载与不可变约束

`EvaluationCase` 严格实现测试规格数据结构，禁止额外字段。Loader：

- 要求 UTF-8 JSONL、18 条、ID 唯一且为 `PG-MVP-001`～`018`；
- 验证分类数量、datasource、dialect、期望行为和终态；
- `EXECUTE` 必须有 Gold tables、fields、SQL 和
  `execute_gold_sql`；
- `REJECT` 必须使用 `not_applicable`，且声明公开错误类型；
- 验证安全 Case 不进入可执行率分母；
- 返回文件 SHA-256 和忽略 `status` 后的规范 SHA-256。

正式更新后，status-neutral SHA-256 必须仍等于基线
`a00a8ec7496fc4e1533b2773e0267d555357a80be435a02dd70981d76ddb40d7`。

## Comparator

比较顺序严格遵循测试规格：

1. 列名首尾空白和大小写规范化；列数和 PostgreSQL type OID 必须一致；
2. NULL、Decimal、日期、timestamp with time zone 和嵌套 JSON 规范化；
3. `order_sensitive` 或 `exact` 使用逐行比较；
4. `multiset` 忽略顺序但保留重复次数；
5. `keyed` 由调用者提供唯一键列；Gold 或预测出现重复键即失败；
6. 只对 Case 明确声明的列应用 Decimal absolute/relative 容差；
7. float 未声明容差时失败；
8. 行数、重复分布或粒度不一致时失败，即使汇总值偶然相同。

`ComparisonResult` 只包含布尔结果、稳定 code、公开消息和行数，不保存具体值。
自测覆盖重复数、NULL/空字符串、容差边界、时区等价、缺列、多列、重复键和
grain 错误。

## Trace

`TraceRecord` 从终态 `SQLTaskState` 构造，记录：

- request/trace ID、FinalStatus、ErrorType 和稳定错误码；
- NodeTiming 的 node、attempt、route 和 duration；
- SQL attempt number、指纹、校验/执行结果和错误类型；
- Token、模型配置 ID、Prompt 版本和修复策略；
- Schema 版本、数据库耗时、返回行数、截断和重试计数。

Trace 不包含问题、SQL、Prompt、Schema 样例值、结果行、DSN、API key 或原始
异常。`TracedWorkflowRunner` 包装现有 `run_workflow`，Sink 失败只写固定
`text_to_sql_trace_sink_degraded` 日志，不改变已完成 State。生产 bootstrap
使用安全日志 Sink；现有 `ApplicationServices` 和 Workflow 公共接口不变。

## 真实评测数据流

每条 Case 的数据流：

1. 重新核对 baseline；
2. 读取该 Case 的授权表并加载同一 Schema snapshot；
3. `EXECUTE` Case 的 Gold SQL 先通过与预测相同的 Stage 3 安全校验，再由
   Stage 6 Connector 在只读事务中执行；
4. 使用当前 Case 问题运行完整九节点 Workflow；
5. 允许查询校验期望终态、Gold table/field recall、安全校验、真实执行和
   Comparator；
6. `REJECT` Case 校验期望终态/错误类型、零数据库执行和零修复；
7. 按测试规格的固定 Stub 策略，PG-MVP-015 使用 Case 声明的未授权表构造
   只读拒绝输入，PG-MVP-016/017 使用 Case 中固定危险 SQL，保证安全门
   确定性；
8. PG-MVP-018 第一次使用 fixture 中的错误 SQL，后续修复调用真实模型；
9. 其他 Case 使用根目录 `.env` 中的真实 OpenAI-compatible Provider；
10. 当前问题是请求输入；Gold SQL、Gold fields、其他 Case 问题和期望结果绝不
    进入模型消息。

Gold 和预测使用同一个 `REPEATABLE READ READ ONLY` 外层事务和同一个 Schema
对象。每次执行使用内层 savepoint，保证一次可修复数据库错误不会中止共享
快照。评测 Connector 只增加计数和复用该快照，不改变只读、timeout、重试或
结果上限行为。

为了消除真实模型对投影列名的非语义抖动，生成结果进入 Validator 前只做确定
性别名规范化：直接列使用源列名；`COUNT(普通列)`、`SUM(普通列)` 和
`DATE_TRUNC(普通列, unit)` 使用由表达式本身推导的别名；无歧义时同步
`GROUP BY`/`ORDER BY` 中的旧别名。规则不依赖 Case、Gold 或结果，跳过
`COUNT(*)`、源列同名歧义、多聚合、其他函数、多 statement 和不可解析 SQL，
且不改变表达式或值语义。

## 证据与逐条审核

每条 `CaseEvaluation` 包含：

- Case ID、初始状态、实际/期望终态和错误类型；
- Gold 校验/执行、预测校验/执行、结果比较；
- table/field recall、执行次数、attempt/repair 数；
- Trace 是否生成及其摘要哈希；
- 稳定失败 code；
- `passed`，仅在全部必需证据为真时成立。

报告不包含问题、Gold SQL、预测 SQL、Prompt、行值、凭据或原始错误。

主流程读取报告并逐条审核。对一个 `passed=true` Case，状态更新器再次验证：

- Case ID 精确匹配且仍为 `draft`；
- evidence digest 与报告一致；
- 审核状态为 `approved`，且 review digest 与 evidence digest 一致；
- baseline 和 status-neutral hash 一致；
- 原始行只发生一次精确
  `"status":"draft"` → `"status":"verified"` 替换。

每次写入使用同目录临时文件、`fsync` 和原子替换。未通过 Case 不调用更新器。

## 指标

报告区分：

- 允许执行 Case：15 条，统计首次可执行率、修复后可执行率和 Gold Result
  通过率；
- 权限/危险 SQL Case：3 条，只统计安全门禁，不进入允许查询分母；
- 总 verified 数量；
- Token、节点/数据库耗时和 repair count 汇总。

不采用原项目 98.82% 作为阈值。MVP Stage 10 完成门禁仍要求 18 条全部通过并
成为 `verified`；若真实模型导致任意 Case 失败，该 Case 保持 `draft`，Stage 10
不宣称完成。

## FastAPI 最终闭环

正式评测后通过 `TestClient` 调用 `POST /api/v1/text-to-sql`，至少验证：

- 一条首次成功 Case；
- PG-MVP-018 的生成、校验、执行、一次有限修复和 Finalize；
- Trace sink 失败不改写成功响应；
- SQL、DSN、Prompt 和异常不出现在响应或评测报告。

本运行环境的外部数据审查拒绝再次把 Case 问题和 Schema 上下文经 FastAPI
发送到 `.env` 指向的未明示模型目的地。因此 HTTP 首次成功、合法空结果、
一次修复和危险 SQL 零执行由固定 Stub + 同一真实 Pagila 的集成测试验证。
不得把该证据表述为一次真实模型经 HTTP 的调用。

## 已作废历史候选

最新候选运行自动通过 17/18；PG-MVP-003 因未命中 Gold 要求的
`activebool` 字段而得到 `EVALUATION_FIELD_RECALL_FAILED`。独立复审认定：

- 在观察该失败后增加“优先 boolean”提示属于 High 级事后评测 coaching；
- 候选运行使用过的 `bpchar → TRIM(...)` 后处理会改变值语义，属于 High
  级范围漂移。

两项调整均不作为验收修复，值改写代码已移除。该 17/18 报告永久标记为
invalidated，不得用于任何状态更新。所有 Gold 状态已恢复为 `draft`。

用户随后明确授权本设计中的通用冻结视图语义能力。完成与当前 Gold 无关的合成
测试、一次独立初审、blocking/high 修复和一次最终复审后，才建立全新的
baseline ID 并开始正式候选评测。

## 正式评测次数与终局

新基线最多运行两次完整 18 Case：

1. 第一次为正式候选；
2. 只有第一次暴露可由非 Gold 特化测试证明的通用实现缺陷，才允许修复、重新
   冻结并运行第二次；
3. 第二次后不得继续依据当前 Gold 调整 Prompt、Comparator、后处理或元数据。

18/18 自动证据和 18/18 独立审核都通过时，才逐 Case 更新为 `verified`，执行
最终回归并以 `test: complete stage 10 evaluation and security regression`
提交。

若最终仍有有效 Case 失败，失败 Case 保持 `draft`，Stage 10 implementation
记为 `completed`，MVP release qualification 记为 `not_passed`；完成工程验证
后以 `test: implement stage 10 evaluation and record qualification failure`
提交并推送，不冒充发布验收成功。

## 安全与失败处理

- 任何 baseline、Case schema、Gold 安全校验或 Gold 执行失败均使该 Case
  保持 `draft`；
- 模型网络/协议错误只记录稳定公开 code；
- Comparator 不在错误消息中放行值；
- 报告写入失败不更新 Gold；
- Gold 状态更新失败不重试跨 Case 批量写入；
- 受保护主规格和测试规格保持原哈希；
- Gold 除 `status` 外的规范内容哈希必须保持不变。

## 暂不实现

- 在线评测服务、Dashboard、缓存、并发批量模型调用；
- 多模型路由、RAG、Few-shot、训练集导出；
- 完整生产监控、OTel backend 或第三方 Trace 服务；
- 多数据源或非 PostgreSQL Comparator。
