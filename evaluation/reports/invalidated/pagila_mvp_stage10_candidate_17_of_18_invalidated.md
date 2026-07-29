# Pagila MVP Stage 10 已作废候选报告

## 结论

该历史候选已永久作废，不代表当前 Stage 10 状态。

最新候选运行的自动证据为 17/18 通过；PG-MVP-003 为
`EVALUATION_FIELD_RECALL_FAILED`。随后独立复审认定该候选运行仍包含不可接受的
事后评测调整，因此 18 条 Case 的人工审核全部标记为 `rejected`。所有 Gold
Case 已恢复为 `draft`，没有 Case 保留 `verified` 状态。

本报告只保留为失败历史，不是发布验收证明，也不得用于更新 Gold 状态。

## 锁定基线

- Pagila tag：`pagila-v3.1.0`
- Pagila commit：
  `fef9675714cfba1756df4719b5e36075a7ddf90e`
- PostgreSQL：
  `16.14 (Debian 16.14-1.pgdg12+1)`
- PostgreSQL image：
  `postgres:16.14-bookworm@sha256:92620daddcd947f8d5ab5ba66e848702fe443d87fed30c4cea8e389fd78dfc55`
- 规范化 data-only dump SHA-256：
  `e584f0beb3817d1a6f3e35518192ba66cc8b14c50df08c34527d5b15e77bd567`
- 规范化 schema-only dump SHA-256：
  `74de0ad271945ff3ce8e21d9065d1c0178f01994a8f25c613afebcebed5933b2`
- Gold 当前/初始文件 SHA-256：
  `049e048b821e949936c1793d441f7adcda4660f10f8d0acf63e4f766a9726c22`
- Gold status-neutral SHA-256：
  `a00a8ec7496fc4e1533b2773e0267d555357a80be435a02dd70981d76ddb40d7`

候选评测前已验证 manifest、上游 schema/data fixture、容器 image、服务端版本、
`film` 行数、data-only/schema-only dump，并强制实际 DSN 指向该容器的发布端口
且使用 `text_to_sql_reader`。Gold 与预测在同一
`REPEATABLE READ READ ONLY` 快照中运行。

## 候选运行结果

| Case | 自动结果 | 人工审核 | 最终 Gold 状态 |
|---|---|---|---|
| PG-MVP-001 | EVALUATION_PASS | rejected | draft |
| PG-MVP-002 | EVALUATION_PASS | rejected | draft |
| PG-MVP-003 | EVALUATION_FIELD_RECALL_FAILED | rejected | draft |
| PG-MVP-004 | EVALUATION_PASS | rejected | draft |
| PG-MVP-005 | EVALUATION_PASS | rejected | draft |
| PG-MVP-006 | EVALUATION_PASS | rejected | draft |
| PG-MVP-007 | EVALUATION_PASS | rejected | draft |
| PG-MVP-008 | EVALUATION_PASS | rejected | draft |
| PG-MVP-009 | EVALUATION_PASS | rejected | draft |
| PG-MVP-010 | EVALUATION_PASS | rejected | draft |
| PG-MVP-011 | EVALUATION_PASS | rejected | draft |
| PG-MVP-012 | EVALUATION_PASS | rejected | draft |
| PG-MVP-013 | EVALUATION_PASS | rejected | draft |
| PG-MVP-014 | EVALUATION_PASS | rejected | draft |
| PG-MVP-015 | EVALUATION_PASS | rejected | draft |
| PG-MVP-016 | EVALUATION_PASS | rejected | draft |
| PG-MVP-017 | EVALUATION_PASS | rejected | draft |
| PG-MVP-018 | EVALUATION_PASS | rejected | draft |

结构化 JSON 报告保存该次候选证据，不包含问题、SQL、Prompt、结果行、DSN、
API Key 或原始异常。其汇总为：

- 自动通过：17/18
- 审核通过：0/18
- 审核拒绝：18/18
- verified：0/18

JSON 中每条 Case 的 `initial_status=verified` 是当次运行时先前状态更新尝试留下
的事实记录；这些更新已被后续独立审查作废并全部恢复为 `draft`。这也意味着该
候选运行不满足“生成报告时全部 Case 必须保持 draft”的验收前提，不能据此批准
任何 Case。

## 最终 blocked 快照工程回归

- 单元测试：502 passed
- 安全测试：88 passed
- 真实 Pagila 集成测试：73 passed
- 单进程全量回归：663 passed
- `python -m compileall`：通过
- Python 依赖一致性：通过
- Docker Compose 配置检查：通过
- `git diff --check`：通过
- 最终只读 Pagila runtime baseline 复核：通过
- 两份受保护规格哈希：与入口基线一致
- Gold：与 `HEAD` 逐字节一致，18 条均为 `draft`

这些结果证明当前工程快照没有回归失败，但不能替代失败的真实 Case 评测和独立
审核门。

## 阻塞原因

1. PG-MVP-003 的问题文本与现有 Schema 元数据不足以权威区分数值状态列和
   boolean 状态列。真实模型未引用 Gold 要求的 boolean 字段，因此必需字段
   召回失败。
   锁定 Pagila 的 `customer_list` 视图定义确实使用 `customer.activebool`
   生成文本 `active`，但 `customer.active` 和 `customer.activebool` 在运行时
   都没有字段注释，且当前授权的表元数据/Prompt 契约不包含视图定义。把已见
   Gold 后发现的视图表达式临时转换为合成注释、别名或 Prompt 规则，会扩展
   Stage 2/5 的生产语义边界，不能作为本轮验收修复。
2. 在已经观察到该失败后加入“优先 boolean”提示再对同一 Gold 集验收，会构成
   事后 model coaching；独立审查将其评为 High 级评测独立性问题，未采用。
3. 候选运行中使用过的 `bpchar → TRIM(...)` 后处理会改变值语义，而不只是规范
   列名；独立审查将其评为 High 级范围漂移。该后处理已从代码移除，因此候选
   报告不能升级为批准证据。

## 解除阻塞所需条件

必须先在当前 Gold 之外完成至少一项：

- 增加独立、权威的业务元数据，明确状态列含义，并重新冻结评测基线；或
- 在未查看的新 holdout 上预先冻结通用类型策略和固定宽度字符串输出语义，
  再用新的未见评测集验证。

第一条可引用锁定上游 `customer_list` 视图作为元数据来源，但必须先定义通用、
可审计的视图语义提取规则，获得新增生产行为授权，并在重新冻结的非当前候选
运行中验证；不能只为 `activebool` 写特例。

不得继续根据当前 18 条 Gold 调整 Prompt、后处理或 Comparator，也不得把当前
17/18 候选结果批量标记为 `verified`。
