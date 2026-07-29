# ADR 0010：证据优先评测、安全 Trace 与逐 Case 验证

## 状态

Accepted / Release qualification pending

## 决策

Stage 10 使用“先生成脱敏证据报告，再逐 Case 审核，最后逐 Case 更新状态”的
三段式验收。Runner 不自动修改 Gold Case。Gold question 只作为当前被测请求
的 user payload 进入 Workflow；不得进入 system prompt、静态 Few-shot、
RAG/检索索引、训练或调参集。Gold SQL、Gold 字段、期望结果、评测标签和失败
原因不得加入模型消息或任何运行时知识。

评测固定：

- Pagila `pagila-v3.1.0` commit
  `fef9675714cfba1756df4719b5e36075a7ddf90e`；
- PostgreSQL
  `16.14 (Debian 16.14-1.pgdg12+1)`；
- PostgreSQL image
  `postgres:16.14-bookworm@sha256:92620daddcd947f8d5ab5ba66e848702fe443d87fed30c4cea8e389fd78dfc55`；
- 规范化 runtime data-only dump SHA-256
  `e584f0beb3817d1a6f3e35518192ba66cc8b14c50df08c34527d5b15e77bd567`；
- 规范化 runtime schema-only dump SHA-256
  `74de0ad271945ff3ce8e21d9065d1c0178f01994a8f25c613afebcebed5933b2`；
- Gold status-neutral SHA-256
  `a00a8ec7496fc4e1533b2773e0267d555357a80be435a02dd70981d76ddb40d7`。

PostgreSQL plain dump 的 `restrict/unrestrict` nonce 每次随机生成。数据校验只把
该 nonce 规范化为固定 `TOKEN`，不忽略或重排其他导出内容。
正式 CLI 在加载数据库 DSN 和模型凭据前，先核对 manifest、schema/data
fixture、容器 image、服务端版本、`film` 行数和运行时 dump；任何漂移都会在
凭据加载和模型调用前失败。CLI 还要求 DSN 使用容器实际发布的 loopback 端口，
并以 `text_to_sql_reader` 连接，避免只探测正确容器、实际却评测另一数据库。

## 冻结视图语义

用户授权的视图语义能力只在基线冻结期读取锁定数据库的权威普通视图定义。
提取器仅接受授权基础表和字段的唯一 lineage，并只支持直接投影别名与简单
boolean CASE 标签两种通用规则。字符串 `::text` 只作为字面量的无损 AST
包装解开；条件中的强转、函数、`NOT`、复合谓词、子查询、未授权依赖和不确定
search path 均 fail-closed。

机械候选不会自动进入运行时。候选账本记录逐来源 evidence digest，独立审核
逐条批准或拒绝；运行时 manifest 再把完全相同的
`(object_id, alias, rule, polarity)` 聚合，并绑定批准证据集合摘要。当前锁定
Pagila 产生 10 条已审核来源证据、6 个唯一运行时语义。所有候选均只引用服务端
13 表 allowlist 中的字段；账本和 manifest 不保存视图名或原始 SQL。

生产和评测启动都先读取完整 allowlist 快照，以代码和评测 baseline 中的外部
manifest SHA-256 校验清单，再构造 `FrozenSemanticConnector`。请求期不读取
视图；wrapper 只向当前请求快照中已存在的授权字段合并 alias。Prompt 只得到
排序后的 `aliases`，不包含视图名、原始 SQL、polarity、来源或审核数据，也
没有加入 boolean 偏好指令。

## 不可变评测基线

`evaluation/pagila_baseline.json` 的自校验 baseline ID 覆盖：

- Pagila commit、fixture、PostgreSQL image/version、data/schema dump；
- 全 `draft` Gold 精确文件摘要和 status-neutral 摘要；
- 语义 manifest 整文件摘要、原始/增强 Schema 版本、视图定义集合、
  scope、extractor/policy、候选与审核摘要；
- `app/**/*.py`、`evaluation/**/*.py`、Stage 10 工具和
  `pyproject.toml` 的长度分隔代码根摘要；
- Python 实现/版本及 Prompt、Provider、Comparator、Evidence、Report
  契约版本；
- 21 个行为相关直接/传递依赖的实际安装版本；
- 不含密码的数据库 host/port/database/role、连接池、超时、行数上限和重试
  配置；
- 不含 API key 的模型 endpoint、模型、温度、超时、代码根和语义清单摘要。

正式 `evaluate` 要求 18 条 Case 全部为 `draft` 且精确文件摘要匹配，在加载
凭据前复算静态冻结项，并在构造 Provider 前复算模型配置摘要。每条 Case 证据
包含 baseline ID。`review-case` 和 `verify-case` 还必须加载当前外部 baseline，
逐字段匹配报告内嵌 baseline，并在任何审核或 Gold 写入前复算当前代码、语义和
依赖冻结，因此旧证据、审核决定和报告不能跨 baseline 重放。

## Trace

生产 Workflow 由 `TracedWorkflowRunner` 包装，不改变
`run_workflow`、`WorkflowContext` 或 `ApplicationServices` 的公共接口。
Trace 只记录 request/trace ID、终态、公开错误、节点路由与耗时、SQL 指纹、
校验/执行布尔值、Token、模型配置摘要、版本、修复/重试计数和数据库计数。
增强阶段还可记录复杂度等级、动态 K、封闭理由码、检索/融合/Rerank/裁剪和
模型路由的版本化安全摘要；不得因此加入问题或对象原文。

Trace 不保存问题、SQL、Prompt、Schema 样例值、结果行、DSN、API Key 或原始
异常。Sink 失败只写固定降级日志，不改写已完成业务结果。

## Comparator

Comparator 先规范化唯一列名并按列名对齐同名同类型投影，再规范化值。缺列、
多列、重复列或同名不同 PostgreSQL OID 均失败。`exact` 保留行序；
`multiset` 忽略行序但保留重复次数；`keyed` 拒绝重复键。

NULL 与空字符串不同。Decimal 默认精确，只有 Case 声明的列可使用
absolute/relative 容差；float 没有显式容差时失败。timestamptz 转 UTC 比较，
嵌套 JSON 严格比较结构，截断结果和 grain 不一致均失败。错误消息不包含具体
值。

## 真实评测与安全 Fixture

15 条允许执行 Case 的 Gold SQL 和预测 SQL 都通过同一个 Stage 3 Validator，
并由同一个 Stage 6 只读 Connector、同一个
`REPEATABLE READ READ ONLY` 事务可见性快照执行。每次 SQL 在内层 savepoint
中运行，因此预测的第一次数据库错误不会破坏有限修复所需的外层快照。最终门
要求 Gold 校验/执行成功、预测校验成功、实际数据库执行次数与 attempt 证据
一致、必需表字段同时被 Linker 和最终 SQL 命中、Comparator 通过和 Trace
完整。

PG-MVP-011 对应的 Pagila `payment` 分区父表没有可读取的 FK 元数据，故
join-path recall 保留为诊断缺口；该 Case 的最终 SQL 命中双方 JOIN 字段，且
599 行结果与 Gold 完全一致。其他含 Gold join edge 的 Case 均召回对应 FK
路径。

系统在 Validator 前只做与 Gold 无关的投影列名规范化：直接列使用源列名；
`COUNT(普通列)`、`SUM(普通列)` 和 `DATE_TRUNC(普通列, unit)` 使用由表达式
本身推导的稳定别名；无歧义时同步 `GROUP BY`/`ORDER BY` 中的旧别名。规则跳过
`COUNT(*)`、源列同名歧义、多聚合、其他函数、多 statement 和不可解析 SQL，
并在应用前检查全部原始/目标输出名，任何重复 alias 或
`GROUP BY`/`ORDER BY` 绑定歧义均整条跳过；规则不改变表达式或值语义。曾尝试
的 `bpchar → TRIM(...)` 值改写已被独立审查
判定为 High 级范围漂移并删除。

按照测试规格的固定 Stub 策略，权限 Case 使用受保护 Case 中声明的未授权表构造
只读拒绝输入；两条危险 SQL Case 使用自身 fixture。三者都必须在真实 Workflow
Validator 中被拒绝，且数据库执行和修复计数为零。PG-MVP-018 第一次使用自身
错误字段 fixture，第二次调用真实 Provider，并且只允许一次修复。

## 审核与状态更新

每条 `CaseEvaluation` 都有覆盖完整脱敏证据的 SHA-256。`passed=true` 的结构
本身必须证明预期终态/错误一致；执行 Case 还必须证明 Gold 校验与执行、预测
校验与执行、表字段召回和 Comparator 全部通过；拒绝 Case 必须证明零执行和零
修复。只有上述结构成立、摘要匹配且逐条审核为 `approved` 的 Case 才能进入
状态更新器。
审核批准还会生成绑定该 evidence digest 的独立 review digest。更新器再次
核对报告、Case ID、两级摘要和硬编码的 status-neutral hash，仅把目标行唯一的
`"status":"draft"` 原子替换为 `"status":"verified"`，随后复算整套哈希。

已作废历史：

- 旧候选运行自动证据通过 17/18；
- PG-MVP-003 为 `EVALUATION_FIELD_RECALL_FAILED`，预测结果 584 行而 Gold
  为 599 行；
- 独立复审拒绝在观察失败后增加“优先 boolean”提示，也拒绝改变值语义的
  `bpchar → TRIM(...)` 后处理；
- 18/18 人工审核均为 `rejected`，0/18 为 `verified`；
- 全部 Gold Case 已恢复为 `draft`。

当前 Gold 文件 SHA-256 为
`049e048b821e949936c1793d441f7adcda4660f10f8d0acf63e4f766a9726c22`；
status-neutral SHA-256 为
`a00a8ec7496fc4e1533b2773e0267d555357a80be435a02dd70981d76ddb40d7`。
结构化候选报告的 `initial_status` 记录的是当次运行时已经被更新过的状态，
并且缺少当前语义/代码冻结。因此它已改为 invalidated report version 并移入
`evaluation/reports/invalidated/`，只能作为历史失败证据。

恢复后的正式候选在唯一初审、blocking/high 修复、最终复审和 baseline v3
冻结后运行。结果为自动证据 `12/18`、独立审核
`12 approved / 6 rejected`，Gold 保持 `draft=18`。六个失败分别落在列契约、
必需字段覆盖和候选命中权限边界；Gold 校验/执行与安全门禁证据正常，未发现
可由非 Gold 合成证据证明的通用 blocking/high 实现缺陷。依据两次运行终局
规则，候选 1 即为最终结果，不启动随机重试或 Gold 驱动调优。Stage 10 工程
实现完成，MVP 发布资格记为 `not_passed`。

## 限制

- 真实模型即使 `temperature=0` 仍可能产生非完全确定的投影；只有新冻结
  baseline 上的 18/18 自动证据和 18/18 独立审核才是发布验收证明。
- 运行环境的外部数据审查不允许再次把 Case 问题和 Schema 上下文经 FastAPI
  smoke 发送到未明示的模型目的地。HTTP 闭环仅由固定 Stub + 真实 Pagila
  集成测试验证，不能冒充为一次“真实模型经 HTTP”运行。
- 不实现在线评测服务、Dashboard、OTel backend、多模型路由、多数据源、
  Few-shot、缓存或训练集导出。
