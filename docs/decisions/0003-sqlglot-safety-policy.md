# ADR 0003：SQLGlot PostgreSQL 安全校验策略

## 状态

已验证，2026-07-28。

## 决策

第三开发阶段使用锁定的 `sqlglot==30.13.0` 实现纯函数式、fail-closed 的
PostgreSQL SQL 安全门。正则或关键词无法可靠覆盖注释、字符串、嵌套 CTE、
别名和方言节点；把未校验 SQL 发送到数据库 `EXPLAIN` 又会越过确定性安全
边界，因此两者均不采用。

SQLGlot 版本固定，不使用宽松范围。升级前必须重新检查 AST 形态，并运行完整
允许、拒绝、授权、字段、函数和 Pagila 回归。

## 校验顺序

校验严格按以下顺序执行：

1. PostgreSQL 方言解析；
2. 单 statement；
3. 根节点必须是 `SELECT`；
4. 禁止节点、锁、`SELECT INTO` 和 wildcard；
5. 版本化 AST allowlist；
6. 授权表与元数据快照上下文一致性；
7. 基表作用域、Schema 和对象存在性；
8. 字段 qualification 和引用证据；
9. `mvp-v1` 函数策略；
10. PostgreSQL 方言规范序列化。

任何阶段失败都返回不含规范 SQL和部分引用的结构化结果。解析错误、SQLGlot
错误、SQL 文本、Schema/表/字段/函数名、DSN 和驱动错误不会进入公开消息。

## 只读与 AST 策略

根节点只接受 `exp.Select`。最终主体为 `SELECT` 的 CTE 可以通过，但 CTE、
子查询或表达式中的 DML、DDL、命令、`COPY`、`SET`、`SELECT INTO` 和锁节点
仍会被遍历拒绝。多 statement 整体拒绝，不截取第一条。

AST 使用 `mvp-v1` 精确类型 allowlist。明确危险节点优先拒绝；未列出的节点
默认返回 `SQL_UNKNOWN_AST`。`SELECT *`、`table.*` 和 PostgreSQL 整行别名
引用拒绝；qualification 后的 `exp.TableColumn` 用于识别直接或表达式包裹的
整行引用。只有直接、无表限定的 `COUNT(*)` 作为聚合特例允许。

## 授权、对象和字段

授权只来自调用方传入的服务端 `allowed_schemas` 和规范
`schema.table` 列表。元数据快照不得包含授权范围外的表；上下文不一致按内部
错误拒绝。SQL 中的显式 Schema 必须精确授权，三段 catalog 引用拒绝；未限定
表名只有在授权范围中唯一时才解析，同名歧义要求显式 Schema。

表和字段存在性只使用第二阶段不可变快照，不查询数据库。SQLGlot `Scope`
用于区分基表与 CTE/派生表，qualification 处理别名、JOIN、CTE 输出、派生表
和相关子查询。成功证据只记录去重、排序后的底层
`schema.table` 和 `schema.table.column`。

PostgreSQL 未加引号标识符按小写折叠；带引号标识符保留精确大小写。传给
SQLGlot `MappingSchema` 的大小写敏感 Schema、表和字段使用正确转义的 quoted
identifier，授权比较仍保持原始精确标识符。

## 函数策略

`mvp-v1` 允许：

- `COUNT`、`SUM`、`AVG`、`MIN`、`MAX`；
- `COALESCE`、`NULLIF`；
- `LOWER`、`UPPER`、`LENGTH`、`TRIM`、`SUBSTRING`；
- `DATE_TRUNC`、`EXTRACT`、`CURRENT_DATE`；
- `ROUND`、`ABS`、`CEIL`、`FLOOR`；
- `CASE`、`CAST`。

映射基于精确 AST 类型：`DATE_TRUNC` 使用 `exp.TimestampTrunc`，`CASE`
内部 `exp.If` 仅在父节点为 `exp.Case` 时允许。SQLGlot 同时作为结构节点和
`exp.Func` 的布尔/子查询节点，只在精确结构 allowlist 中放行。匿名函数、
未映射 Func、独立 `IF()`、UDF、`pg_sleep`、文件/网络和 dblink 能力默认
返回 `SQL_FUNCTION_NOT_ALLOWED`。CAST 目标仅允许显式内建标量类型集合；
`VARCHAR`、`NUMERIC` 和时间精度等参数只允许挂在批准类型下的非负数字
`exp.DataTypeParam`。自定义类型及其参数化形式拒绝，避免通过类型输入函数
绕过 UDF 默认拒绝。

## 错误与路由证据

- 解析失败：`SYNTAX_ERROR / SQL_PARSE_ERROR`；
- 多 statement、危险节点、wildcard、未授权对象和函数：
  `PERMISSION_DENIED`；
- 同名对象、快照对象或字段问题：`SCHEMA_ERROR`；
- PostgreSQL 序列化不支持：`DIALECT_ERROR`；
- 授权与快照上下文不一致：`UNKNOWN`。

权限和安全错误不可交给模型修复；后续 Workflow 只允许语法、Schema 和方言
错误进入有限修复。

## 验证证据

- Stage 1–3 单元测试：194 项通过；
- P0 SQL 安全测试：29 项通过；
- 真实 PostgreSQL/Pagila 集成测试：34 项通过，其中 18 项为 Stage 3；
- PG-MVP-001～014 和 PG-MVP-018 Gold SQL 均通过授权对象、字段和函数校验；
- PG-MVP-016 DELETE、PG-MVP-017 多 statement 和 staff 权限 Case 均拒绝；
- CTE、派生表、相关子查询、跨 Schema 歧义和大小写敏感对象测试通过；
- `compileall`、`pip check`、Docker Compose 配置和受保护文件哈希检查通过。

## 延后到第四阶段

BM25/词法 Schema Linking、Top-K=10、字段聚合、FK 路径扩展和修复时重新
Linking 属于第四开发阶段。本阶段不实现 LLM、SQL 生成、指纹、Workflow、
FastAPI、Comparator 或评测 runner。
