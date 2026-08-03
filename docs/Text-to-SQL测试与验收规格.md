# Text-to-SQL 测试与验收规格

> 本文件定义 MVP P0 回归以及增强版、生产版阶段 0～5 的分层验收。
> Gold SQL 不要求字符串相同；优先比较执行结果、列、重复行、聚合粒度和数值
> 容差。权限和危险 SQL Case 单独统计，安全门禁在所有阶段保持 100%。

> 本文中原有的阶段 0～5 统一称为“增强能力 Stage”。当前
> “本地工具阶段 5”当前只交付模型设置前端闭环，其独立门禁见第 15.1 节；
> 原业务知识/Few-shot 门禁仍见第 16 节且含义不变。

## 1. 测试分层

| 层次 | 目标 | 外部依赖 | P0 |
|---|---|---|---:|
| 单元测试 | State、路由、指纹、错误映射、Comparator | 无 | 是 |
| Schema Linking | Gold 表字段召回、Top-K 和权限过滤 | 固定元数据 | 是 |
| AST/安全 | 单语句、只读、对象、函数和拒绝规则 | SQLGlot | 是 |
| Connector Contract | 元数据、只读、超时、结果和错误统一 | PostgreSQL | 是 |
| Workflow 集成 | 当前十种节点、计数、终止和恶意修复 | LLM/Connector Stub | 是 |
| Pagila E2E | 问题到真实执行结果 | 固定 Pagila + 模型 | 是 |
| API | 请求、联合响应、错误和 Trace | 启动服务 | 是 |
| 本地 Profile | Profile 校验、SQLite、内存凭据、CRUD 和 ID 查询 | 临时目录/静态 runtime | 本地工具阶段 2 |
| 动态数据源 | 连接测试、metadata、allowlist、RuntimeRegistry 和 ID 查询 | PostgreSQL/MySQL | 本地工具阶段 3 |
| 增强检索 | 复杂度、动态 K、双路召回、RRF、Rerank、裁剪 | 固定语料/Embedding Stub | 阶段 1 |
| 业务知识 | 术语、指标、Few-shot、RAG、审批与撤销 | 固定知识库 | 阶段 2 |
| 会话恢复 | Session、Checkpoint、Compaction、Memory 隔离 | 持久化测试存储 | 阶段 3 |
| 多数据库 | Connector、方言与跨源 QueryPlan | MySQL/StarRocks | 阶段 4 |
| 生产治理 | 缓存、导出、遥测、配额、部署与保留 | 生产等价环境 | 阶段 5 |

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
- 不得进入训练集、Few-shot、RAG、检索索引或生成 Prompt。Gold question
  只允许作为当前被测请求的 user payload，不得作为 system 指令、静态示例、
  调参语料或可复用知识。
- 数据快照变化后重新执行和审阅。

### Gold Result

- `execute_gold_sql` 与预测 SQL 必须在同一事务可见性和数据快照下执行。
- 比较列数量、规范化类型、行、重复数、顺序、NULL、粒度和数值。
- 合法空结果是成功结果。

## 4. Schema Linking 与复杂度路由测试

MVP P0 回归：

- 直接表名和字段名命中。
- 注释或业务别名命中。
- 多表查询召回所有必需表、JOIN 键和中间表。
- 同名字段不会导向错误表。
- 未授权表在召回前过滤。
- Schema 版本改变后旧索引失效。
- 以显式预算 10 运行时保持原 MVP 排名和候选有界行为。
- 字段不存在的修复 Case 能重新 Linking。

增强阶段 1：

- 授权内探测固定上限为 20，探测结果与最终物化结果使用同一
  `schema_version`。
- `ComplexityRouteNode` 是独立节点，探测后执行，零 Connector、零 Embedding、
  零 Reranker、零 LLM 和零数据库执行。
- 路由只消费规范化问题、正分候选、相关 JOIN Path、修复历史及版本化策略；
  不读取 `EvaluationCase.difficulty` 或其他 Gold 字段。
- `simple/medium/complex` 分别物化最多 5/10/20 张表；客户端不能声明复杂度、
  Top-K、模型或上下文预算。
- Schema 修复重新读取授权快照、重新探测和决策；语法/方言修复沿用当前决策。
- 相同问题、授权快照、修复历史和策略版本必须得到相同等级、K、理由码和顺序。
- 任一 K 下，FK 中间表计入预算，候选、字段和 JOIN Path 都不越过授权范围。

检索指标：

- Table Recall@5/10/20。
- Field Recall@5/10/20。
- Precision@5/10/20 和按复杂度分桶的平均候选表数。
- BM25/Embedding 各路召回、RRF 后召回、Rerank 前后变化。
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
| 文本 | 先执行 `rstrip()`；随后大小写、前导/中间空格精确比较。PostgreSQL `text`、`varchar`、`bpchar` 视为同一字符串类型族 |
| 日期 | 精确相等 |
| 时间戳 | 转为 Case 时区和精度后比较 |
| 无 ORDER BY | multiset，不依赖物理顺序 |

其余值规范化、类型、列、重复次数和 grain 规则不变。Comparator 自测必须覆盖重复数不同、NULL 与空字符串、容差边界、时区等价、缺列、多列和 grain 不同但总值偶然一致。

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
- 正常检索周期按
  `SchemaLinking(probe) → ComplexityRoute → SchemaLinking(materialize)`
  执行；节点类型总数为 10。
- `ComplexityRouteNode` 的异常只允许进入脱敏内部失败，不能跳过 Linking、
  Validate 或 Execute 边界。

### 10 个 MVP Bad Case

| ID | 场景 | 预期 |
|---|---|---|
| BC-01 | Top-K 噪声 | 候选不超过路由决定的 5/10/20，必需表仍在对应预算内 |
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
- 本地 Profile 模式接受 `datasource_id + model_profile_id`，不携带
  API Key、数据库密码、Host、Base URL 或 allowlist。
- Profile 模式与 `model_overrides`/`datasource_override` 混用返回
  422，且 Workflow、Connector 和 Provider 调用均为 0。
- 未提供 `model_profile_id` 的旧请求、Override 成功和拒绝 Case 保持
  原有行为。

响应测试：

- 覆盖全部 `FinalStatus`。
- `request_id`、`trace_id` 存在，终态唯一。
- 成功有 SQL 和结果；合法空结果允许空行。
- 澄清无执行结果。
- 权限失败不泄露未授权对象。
- 失败无原始驱动堆栈。
- OpenAPI 与 Pydantic Schema 一致。
- Trace sink 失败不改写已完成业务结果。
- Profile 不存在使用固定 404 错误；runtime 未绑定使用固定 409 错误；
  Store 不可用使用脱敏 503 错误。阶段 2 的静态 runtime 已持有自身凭据，
  Profile 内存凭据缺失只显示状态，不重复阻断查询。
- 上述错误响应、日志和异常不回显 Profile 输入中的 Host、URL、
  用户名、密码、API Key 或完整 DSN。

## 10. Pagila MVP Case

Case 文件：`evaluation/cases/pagila_mvp.jsonl`

Schema 字段依据已锁定的 Pagila 3.1.0、commit
`fef9675714cfba1756df4719b5e36075a7ddf90e` 的 `pagila-schema.sql` 编写。
当前主 Gold 状态为 `16 verified / 2 draft`；该状态只记录逐 Case 审核结果，不能
把仍为 draft 的 Case 计入通过，也不代表整体发布资格已经通过。

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

- State、十种节点路由、两遍 Linking、修复计数和 Workflow 终止单元测试。
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
- Gold question 只作为当前请求的 user payload；Gold SQL、fields、result、
  label、fixture 和失败原因不进入 Prompt、Few-shot、RAG、检索索引、训练或
  调参集。

真实模型发布阈值在模型确定并跑出首个 baseline 后制定；不得使用原项目 98.82% 作为新项目门槛。只有 Mock、没有真实 PostgreSQL 闭环，不通过 MVP 验收。

## 12. 阶段完成状态与统一门禁

每个能力独立记录以下状态：

| 状态 | 必要证据 |
|---|---|
| `functional_complete` | 明确契约、真实可达实现、单元测试、错误/超时/取消/降级、配置和本地 Trace |
| `integration_complete` | 组件贯通 Workflow/API，必要契约/集成/安全/E2E 通过，权限和版本隔离有证据 |
| `real_environment_validated` | 在冻结的真实模型、数据库、存储或生产等价环境运行，版本与结果证据完整 |

能力只有同时具备迁移/兼容说明、实际测试输出和文档一致性才可获得对应状态。
替身、不可达代码、空接口、未来配置项或单次人工演示都不能单独证明完成。

所有阶段的绝对安全门禁：

- P0 权限和危险 SQL 测试 100% 通过；
- 未授权候选、索引文档、Prompt 对象、缓存命中和跨会话读取均为 0；
- 安全/权限拒绝后的数据库执行、模型修复和跨模型回退均为 0；
- 所有来自模型、Few-shot、RAG、Memory、缓存、Checkpoint 和跨源计划的 SQL
  都重新经过当前身份下的权限、AST、函数和执行边界；
- 版本证据不完整的运行不进入任何质量或发布分母。

## 13. 本地工具阶段 2：Local Profile 门禁

### Profile 模型与存储

- `ModelProfile` 和 `DatasourceProfile` 严格禁止额外字段，自身
  `repr`/JSON/OpenAPI 不包含 API Key、密码或 DSN。
- ID 拒绝空白、控制字符、换行、路径式输入和日志注入；端口、
  endpoint、host 和 allowlist 边界有独立反例。
- SQLite 使用 `user_version=1`、参数化 SQL 和显式事务；未知版本、
  损坏行、坏 JSON、锁超时和 I/O 失败均 fail closed。
- 创建、读取、替换、删除和确定性列表通过；重复 ID 和不存在对象
  返回稳定服务错误。

### 凭据安全与生命周期

- API Key 和数据库密码只保存在当前单进程的 Credential Store。
- 重新打开 SQLite 后非敏感 Profile 保留，新 Credential Store 全部为
  `missing`或 `not_applicable`。
- 更新时“未提供 Secret”表示保留，“显式 `null`”表示清除；
  endpoint/主机/用户等身份字段变化且未提供新 Secret 时自动清除。
- 删除 Profile 和应用正常退出会清除相应内存引用。Python 字符串
  不宣称可物理零化。
- 使用哨兵 Secret 扫描 `config.db`、journal/WAL/SHM、API 响应、
  OpenAPI、异常、`caplog` 和 Trace，任一位置都不得命中。

### API 与运行时边界

- 模型和数据源 CRUD 的 Create/List/Get/Replace/Delete 全部可达，写入
  可接收 Secret，响应只返回凭据状态。
- CRUD 不调用 ConnectorFactory、ModelProviderFactory 或 Workflow runner。
- Profile-ID 查询只使用 Bootstrap 显式绑定的现有静态 Context/模型
  路由；未绑定的 Profile 返回 409，不得暗中使用默认资源。
- Profile 模式下进入 Workflow 的 datasource ID 必须与解析后 Context 一致。
- Override 字段在 OpenAPI 中标记 deprecated，旧请求、成功、拒绝和
  脱敏行为通过原有回归。
- 本阶段不建立动态 Connector/Provider，不修改 Embedding 必需行为，
  不修改 Workflow、Gold 或 Comparator。

### 阶段通过线

- 新增 Profile 测试全部通过，不新增无理由 skip。
- unit/security 总体分支覆盖率不低于 83%，原有 unit、security、
  Pagila integration、Python 全量和前端基线不回归。
- Gold 内容和 `16 verified / 2 draft` 保持不变；Profile ID 不写入
  Pagila Gold Case。

## 14. 本地工具阶段 3：动态数据库连接门禁

### Metadata 与授权隔离

- `POST /api/v1/local/datasources/test` 使用临时 Connector，完成连接检查与结构
  发现后必定关闭，不保存 Profile、密码或运行时。
- `GET /api/v1/local/datasources/{id}/metadata` 返回当前账号可发现的全部非系统
  Schema、表/视图、字段、类型、nullable、主键和外键，不返回样例值、视图定义、
  存储过程、Trigger、凭据或驱动错误。
- metadata 发现范围不等于 AI 授权范围；接口不得修改 allowlist。只有显式 PUT
  且在线验证成功的新对象才进入授权。
- Workflow、Schema Linking、Prompt、Validator 和 execute 只接收 Profile 的
  非空 allowlist。空、失效、不匹配或请求扩大范围全部 fail closed，不回退到
  metadata 全量或默认 `.env` 数据源。
- PostgreSQL/MySQL 系统 Schema 排除正确，结果确定性排序；catalog 与详细结构
  读取共享 30 秒端到端预算；500 个关系、10,000 个字段、5,000 个外键上限和
  对象边界截断均有测试。

### 动态运行时与错误边界

- `RuntimeRegistry` 按 datasource ID 懒创建和复用 runtime；首次并发只创建一次，
  失败不缓存且允许重试。
- 更新完成后 Registry 拒绝先前读取的旧 Profile 重建运行时；删除完成后密码已
  清除且旧运行时已移除，配置变化不存在可长期复用的旧缓存。
- 数据源 create、PUT 和 DELETE 写操作串行化；并发 PUT 后 Store、凭据和 Registry
  身份必须一致指向最后完成的更新。
- Connector 构造后、`open()` 前即进入资源管理；创建失败、Profile 更新/删除和
  应用退出均关闭旧资源，单个 close 失败不阻止其他资源关闭。
- Profile 不存在、内存密码缺失、连接失败、allowlist 无效、metadata 超时和
  metadata 不可用使用不同稳定错误码，且绝不回退到默认 Context。
- 公开响应、OpenAPI、日志、Trace 和异常不包含密码、API Key、完整 DSN、Host、
  用户名、驱动错误、原始 SQL 或数据库文件路径。

### PostgreSQL/MySQL 真实门禁

- 原有 PostgreSQL/Pagila 91 项保持通过，事务只读、超时、1000 行上限和行为不变。
- MySQL 固定为官方 8.4 镜像与官方 Sakila 1.5 归档；镜像 digest、归档 SHA-256、
  显式 Sakila 版本和两份 SQL 文件 SHA-256 可重复校验。
- MySQL Connector 真实验证连接、23 个非系统表/视图、字段、主键、外键、多表
  metadata、NULL/Decimal、超时、1000 行截断和写拒绝。
- MySQL API E2E 使用临时 Profile Store、进程内密码和固定模型/Embedding 替身；
  请求只含两个 Profile ID，最终 SQL 经 MySQL SQLGlot 校验并在 Sakila 真实执行。
- MySQL 使用 `START TRANSACTION READ ONLY`，启动不确定或回滚失败时废弃连接；
  Docker 应用账号仅有 Sakila `SELECT` / `SHOW VIEW` 权限。
- MySQL 反引号 SQL 的纯格式变化产生相同指纹，继续受既有修复次数和循环上限
  约束。
- 不新增无理由 skip；unit+security 分支覆盖率不低于 83%；Gold 内容和
  `16 verified / 2 draft` 状态不变。

## 15. 本地工具阶段 4：动态模型与离线模式门禁

### 动态 Provider 与模型测试

- `POST /api/v1/local/models/test` 使用临时 Provider 验证项目结构化生成契约；
  完成后不保存 Profile、Key、运行时、模型响应、Prompt、Trace 或历史。
- 生成测试失败返回稳定脱敏错误；生成成功但可选 Embedding 失败时明确返回
  `embedding=unavailable`，并说明 BM25-only 仍可用，不把增强检索失败伪装成
  整体生成模型失败。
- 单个动态生成 Provider 精确映射 simple、standard、complex 三条主路由；动态
  Profile 不启用 fallback，请求不能指定 Route 或 Provider。
- `ModelRuntimeRegistry` 按 Model Profile ID 并发单建、复用和失败重试；endpoint、
  model、Embedding 配置或任一 Key 变化后旧运行时不得继续使用。
- Profile Resolver 将已解析的数据源运行时与模型运行时显式组合；任一 Profile、
  凭据或运行时失败都在 Workflow 前拒绝，不回退默认 `.env` 资源。

### Embedding 可选化与安全降级

- `embedding_base_url`、`embedding_model`、`embedding_dimension` 必须全有或全无；
  未配置时不创建 RetrievalRuntime，Schema Linking 直接走 BM25-only。
- 配置 Embedding 时继续先授权过滤再建文档、索引和打分；索引键保持数据源、授权
  摘要、Schema/语义、Embedding 模型与维数、策略版本隔离。
- 超时、连接、限流、无效响应和维数不匹配只在同授权、同 Schema 版本且 BM25
  有安全候选时按既有矩阵降级；不得扩大权限、使用陈旧索引或隐藏降级。
- 静态生成模型和 Embedding 允许完全缺省；无静态配置时应用可启动并等待 Profile，
  任一静态配置半配置时启动失败。

### 安全与通过线

- API Key 可为空以支持无鉴权 loopback 服务；配置 Key 时只存在进程内存，未配置
  时不发送 Authorization Header。非 loopback HTTP、URL 凭据、query、fragment
  和重定向继续拒绝。
- SQLite 迁移只增加非敏感 Embedding 维数字段；Key 不得命中数据库、WAL/SHM、
  OpenAPI、响应、异常、日志或 Trace。
- 无静态 LLM/Embedding 的 BM25-only Profile 查询、动态 PostgreSQL/Pagila 和
  MySQL/Sakila 链路可达；旧普通请求、Override 和静态多模型路由保持兼容。
- 不新增无理由 skip；unit+security 分支覆盖率不低于 83%；Workflow 图、节点、
  State、Comparator、Gold 内容与 `16 verified / 2 draft` 状态不变。

## 15.1 本地工具阶段 5：模型设置前端闭环门禁

- 浏览器只通过 BFF 调用模型 Profile API；BFF 不接受上游 URL/Header。
- ModelProfile CRUD 和 `/test` 全部可达并保留脱敏 HTTP 语义。
- API Key 只存在写请求和组件瞬时状态，Profile 响应、localStorage 和历史均不包含。
- 编辑时省略 Key 表示保留，`null` 表示清除。
- 当前选择只保存合法 `model_profile_id`，失效或删除后清理。
- 旧 `text-to-sql-model-config` 被删除且不上传。
- 普通设置 UI 不显示多路模型和 fallback。

## 16. 增强能力 Stage 1：检索与路由增强门禁

### 功能完成

- `ComplexityRouteNode`、动态 5/10/20、Embedding、BM25+Embedding 双路、
  RRF、可解释 Rerank、模型路由和上下文裁剪均有真实可达实现。
- 路由、Embedding 索引、文档构建、融合、Rerank、模型表和裁剪策略均有
  独立版本。
- RRF 使用 `k=60`，只融合 rank；重复候选去重，规范对象 ID 稳定 tie-break。
- Rerank 只使用白名单理由码和授权内特征，不使用 Gold 或未批准知识。
- Embedding、Rerank 和模型调用分别覆盖成功、格式错误、超时、取消、限流、
  不可用及预定义降级。

### 集成完成

- 正常路径包含探测 Linking、显式 ComplexityRoute、同版本物化 Linking；
  Schema 修复重新执行三步，语法/方言修复不得增加无关检索。
- 两路检索都证明“先授权过滤，后建文档/索引/打分”；权限范围、Schema、
  语义、Embedding 模型或策略变化会使旧索引拒绝或重建。
- Trace 至少包含复杂度、实际 K、理由码、路由策略版本、各通道版本/数量/耗时、
  RRF 摘要、Rerank 理由、裁剪前后计数、模型路由与降级。
- 独立非 Gold development 集只用于实现与调参；独立 calibration holdout
  冻结候选配置后不得继续调参。
- 冻结 holdout 上，组合方案的 Table/Field Recall@K 不低于冻结 BM25 基线，
  且至少一个主要召回指标提升；安全绝对门禁不得回归。

### 真实环境验证

- 固定真实 Embedding 模型、维数、endpoint、索引输入摘要、依赖版本和超时。
- 至少两个真实生成模型按路由运行；只验证明确批准的相同数据处理边界回退。
- 使用真实 Pagila 运行新的冻结 baseline；Stage 10 历史报告只能作为回归参照。
- 18 条 Pagila Gold 仅在配置和代码冻结后运行；不得按失败 Case 修改策略或
  重复抽样择优。

## 16. 增强能力 Stage 2：业务知识与 Few-shot 门禁

- 术语和指标记录名称、定义、公式、粒度、过滤条件、时间口径、适用数据源、
  所有者、审核状态和版本。
- 参考 SQL 在当前 Connector 上只读执行，通过当前 Validator，结果已对账且
  人工批准后，才能成为 Few-shot 或长期知识。
- 新增、更新、失效、撤销和回滚都有审计事件；撤销后旧知识不得被检索、缓存或
  Session 恢复继续使用。
- Few-shot/RAG 检索先执行身份、数据源和知识 ACL；Prompt 明确区分不可信知识
  数据与系统规则。
- 功能完成可使用确定性知识库；集成完成必须贯通审核—检索—生成—重新校验；
  真实环境验证必须使用真实批准样本完成对账和撤销演练。

## 17. 增强能力 Stage 3：Session、Checkpoint 与 Memory 门禁

- API 使用服务端或可信认证绑定的 `session_id`，请求正文不能冒充其他身份、
  租户或项目。
- Checkpoint 只保存结构化状态、版本和必要摘要，不保存无上限原始聊天。
- 澄清恢复和进程重启恢复都重新校验身份、权限、数据源、Schema、知识、
  模型/策略版本；任何失配按契约重检索、澄清或拒绝。
- 任务级、会话级、项目级 Memory 使用不同命名空间和 ACL；跨范围读写测试
  必须为 0。
- 恢复不能重复执行已经完成的 SQL；取消、并发更新、过期、损坏和迁移失败均有
  确定终态。
- 真实环境验证要求在持久化存储上完成进程重启、并发 Session、权限撤销和
  Schema/知识升级演练。

## 18. 增强能力 Stage 4：多数据库和跨数据源门禁

- Connector Contract 明确元数据、只读执行、超时、取消、分页能力、错误、
  方言和 capability；Dialect Profile 明确引用、函数、类型、日期/时区、
  NULL、整数除法、窗口 frame 和引擎专用聚合。
- MySQL 与 StarRocks 分别有真实数据库契约和方言专项测试；SQLGlot parse
  只能作为单元证据。
- 跨源 QueryPlan 显式列出数据源、子查询、依赖、下推、行数/内存预算和合并
  算子；每个子查询在目标数据源的当前权限下重新校验。
- 取消传播、部分失败、超时、结果过大、类型不兼容和重复/NULL 语义均有测试。
- 真实环境验证要求固定 MySQL/StarRocks 版本、字符集、时区和数据摘要，并
  运行跨源 E2E。

## 19. 增强能力 Stage 5：缓存、导出和生产治理门禁

- Schema、Few-shot 和结果缓存键绑定身份/租户、数据源、权限摘要、Schema、
  知识、模型/策略和结果版本；跨范围命中必须为 0。
- 失效、撤销、TTL、并发重建、原子替换和跨实例传播有可重复测试。
- 分页令牌、异步导出和下载都不可伪造、可过期、可取消、可审计；导出时重新
  校验当前权限。
- 指标、Trace、日志和审计使用统一事件契约；Dashboard 与告警有规则测试和
  告警演练。
- 用户/可信 tenant/数据源三级限流、熔断、并发控制、队列、资源组和容量预算
  有负载与故障注入证据。
- Secret 轮换、部署、升级、回滚、备份恢复和数据保留/删除都有生产等价演练；
  缺少演练不得标记 `real_environment_validated`。

## 20. Gold、非 Gold 与正式发布边界

| 数据集合 | 允许用途 | 禁止用途 |
|---|---|---|
| 非 Gold development | 实现、调试、选择初始阈值和解释规则 | 复制或可逆改写 Pagila Gold 内容 |
| 非 Gold calibration holdout | 冻结一个候选配置和质量/资源基线 | 冻结后继续改权重、Prompt、模型路由 |
| Pagila 18 条 Gold | 代码、配置和环境冻结后的最终验收与独立审核 | 训练、Few-shot、RAG、索引、权重选择、按 Case 修补、重复抽样择优 |

Gold question 作为当前 E2E 请求进入 user payload 是允许且必要的；除此之外，
Gold question、SQL、tables、fields、join、result、label、fixture 和失败原因
都不得进入 system prompt、静态示例、检索/知识索引、训练或调参记录。
