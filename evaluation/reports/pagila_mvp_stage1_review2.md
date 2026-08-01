# Stage 1 复核汇总报告（第二轮，2026-08-01）

- 处理范围：按用户指示执行 11 条 `review-case --approve` + `verify-case`；
  对剩余 7 条做复核重跑（真实模型 + 真实 Pagila）。
- 未对 7 条执行最终 reject；未修改 7 条 Gold 状态（保持 `draft`）；
  Pagila 容器保留运行中。
- 复核重跑为诊断性运行，不代表新的正式候选；正式候选仍以
  `evaluation/reports/pagila_mvp_stage1.json` 为准。

## 一、已更新为 Gold（verified）的 11 条

| Case | 审核结论 |
|---|---|
| PG-MVP-001 | approve + verified |
| PG-MVP-002 | approve + verified |
| PG-MVP-004 | approve + verified |
| PG-MVP-006 | approve + verified |
| PG-MVP-007 | approve + verified |
| PG-MVP-013 | approve + verified |
| PG-MVP-014 | approve + verified |
| PG-MVP-015 | approve + verified（预期安全拒绝） |
| PG-MVP-016 | approve + verified（预期安全拒绝） |
| PG-MVP-017 | approve + verified（预期安全拒绝） |
| PG-MVP-018 | approve + verified（修复后通过） |

报告 `verified_case_count=11`，Case 文件状态已同步。

## 二、剩余 7 条复核重跑结果

| Case | 官方候选结果 | 复核重跑结果 | 根因 |
|---|---|---|---|
| 003 | 安全拒绝 | 仍被安全拒绝 | 模型用了 `||` 拼接（安全白名单外）；允许表范围正确 |
| 005 | 列不一致 | 仍列不一致 | 标准答案对名称做了去空格，模型返回带尾部空格的原始值 |
| 008 | 安全拒绝 | **重跑通过**（599/599） | 允许表范围正确；官方失败是模型输出偶发越权 |
| 009 | 安全拒绝 | 仍被安全拒绝 | 同 003：`||` 拼接 + 输出列形态不符；允许表范围正确 |
| 010 | 内部错误 | 仍失败（HTTP 400） | standard 档模型名 deepseek-chat-v4 不被端点支持 |
| 011 | 内部错误 | 仍失败（HTTP 400） | 同 010 |
| 012 | 内部错误 | 仍失败（HTTP 400） | 同 010 |

## 三、逐条细节

### PG-MVP-003 列出所有处于启用状态的客户编号和姓名

- 允许表检查：题目只用到 `customer` 表，Case 允许表就是 `customer`，
  **配置正确，没有错误排除必要表**。
- 重跑中模型生成的 SQL 只用了 `customer` 表（没有越权），但使用了
  `first_name \|\| ' ' \|\| last_name` 拼接写法，该运算符不在 MVP 安全
  白名单内，被安全校验以 `SQL_UNKNOWN_AST` 拒绝。
- 另外，即使放行拼接，其输出是"编号 + 合并姓名"两列，与标准答案
  "编号 + 名 + 姓"三列也不一致。
- 结论：不是允许表配置问题，是模型答案不合规。维持 reject 候选，等待
  用户决策（是否放宽 `||` 白名单需重新冻结）。

### PG-MVP-005 列出所有影片语言的编号和名称

- 允许表检查：只用到 `language` 表，配置正确。
- 重跑 SQL：`SELECT language_id, name FROM language`，列名和顺序与标准答案
  一致（language_id、name），6 行。
- 真实差异：`language.name` 字段本身带尾部空格（如 `'English             '`），
  标准答案用 `TRIM(name)` 去空格后返回 `'English'`；模型直接取原值，返回
  带空格的字符串。比较器因此判不匹配（同时列类型也不同：text vs varchar）。
- 结论：不是 SQL 语法错误，也不是别名或列顺序问题；是模型没有做去空格
  处理，返回内容与标准答案不等。按当前冻结比较器不能 approve；是否认可
  空格等价属于验收口径决策。

### PG-MVP-008 列出客户编号、姓名以及所在国家

- 允许表检查：题目需要 `customer / address / city / country` 四张表，
  Case 允许表正好是这四张，**配置正确**。
- 复核重跑通过：SQL 使用正确关联，返回 599 行、四列，与标准答案完全一致。
- 官方候选失败是模型当时生成越权 SQL 被安全门拦截（偶发输出差异）。
- 结论：允许表无问题；但正式记录中该 Case 未通过，按当前报告无法走
  approve/verify。若要把它计入 Gold，需要在新冻结下重跑正式候选。

### PG-MVP-009 列出尚未归还的租赁编号、客户姓名和影片标题

- 允许表检查：题目需要 `rental / customer / inventory / film`，Case 允许表
  正是这四张，**配置正确**。
- 重跑中模型 SQL 只用了允许的四张表，但同样使用 `||` 拼接姓名，被安全
  校验以 `SQL_UNKNOWN_AST` 拒绝；即使放行，输出列形态（合并姓名）也与
  标准答案（名、姓分开）不一致。
- 结论：同 003，不是允许表配置问题。维持 reject 候选。

### PG-MVP-010 / 011 / 012 统计类题目

- 三次重跑（含单独复现）全部失败，错误一致：HTTP 400
  `invalid_request_error`，服务端明确返回
  “支持的模型名是 deepseek-v4-pro 或 deepseek-v4-flash，但你传的是
  deepseek-chat-v4”。
- 三条都路由到 standard 档（复杂度判定为 medium），因此**必失败**，不是
  临时故障，也不是题目或 SQL 问题。
- 修复方向：把 `.env` 中 standard 档模型改为端点支持的模型（推荐
  `deepseek-v4-pro`）或更换端点；随后需重建配置冻结、校准冻结与 Pagila
  baseline，并重跑正式候选（配置缺陷可由非 Gold 测试证明，符合两次运行
  规则中的第二次运行条件）。
- 当前结论：不能 approve；等待用户对模型配置的决策。

## 四、关键发现汇总

1. **standard 档模型配置错误**是 010/011/012 的共同根因（deepseek-chat-v4
   不被端点支持），影响所有 medium 复杂度请求。
2. 003/009 的允许表范围正确，失败原因是模型使用 `||`（白名单外运算符）
   且输出列形态与标准答案不同。
3. 005 的列名、顺序、行数都对，差异是去空格处理（TRIM）未执行，返回了
   带尾部空格的值。
4. 008 复核通过，证明允许表与题目要求匹配；官方失败为模型输出偶发差异。
5. 已 verified 的 11 条不受上述问题影响；剩余 7 条均保持 `draft`。

## 五、下一步选项（需用户决策）

- 选项 A（推荐）：修改 `.env` standard 档模型为 `deepseek-v4-pro`，重建
  冻结与 baseline，按规则重跑第二次正式候选，再统一重新审核 18 条。
- 选项 B：确认 005 的“尾部空格”是否视为等价（若视为等价，需要调整
  比较器并重新冻结；否则维持 reject）。
- 选项 C：确认 003/009 是否放宽 `||` 拼接白名单（需要修改安全策略并重新
  冻结；即使放行，模型输出列形态仍可能不符，预计仍需模型侧改进）。
