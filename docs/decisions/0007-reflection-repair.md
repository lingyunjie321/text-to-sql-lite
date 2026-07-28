# ADR 0007：确定性反思、SQL 指纹与修复预算

## 状态

已验证，2026-07-28。

## 决策

第七开发阶段新增纯确定性的 `app.reflection`。它不调用模型、不执行 SQL，而是：

- 为初始和修复 SQL 生成稳定指纹；
- 保存不可变 attempt 历史；
- 在执行前拒绝重复和 A→B→A；
- 最多接受三个不同修复；
- 按统一 `ErrorType` 选择重新 Linking、重新生成、澄清或终止。

LangGraph 只在 Stage 8 编排这些纯函数，不重新实现指纹、预算或路由规则。

## 指纹

可解析 SQL 先用 SQLGlot PostgreSQL 完整解析，按 PostgreSQL 规则规范未加引号
标识符，再稳定序列化全部 statement，最后计算 SHA-256。因此关键字、空白、末尾
分号和未加引号标识符大小写差异不会绕过重复检测；加引号标识符的大小写语义仍
保留。行注释和块注释在规范序列化时移除，不能通过添加无语义注释绕过去重。

解析、词法切分或序列化失败时，直接对未经 trim 或改写的原始 UTF-8 SQL 计算
SHA-256，符合主规格的精确原文规则。指纹只负责循环终止，多 statement 即使可
指纹化也仍会被 Stage 3 拒绝。

## Attempt History

`AttemptHistory` 至少含 attempt 0，并强制：

- attempt 编号从 0 连续递增；
- `repair_count == len(attempts) - 1` 且最多为 3；
- attempt 指纹唯一，seen set 与历史精确一致；
- attempts/seen 容器强制为 tuple/frozenset，拒绝可变 alias；
- 每个 attempt 只能记录一次校验和一次执行；
- 成功校验必须为当前策略，且规范 SQL 指纹必须与当前 attempt 相同；
- 只有成功校验后才能记录执行结果；
- 执行成功和数据库错误不能同时存在。

修复注册先在全部 seen 指纹中查重，再检查预算。重复或超预算时 History 原样
返回，没有新 attempt，不增加 `repair_count`，也没有机会进入 Validator 或
Connector。

## 反思路由

- `SYNTAX_ERROR` → `GENERATE_SQL` / `MINIMAL_SQL_REPAIR`；
- `SCHEMA_ERROR` → `SCHEMA_LINKING` / `RELINK_SCHEMA`；
- `DIALECT_ERROR` → `GENERATE_SQL` / `REGENERATE_POSTGRES`；
- 业务知识缺失或语义歧义 → `CLARIFICATION`；
- 资源风险仅在显式可安全缩小时 → `CLARIFICATION`，否则终止；
- 权限、安全、连接、超时、重复和未知错误 → `FINALIZE`；
- 已接受三个修复后，任何可修复错误也直接终止。

只有语法、Schema、方言错误可以注册新 SQL。Connector 内部同 SQL 连接重试不
创建 attempt，也不增加修复计数。

## 验证证据

- 指纹、attempt、预算、完整错误路由和安全边界聚焦测试：52 项通过；
- PG-MVP-018 的错误字段初始 SQL 经重新 Linking、不同修复、完整 Validate 和
  真实 Pagila Execute 后成功，`repair_count=1`；
- A→B→A 集成场景在执行前返回 `DUPLICATE_SQL`。
- Stage 1–7 单元测试：335 项通过；
- Stage 1–7 安全测试：57 项通过；
- Stage 1–7 集成测试：62 项通过。

## 延后

32 步总上限、九节点状态机、FinalStatus、通用超时/异常 wrapper 和 LangGraph
编排属于 Stage 8；FastAPI、Trace、Comparator 和评测属于 Stage 9–10。
