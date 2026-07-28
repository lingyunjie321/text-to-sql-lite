# Text-to-SQL 测试与验收规格

> 本文件只定义 MVP P0。Gold SQL 不要求字符串相同；优先比较执行结果、列、重复行、聚合粒度和数值容差。权限和危险 SQL Case 单独统计。

## 1. 测试分层

| 层次 | 目标 | 外部依赖 | P0 |
|---|---|---|---:|
| 单元测试 | State、路由、指纹、错误映射、Comparator | 无 | 是 |
| Schema Linking | Gold 表字段召回、Top-K 和权限过滤 | 固定元数据 | 是 |
| AST/安全 | 单语句、只读、对象、函数和拒绝规则 | SQLGlot | 是 |
| Connector Contract | 元数据、只读、超时、结果和错误统一 | PostgreSQL | 是 |
| Workflow 集成 | 九个节点、计数、终止和恶意修复 | LLM/Connector Stub | 是 |
| Pagila E2E | 问题到真实执行结果 | 固定 Pagila + 模型 | 是 |
| API | 请求、联合响应、错误和 Trace | 启动服务 | 是 |

确定性 Stub 证明 Workflow 和安全行为；真实 Pagila E2E 建立模型质量基线，二者不能互相替代。

## 2. Case 数据结构

Case 使用 UTF-8 JSONL。执行 Case 的 Gold Result 在锁定数据库上运行 `gold_sql` 动态生成，不把固定结果行写进仓库。

```python
from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field


class NumericTolerance(BaseModel):
    absolute: Decimal = Decimal("0")
    relative: Decimal = Decimal("0")


class GoldSQL(BaseModel):
    sql: str
    dialect: str = "postgres"
    expected_ast_features: list[str] = Field(default_factory=list)


class EvaluationCase(BaseModel):
    case_id: str
    status: Literal["draft", "verified"]
    category: Literal[
        "single_table", "multi_join", "aggregation", "time",
        "anti_join", "permission", "dangerous_sql", "reflection",
    ]
    question: str
    datasource_id: str = "pagila"
    dialect: str = "postgres"
    allowed_tables: list[str] = Field(default_factory=list)

    expected_behavior: Literal["EXECUTE", "CLARIFY", "REJECT", "FAIL_INFRA"]
    expected_final_status: FinalStatus
    expected_error_type: ErrorType | None = None

    gold_tables: list[str] = Field(default_factory=list)
    gold_fields: list[str] = Field(default_factory=list)
    gold_join_edges: list[str] = Field(default_factory=list)
    gold_sql: str = ""
    gold_result_source: Literal["execute_gold_sql", "not_applicable"]

    comparison_mode: Literal["exact", "multiset", "keyed", "none"]
    order_sensitive: bool = False
    numeric_tolerances: dict[str, NumericTolerance] = Field(default_factory=dict)

    tags: list[str] = Field(default_factory=list)
    difficulty: Literal["simple", "medium", "complex"]
    fixture: dict[str, object] = Field(default_factory=dict)
```

加载校验：

- `EXECUTE` 必须有 Gold tables、fields、SQL，且 `gold_result_source=execute_gold_sql`。
- `CLARIFY`/`REJECT` 必须零数据库执行，`gold_result_source=not_applicable`。
- `verified` Case 的 Gold SQL 必须已在锁定 Pagila 上执行。
- Case ID 唯一；非法 Case 不进入任何指标分母。
- 安全、权限和基础设施 Case 不进入允许查询的可执行率分母。

## 3. Gold Schema / Fields / SQL / Result

### Gold Schema

- `gold_tables` 包含所有必需表和中间表。
- `gold_join_edges` 使用 `table.column=table.column`。
- 多条等价 JOIN Path 可由多个 Case 或 Fixture 表达。
- Schema 版本变化后，原 Gold 自动失效。

### Gold Fields

- 必须标出 select、filter、join、group、aggregate 和时间字段。
- `SELECT *` 不算字段召回。
- 结果列相同但过滤或 JOIN 字段错误，仍判失败。

### Gold SQL

- 是参考实现，不做字符串相等比较。
- 必须使用目标方言并通过与预测 SQL 相同的安全校验。
- 不得进入训练集、Few-shot 或 Prompt。
- 数据快照变化后重新执行和审阅。

### Gold Result

- `execute_gold_sql` 与预测 SQL 必须在同一事务可见性和数据快照下执行。
- 比较列数量、规范化类型、行、重复数、顺序、NULL、粒度和数值。
- 合法空结果是成功结果。

## 4. Schema Linking 测试

P0 场景：

- 直接表名和字段名命中。
- 注释或业务别名命中。
- 多表查询召回所有必需表、JOIN 键和中间表。
- 同名字段不会导向错误表。
- 未授权表在召回前过滤。
- Schema 版本改变后旧索引失效。
- Top-K 固定为 10，候选不会无界扩大。
- 字段不存在的修复 Case 能重新 Linking。

指标：

- Table Recall@10。
- Field Recall@10。
- Precision@10 和平均候选表数。
- 未授权对象命中数必须为 0。
- 最终 Gold Result 是否通过。

## 5. AST 与安全测试

### 允许

- 单表和多表 SELECT。
- 最终主体为 SELECT 的 CTE。
- JOIN、子查询、聚合、GROUP BY/HAVING、ORDER BY/LIMIT、CASE、CAST。
- 主规格函数 allowlist 中的函数。

### 必须拒绝

- SQLGlot parse failure 和未知 AST。
- 多 statement。
- INSERT、UPDATE、DELETE、MERGE。
- CREATE、ALTER、DROP、TRUNCATE。
- COPY、CALL、DO、SET、RESET。
- CTE 内写操作。
- `SELECT INTO`、`FOR UPDATE`、`FOR SHARE`。
- `SELECT *`、未授权表和未审批 UDF。
- `pg_sleep`、文件、网络、dblink 和系统执行能力。

每个安全 Case 必须满足：

- Connector 执行调用次数为 0。
- 不进入 Reflect 绕过安全规则。
- `repair_count=0`。
- 返回 `REJECTED_SECURITY` 和脱敏错误。
- 数据库只读账号作为第二道防线。

## 6. Connector Contract

PostgreSQL Connector 必测：

- 连接成功、认证失败、连接拒绝和池超时。
- 只在授权范围读取表、字段、PK/FK、unique constraint/index 和注释。
- 普通 SELECT、CTE、聚合、空结果。
- NULL、Decimal、日期、时间戳、时区和 JSON 规范化。
- 1000 行上限与 `truncated`。
- 30 秒 statement timeout、取消和连接回收/废弃。
- 写操作即使绕过上层也被只读账号/事务拒绝。
- SQLSTATE 稳定映射。
- 瞬时连接失败只重试相同调用，不改变 SQL，不增加修复计数。

超时后必须证明数据库查询已取消，或连接已废弃；只让 HTTP 超时不算通过。

## 7. 结果 Comparator

比较顺序：

1. 规范化列名和类型。
2. 规范化 NULL、Decimal、日期、时间戳、时区和 JSON。
3. `order_sensitive=true` 时逐行比较。
4. `multiset` 忽略行序但保留重复次数。
5. `keyed` 按唯一键对齐；重复键失败。
6. 应用每列数值容差。
7. 检查结果 grain，防止一对多 JOIN 重复聚合。

默认规则：

| 类型 | 规则 |
|---|---|
| 整数、ID、布尔、枚举 | 精确相等 |
| Decimal/金额 | 默认精确；Case 可声明 Decimal 容差 |
| 浮点、平均值、比例 | Case 必须显式声明容差 |
| 文本 | 默认大小写和尾空格敏感 |
| 日期 | 精确相等 |
| 时间戳 | 转为 Case 时区和精度后比较 |
| 无 ORDER BY | multiset，不依赖物理顺序 |

Comparator 自测必须覆盖重复数不同、NULL 与空字符串、容差边界、时区等价、缺列、多列和 grain 不同但总值偶然一致。

## 8. 反思、错误路由和循环终止

P0 断言：

- attempt 0 是初始 SQL；最多接受 attempt 1、2、3。
- 新修复 SQL 指纹不同才增加 `repair_count`。
- 语法、Schema、方言错误分别选择主规格规定的策略。
- 权限、安全、连接、超时和资源风险不调用 LLM 修 SQL。
- 每个修复 SQL 重新执行完整 AST 和安全校验。
- 重复 SQL 和 A→B→A 不重复执行。
- 第三个修复失败后为 `FAILED_REPAIR_EXHAUSTED`。
- Workflow 在 32 步内终止。

### 10 个 MVP Bad Case

| ID | 场景 | 预期 |
|---|---|---|
| BC-01 | Top-K 噪声 | Gold 表仍在 Top-10，候选不扩到固定 30 |
| BC-02 | 一对多 JOIN 重复聚合 | SQL 可执行但 Comparator 因 grain/重复失败 |
| BC-03 | 字段不存在 | `SCHEMA_ERROR` → 重新 Linking → 新 SQL |
| BC-04 | 方言函数错误 | `DIALECT_ERROR` → PostgreSQL 重生成 |
| BC-05 | 重复 SQL | 不重复执行，`FAILED_DUPLICATE_LOOP` |
| BC-06 | 权限错误 | 零执行、零修复、`REJECTED_SECURITY` |
| BC-07 | 连接错误 | 同调用有限重试，不调用 LLM |
| BC-08 | 多 statement | 拒绝整段，不能只执行第一条 |
| BC-09 | 合法空结果 | 成功且 `rows=[]`，不得进入修复 |
| BC-10 | 超时取消 | `FAILED_TIMEOUT`，查询已取消或连接废弃 |

## 9. API 测试

Endpoint：`POST /api/v1/text-to-sql`。

请求测试：

- 空问题、纯空白、超过 2000 字符。
- 未知 datasource 和客户端扩大 Schema 范围。
- 非可信客户端请求 debug。
- 总请求 timeout 120 秒。

响应测试：

- 覆盖全部 `FinalStatus`。
- `request_id`、`trace_id` 存在，终态唯一。
- 成功有 SQL 和结果；合法空结果允许空行。
- 澄清无执行结果。
- 权限失败不泄露未授权对象。
- 失败无原始驱动堆栈。
- OpenAPI 与 Pydantic Schema 一致。
- Trace sink 失败不改写已完成业务结果。

## 10. Pagila MVP Case

Case 文件：`evaluation/cases/pagila_mvp.jsonl`

Schema 字段依据 [Pagila 官方仓库](https://github.com/devrimgunduz/pagila)当前 `pagila-schema.sql` 编写。由于具体 commit 尚未锁定，所有 Case 标记为 `draft`，不能作为已经验证的 Gold。

| 分类 | 数量 |
|---|---:|
| 单表 | 5 |
| 多表 JOIN | 4 |
| 聚合 | 3 |
| 时间 | 1 |
| 反连接/子查询 | 1 |
| 权限拒绝 | 1 |
| 危险 SQL | 2 |
| 反思修复 | 1 |
| 合计 | 18 |

加载与执行：

1. 锁定 Pagila commit、PostgreSQL 版本和数据校验和。
2. 校验 JSONL Schema、ID 唯一和分类数量。
3. 对 `EXECUTE` Case 先执行 `gold_sql` 生成临时 Gold Result。
4. 运行 Text-to-SQL，再按 Case comparator 比较。
5. Gold SQL 成功、人工审阅通过后把 Case 改为 `verified`。
6. 权限和危险 SQL Case 只计安全门禁，不进入允许查询可执行率。

## 11. MVP 验收标准

### 必须 100% 通过

- State、九节点路由、修复计数和 Workflow 终止单元测试。
- SQLGlot AST 和全部 P0 安全拒绝 Case。
- PostgreSQL Connector Contract。
- 权限/安全零数据库执行。
- 30 秒 statement timeout、1000 行上限、三次修复和 32 步上限。
- 重复 SQL 不重复执行。
- 连接错误不进入 LLM；权限错误零修复。
- API Request/Response Contract。
- Comparator 自测。

### Pagila 门禁

- Pagila commit、PostgreSQL 版本和数据校验和固定。
- 18 条 Case 从 `draft` 转为 `verified`。
- 所有允许执行 Case 命中必需表字段、通过安全门、真实执行并通过 Gold Result。
- 权限、危险 SQL 和澄清 Case 行为符合预期。
- 测试问题和 Gold SQL 不进入 Prompt、Few-shot 或训练集。

真实模型发布阈值在模型确定并跑出首个 baseline 后制定；不得使用原项目 98.82% 作为新项目门槛。只有 Mock、没有真实 PostgreSQL 闭环，不通过 MVP 验收。
