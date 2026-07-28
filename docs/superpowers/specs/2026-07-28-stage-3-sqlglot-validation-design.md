# 第三开发阶段：SQLGlot PostgreSQL AST 与安全校验设计

## 目标

在第二阶段授权元数据快照基础上，为后续 Workflow 提供一个纯函数式、
fail-closed 的 SQL 安全门。所有模型生成 SQL 必须先通过该安全门，才能交给
PostgreSQL Connector。

本阶段完成后，项目应能：

- 使用 PostgreSQL 方言解析且只接受一条语句；
- 只允许 `SELECT` 或最终主体为 `SELECT` 的受控 CTE；
- 拒绝写入、DDL、命令、锁、`SELECT INTO` 和未知 AST；
- 验证表授权、表/字段存在性和作用域内列引用；
- 只允许主规格批准的函数；
- 返回结构化、可路由且不泄露 SQL/对象名的校验结果；
- 使用固定 Pagila 快照验证允许 SQL 与安全拒绝 Case。

## 范围

### 包含

- SQLGlot 30.13.0 依赖锁定；
- PostgreSQL 单方言解析；
- 单 statement、只读根节点和 CTE 内部只读检查；
- 明确禁止节点和版本化 AST 节点 allowlist；
- `SELECT *` 拒绝，`COUNT(*)` 作为聚合特例允许；
- Schema/表授权与第二阶段快照一致性检查；
- 表别名、CTE、派生表、子查询和相关子查询字段解析；
- 函数 allowlist；
- 规范 PostgreSQL SQL、引用表和引用字段输出；
- 单元测试、Pagila 集成测试、第三阶段技术决策和使用说明。

### 不包含

- Schema Linking、BM25、Top-K 或 JOIN Path 搜索；
- LLM、Prompt、SQL 生成或反思修复；
- SQL attempt 指纹、重复 SQL 和修复计数；
- LangGraph 节点、路由、Connector 调用次数或 API；
- 查询成本估算、`EXPLAIN`、动态资源阈值或 SQL 自动改写；
- 数据库执行、结果比较、Trace 或缓存；
- 新函数配置接口、UDF 审批后台或多方言。

SQL 安全门只判断结构、授权和对象真实性，不判断业务语义是否正确，也不把
SQL 发送到数据库做“试运行”。

## 方案选择

### 方案 A：SQLGlot AST 分层校验，默认拒绝（采用）

使用固定版本 SQLGlot 的 PostgreSQL parser，将语句形态、危险节点、对象、
字段和函数分层验证。安全行为由 AST 类型和已验证元数据决定，不依赖文本匹配。
优点是可测试、可审计，并能覆盖 CTE、别名和子查询；缺点是升级 SQLGlot 时
必须重新审核 AST allowlist。固定版本和完整安全回归可以控制该风险。

### 方案 B：正则/关键词主导

实现简单，但注释、字符串、大小写、嵌套 CTE 和方言变体很容易造成误判或绕过。
主规格要求所有 SQL 经过 SQLGlot，因此不采用。

### 方案 C：SQLGlot 基础解析后交给数据库 `EXPLAIN`

数据库能补充名称解析，但会让未通过确定性安全策略的 SQL 到达数据库，并增加
权限、超时和副作用边界。只读账号仍保留为第二道防线，不能代替 AST 安全门，
因此不采用。

## 依赖决策

锁定 `sqlglot==30.13.0`。该版本支持 Python 3.12，且已核对以下 PostgreSQL
AST 表达：

- `SELECT INTO` 为 `exp.Into`；
- `FOR UPDATE` / `FOR SHARE` 为 `exp.Lock`；
- `COPY` 为 `exp.Copy`；
- `CALL`、`DO`、`RESET` 的不支持语法回退为 `exp.Command`；
- `SET` 为 `exp.Set`；
- 未知/UDF 函数为 `exp.Anonymous`；
- `DATE_TRUNC` 规范化为 `exp.TimestampTrunc`；
- `CASE` 内部分支使用结构性 `exp.If`。

SQLGlot 的 minor 版本可能包含不兼容 AST 变化。任何版本升级都必须重新跑完整
允许/拒绝矩阵，不允许使用宽松的版本范围。

## 组件设计

新增 `app/validation/`：

```text
app/validation/
├── __init__.py
├── models.py
├── policy.py
└── sql_validator.py
```

- `models.py`：不可变的校验结果和结构化问题；
- `policy.py`：`mvp-v1` AST 与函数策略；
- `sql_validator.py`：解析、作用域、授权、字段与函数校验；
- `__init__.py`：稳定公共接口。

SQLGlot AST 不进入返回模型，避免把第三方可变对象传播到 Workflow State。

## 公共接口

```python
def validate_sql(
    sql: str,
    *,
    allowed_schemas: tuple[str, ...],
    allowed_tables: tuple[str, ...],
    snapshot: SchemaSnapshot,
) -> ValidationResult:
    ...
```

返回模型：

```python
@dataclass(frozen=True, slots=True)
class ValidationIssue:
    error_type: ErrorType
    code: str
    public_message: str


@dataclass(frozen=True, slots=True)
class ValidationResult:
    is_valid: bool
    normalized_sql: str | None
    referenced_tables: tuple[str, ...]
    referenced_columns: tuple[str, ...]
    issue: ValidationIssue | None
    policy_version: str
```

成功结果必须满足：

- `is_valid is True`；
- `normalized_sql` 是 SQLGlot 以 PostgreSQL 方言和
  `unsupported_level=RAISE` 稳定序列化的单条 SQL；
- 引用对象使用 `schema.table` 和 `schema.table.column`；
- 引用集合去重并稳定排序；
- `issue is None`。

失败结果必须满足：

- `is_valid is False`；
- `normalized_sql is None`；
- 引用对象为空，避免从失败结果泄露部分解析信息；
- `issue` 存在；
- `public_message` 不包含原 SQL、表、字段、函数、Schema 或 SQLGlot 原始错误。

`ErrorType` 暂时复用现有完整 Workflow 枚举。第三阶段不移动第一阶段错误类型，
避免为了模块位置做无关重构。

## 校验顺序

```text
上下文一致性
→ SQLGlot(postgres) 解析
→ 单 statement
→ 根节点 SELECT
→ 禁止节点 / 锁 / INTO / wildcard
→ 版本化 AST allowlist
→ 表作用域与授权
→ 字段存在性和歧义
→ 函数策略
→ PostgreSQL 规范序列化
→ 允许执行
```

顺序具有安全含义：多 statement、危险节点和未授权对象在任何字段补全或规范化
之前拒绝，不能只保留第一条或改写成“看起来安全”的 SQL。

## 上下文一致性

`allowed_tables` 必须使用第二阶段的 `schema.table` 规范格式，并通过
`normalize_metadata_scope()` 去重、排序和大小写保留。

快照中每张表必须位于授权范围内。若调用方传入的快照包含范围外对象，返回：

- `ErrorType.UNKNOWN`；
- code `SQL_VALIDATION_CONTEXT_INVALID`；
- 公开消息 `The SQL validation context is invalid.`。

授权范围可以包含快照中不存在的表，因为未知/不可见对象在第二阶段会返回空
结果。表为空的 SQL（例如 `SELECT CURRENT_DATE`）仍可按其他规则校验。

## 解析、单语句与只读根

使用：

```python
expressions = sqlglot.parse(
    sql,
    read="postgres",
    error_level=ErrorLevel.RAISE,
)
```

规则：

- 空 SQL、`ParseError` 或没有有效表达式：
  `SYNTAX_ERROR / SQL_PARSE_ERROR`；
- 表达式数量不等于 1：
  `PERMISSION_DENIED / SQL_MULTIPLE_STATEMENTS`；
- 唯一根节点不是 `exp.Select`：
  `PERMISSION_DENIED / SQL_NOT_READ_ONLY`；
- PostgreSQL 规范序列化抛出 `UnsupportedError`：
  `DIALECT_ERROR / SQL_DIALECT_ERROR`。

根节点必须是 `exp.Select`。CTE 是 `Select` 的 `with_` 子树；写操作 CTE 会在
禁止节点阶段拒绝。`UNION`、`INTERSECT` 和 `EXCEPT` 的根是 set operation，
本阶段不放行，因为主规格只批准 `SELECT` 或最终主体为 `SELECT` 的受控 CTE。

## 禁止节点与 AST allowlist

无论出现于根、CTE、子查询还是表达式内部，以下节点一律拒绝：

- `exp.Insert`、`exp.Update`、`exp.Delete`、`exp.Merge`；
- `exp.Create`、`exp.Alter`、`exp.Drop`、`exp.TruncateTable`；
- `exp.Copy`、`exp.Command`、`exp.Set`；
- `exp.Into`、`exp.Lock`；
- 其他 DDL、DML、命令或事务控制节点。

先检查明确禁止集合，再检查 `mvp-v1` AST 类型 allowlist。allowlist 只覆盖：

- Select、CTE、FROM、JOIN、子查询和别名结构；
- WHERE、GROUP BY、HAVING、ORDER BY、LIMIT；
- 标识符、字面量和允许的类型表达；
- 比较、布尔、算术、NULL、IN、BETWEEN、LIKE、EXISTS；
- 主规格批准的函数节点及其必要结构节点。

不在 allowlist 的节点以
`PERMISSION_DENIED / SQL_UNKNOWN_AST` fail closed。该规则防止 SQLGlot 新增
节点或解析回退被静默放行。`exp.Func` 子类由后续函数策略独立默认拒绝，
不会通过通用 AST 集合宽松放行。

`exp.Star` 默认拒绝。只有作为无表限定、直接 `COUNT(*)` 参数时允许；投影
`SELECT *`、`table.*` 以及其他函数中的 `*` 返回
`PERMISSION_DENIED / SQL_WILDCARD_FORBIDDEN`。

## 表授权与作用域

先在 AST 深拷贝上调用
`normalize_identifiers(..., dialect="postgres")`：未加引号标识符按
PostgreSQL 规则折叠为小写，带引号标识符保留精确大小写。随后使用
`sqlglot.optimizer.scope.traverse_scope()` 遍历每个查询作用域。
`scope.sources` 中：

- 值为 `exp.Table` 时是数据库基表，需要授权和快照验证；
- 值为 SQLGlot `Scope` 时是 CTE 或派生表，不作为数据库对象再次校验，
  其内部作用域会独立遍历。

基表解析规则：

1. 三段式 catalog 引用一律拒绝；
2. 带 Schema 的表必须精确命中 `allowed_tables`；
3. 未限定表名按授权范围中的表名匹配；
4. 唯一匹配时解析为该 `schema.table`；
5. 无匹配视为未授权，返回 `PERMISSION_DENIED / SQL_OBJECT_NOT_ALLOWED`；
6. 多个授权 Schema 有同名表时返回
   `SCHEMA_ERROR / SQL_OBJECT_AMBIGUOUS`，要求 SQL 显式限定；
7. 已授权但快照中不存在时返回
   `SCHEMA_ERROR / SQL_OBJECT_UNKNOWN`。

公开错误不区分对象“真实存在但未授权”和“数据库中不存在”，避免枚举未授权
对象。

## 字段存在性与引用提取

在深拷贝 AST 上把已解析基表补成规范 Schema，然后使用 SQLGlot
`qualify()`：

```python
qualify(
    expression_copy,
    dialect="postgres",
    schema=schema_mapping,
    expand_stars=False,
    infer_schema=False,
    validate_qualify_columns=True,
    quote_identifiers=False,
    identify=False,
    sql=None,
)
```

`schema_mapping` 只来自授权快照，按 Schema、表、字段构造；字段类型使用快照的
`formatted_type`，不查询数据库。

SQLGlot qualification 负责：

- 表别名；
- CTE 和派生表输出列；
- JOIN 两侧字段；
- 不限定字段的唯一解析；
- 相关子查询的外层引用；
- 歧义和未知字段。

`OptimizeError` 统一返回
`SCHEMA_ERROR / SQL_COLUMN_INVALID`，公开消息不包含原始错误。

qualification 成功后再次遍历 scope，仅从基表 source 对应的列生成
`schema.table.column` 引用；CTE/派生表外层列不重复记录，内部作用域已经记录
底层基表字段。

## 函数策略

策略版本为 `mvp-v1`。允许逻辑名称：

```text
COUNT SUM AVG MIN MAX
COALESCE NULLIF
LOWER UPPER LENGTH TRIM SUBSTRING
DATE_TRUNC EXTRACT CURRENT_DATE
ROUND ABS CEIL FLOOR
CASE CAST
```

SQLGlot 内建函数通过明确 AST 类型映射到上述逻辑名称，而不是直接信任
`sql_name()`；例如 `exp.TimestampTrunc` 映射为 `DATE_TRUNC`。

规则：

- `exp.Anonymous` 一律拒绝，因此 `pg_sleep`、UDF、文件/网络函数和
  `dblink` 默认拒绝；
- `exp.If` 只允许作为 `exp.Case` 的结构分支，独立 `IF()` 不允许；
- 任何未映射的 `exp.Func` 子类视为未知函数；
- 函数名大小写不敏感；
- 不通过字符串包含或前缀判断放行函数。

拒绝结果为
`PERMISSION_DENIED / SQL_FUNCTION_NOT_ALLOWED`，不在公开消息中返回函数名。

## 结构化错误

| 场景 | ErrorType | code |
|---|---|---|
| 空 SQL、解析失败 | `SYNTAX_ERROR` | `SQL_PARSE_ERROR` |
| 多 statement | `PERMISSION_DENIED` | `SQL_MULTIPLE_STATEMENTS` |
| 非 SELECT、危险节点、锁、INTO | `PERMISSION_DENIED` | `SQL_NOT_READ_ONLY` / `SQL_FORBIDDEN_NODE` |
| wildcard | `PERMISSION_DENIED` | `SQL_WILDCARD_FORBIDDEN` |
| 未授权表 | `PERMISSION_DENIED` | `SQL_OBJECT_NOT_ALLOWED` |
| 同名表歧义、授权对象/字段缺失 | `SCHEMA_ERROR` | `SQL_OBJECT_AMBIGUOUS` / `SQL_OBJECT_UNKNOWN` / `SQL_COLUMN_INVALID` |
| 未批准函数 | `PERMISSION_DENIED` | `SQL_FUNCTION_NOT_ALLOWED` |
| 未知 AST | `PERMISSION_DENIED` | `SQL_UNKNOWN_AST` |
| PostgreSQL 序列化不支持 | `DIALECT_ERROR` | `SQL_DIALECT_ERROR` |
| 快照越过授权范围 | `UNKNOWN` | `SQL_VALIDATION_CONTEXT_INVALID` |

权限和安全问题不可交给 LLM 修复；语法、Schema 和方言错误由后续 Workflow
按主规格路由。本阶段只产生正确的 `ErrorType`，不实现路由。

## 测试设计

### 单元测试

允许：

- 单表、多表 JOIN、子查询和相关 `NOT EXISTS`；
- 最终主体为 SELECT 的 CTE；
- GROUP BY/HAVING、ORDER BY/LIMIT；
- CASE、CAST 和全部函数 allowlist；
- `COUNT(*)`；
- 表别名、CTE 输出列和唯一不限定字段；
- 大小写和带引号标识符的 PostgreSQL 规则。

拒绝：

- parse failure、空 SQL和多 statement；
- DML、DDL、COPY、CALL、DO、SET、RESET；
- 写操作 CTE；
- `SELECT INTO`、`FOR UPDATE`、`FOR SHARE`；
- `SELECT *` 和 `table.*`；
- 未授权、未知、跨 catalog 和同名歧义表；
- 未知、歧义字段；
- `pg_sleep`、文件/网络/dblink、UDF 和独立 `IF()`；
- 未知 AST 和 SQLGlot `Command` 回退；
- 失败消息中的 SQL、对象和函数泄漏。

每个危险 SQL Case 直接调用 validator 并断言失败，不创建 Connector。

### Pagila 集成测试

- 使用第二阶段 Connector 读取每条 Case 的精确授权快照；
- `PG-MVP-001` 至 `PG-MVP-014` 的 `gold_sql` 全部通过；
- `PG-MVP-018` 的修复后 `gold_sql` 通过；
- `PG-MVP-016` DELETE 被拒绝；
- `PG-MVP-017` 多 statement 被拒绝整段；
- 仅授权 `public.film` 时，`SELECT username, email FROM staff` 被拒绝；
- 所有成功结果仅引用 Case 授权表和快照存在字段；
- 第一、第二阶段单元与集成测试继续通过。

Case 文件保持只读和字节不变。本阶段不把 Case 从 `draft` 改为 `verified`，
因为完整 E2E、Workflow 和模型尚未实现。

## 完成标准

- `sqlglot==30.13.0` 已锁定；
- 所有 SQL 必须经过 PostgreSQL parser；
- 多 statement 和所有明确危险语句 fail closed；
- 表授权与字段存在性同时成立；
- CTE、别名、派生表和相关子查询正确解析；
- 仅批准函数可通过；
- 未知 AST/函数默认拒绝；
- 成功返回稳定规范 SQL和规范引用；
- 失败返回正确 `ErrorType` 且不泄露 SQL/对象；
- Pagila 允许与拒绝 Case 通过；
- 第一、第二阶段回归继续通过；
- 三份受保护规格/Case 文件未修改；
- 没有实现 Schema Linking、LLM、Workflow、API 或数据库执行编排；
- 第三阶段编码必须在用户后续明确指令后才能开始。
