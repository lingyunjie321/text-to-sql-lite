# MVP 编码入口

> 后续 Codex 开发优先读取本页，再按需进入详细章节。MVP 基线是
> PostgreSQL + Pagila 上安全、真实、可评测的 Text-to-SQL 最小闭环；
> “补充实现”中的增强版与生产版能力同样属于最终交付必做范围，但必须按
> 阶段 0～5 形成可独立验收的纵向闭环。

## 必须实现

- PostgreSQL 单数据源和 Pagila 固定快照。
- 表、字段、PK/FK、注释等元数据读取。
- 固定 Top-K=10 的基础 Schema Linking。
- 单模型 SQL 生成。
- SQLGlot PostgreSQL AST、单语句、只读、对象与函数策略校验。
- 真实数据库只读执行，30 秒超时，最多返回 1000 行。
- 结构化错误路由，初始 SQL 后最多三次不同修复。
- SQL 指纹去重和 Workflow 最大步骤终止。
- FastAPI `POST /api/v1/text-to-sql`。
- Trace、Token、节点耗时和 Pagila 离线评测。

## 补充实现（最终交付必做）

- 复杂度路由、动态 Top-K、多模型路由。
- Embedding、RRF、Rerank、动态 Few-shot 和业务 RAG。
- 多轮 Session、Checkpoint 恢复和长期 Memory。
- MySQL、StarRocks、多方言和跨数据源查询。
- 缓存、导出、完整生产监控和容量治理。

阶段顺序固定为：

0. 规格和验收基线；
1. 检索与路由增强；
2. 业务知识与动态 Few-shot；
3. Session、Checkpoint 与 Memory；
4. 多数据库、多方言与跨数据源；
5. 缓存、导出和生产治理。

安全、授权、版本隔离、Trace、指标和测试从每个阶段同步实现，不留到阶段 5
补做。每项能力分别记录 `functional_complete`、`integration_complete` 和
`real_environment_validated`；确定性替身通过不能冒充真实环境验证。

## 暂不实现

- 多租户、列级/行级权限、Gateway、MCP、Celery。

阶段 5 的租户级运营配额只使用可信身份注入的 `tenant_id` 作为限流和审计键，
不等价于完整多租户数据模型、租户自助管理或列级/行级 RBAC。

## 当前 Workflow 目标

```text
RequestPreprocess
→ PermissionResolve
→ SchemaLinking（授权内探测，K=20）
→ ComplexityRoute
→ SchemaLinking（同版本物化，K=5/10/20）
→ GenerateSQL
→ ValidateSQL
→ ExecuteSQL
→ Finalize

Schema 错误       → ReflectSQL → SchemaLinking（重新探测与决策）
语法/方言错误     → ReflectSQL → GenerateSQL
语义不唯一       → Clarification → Finalize
权限/安全/超时   → Finalize
```

MVP Stage 8 的历史基线只有九个节点。增强阶段 1 增加显式
`ComplexityRouteNode`，当前目标共有十种业务节点；同一个
`SchemaLinkingNode` 在正常检索周期内执行“探测”和“物化”两次：

1. `RequestPreprocessNode`
2. `PermissionResolveNode`
3. `SchemaLinkingNode`
4. `ComplexityRouteNode`
5. `GenerateSQLNode`
6. `ValidateSQLNode`
7. `ExecuteSQLNode`
8. `ReflectSQLNode`
9. `ClarificationNode`
10. `FinalizeNode`

## 核心数据结构

`SQLTaskState` 只保存请求、授权范围、Schema 候选、版本化复杂度决策、
SQL attempt、校验/执行结果、错误、修复计数和观测数据。完整字段见第 4 节。

## 安全硬约束

- 只允许单条 `SELECT` 或最终主体为 `SELECT` 的受控 CTE。
- 所有 SQL 必须经过 SQLGlot；解析失败一律拒绝。
- 拒绝 DML、DDL、COPY、CALL、DO、SET、多 statement、`SELECT INTO` 和锁定语句。
- 只允许授权 Schema/表及批准函数；未审批 UDF 默认拒绝。
- 数据库使用只读账号和只读事务；Prompt 不能替代安全校验。
- 权限、安全、连接、超时和资源风险不得交给模型盲修。

## 验收入口

- 测试规格：`docs/Text-to-SQL测试与验收规格.md`
- Pagila Case：`evaluation/cases/pagila_mvp.jsonl`
- Gold SQL 不做字符串匹配；重点比较执行结果、列、重复行、粒度和数值容差。
- 权限和危险 SQL Case 单独统计，不进入允许查询的可执行率分母。

## 开发顺序

1. Pagila 与 PostgreSQL Connector
2. 元数据读取
3. SQLGlot 安全校验
4. Schema Linking
5. SQL 生成
6. 真实执行
7. 反思修复
8. LangGraph 串联
9. FastAPI
10. 评测和安全回归

---

# Text-to-SQL 项目复现规格

本文是 MVP 基线以及增强版、生产版分阶段交付的编码依据。原项目历史指标只保存在
《Text-to-SQL原项目参考信息》，不构成新项目验收线，也不能直接新增功能。
本文中的默认值均为新项目决策。

## 1. 项目目标与非目标

### 目标

把用户自然语言问题转换为 PostgreSQL SQL，经确定性安全校验后在 Pagila 真实执行，并返回 SQL、结果或结构化失败。可修复错误最多修复三次，所有请求可通过 Trace 复盘。

### 非目标

- 写入、DDL、存储过程或事务编排。
- 复刻原项目成绩、Prompt、模型和半导体业务知识。
- BI 可视化或自然语言分析报告。
- “暂不实现”列表中的完整多租户、列级/行级权限、Gateway、MCP 和 Celery。

成功仅表示 SQL 通过安全门并执行成功；业务语义正确性由离线 Gold Result 判断。

## 2. MVP 范围

| 模块 | MVP 行为 |
|---|---|
| 数据库 | 一个 PostgreSQL 数据源；Pagila 版本锁定后固定 Schema 和数据 |
| 权限 | 固定测试用户；静态 Schema/表 allowlist |
| 元数据 | 表、字段、类型、PK/FK、unique constraint/index、注释、版本指纹 |
| Schema Linking | 词法/BM25 检索、字段聚合、FK 关系扩展、Top-K=10 |
| 生成 | 单模型，结构化返回 SQL 或澄清 |
| 校验 | SQLGlot PostgreSQL、单 statement、只读、对象和函数策略 |
| 执行 | 真实只读事务；30 秒；最多 1000 行 |
| 修复 | 初始 SQL 后最多三个不同修复 SQL |
| API | 同步 `POST /api/v1/text-to-sql`，总超时 120 秒 |
| 观测 | Trace、attempt、错误、Token、节点耗时 |
| 评测 | 固定 Pagila、Gold Schema/Fields/SQL/Result、独立安全集 |

### 2.1 最终交付阶段

| 阶段 | 输入 | 主要输出 | 失败与安全边界 |
|---|---|---|---|
| 0 规格与验收 | 本规格、测试规格、现有代码与正式报告 | 无冲突行为契约、ADR、三层完成门禁 | 未冻结的行为和参数不得编码 |
| 1 检索与路由 | 授权 Schema、问题、版本化模型配置 | 复杂度、动态 K、双路召回、RRF、Rerank、模型路由、裁剪上下文 | 任一通道都先授权过滤；旧索引拒绝；所有 SQL 仍重新校验 |
| 2 业务知识 | 已批准术语、指标、参考 SQL | 动态 Few-shot、业务 RAG、知识版本与撤销 | 未执行、未对账或未批准 SQL 不得写入长期知识 |
| 3 会话与记忆 | 可信身份、Session、当前权限和版本 | Checkpoint、恢复、Compaction、三级 Memory | 恢复必须重新校验身份、数据源、Schema 和知识版本 |
| 4 多源与方言 | Connector/Dialect Profile、数据源注册 | MySQL、StarRocks、跨源 QueryPlan 和受限合并 | 每个子查询重新授权和 AST 校验；真实数据库契约是门禁 |
| 5 生产治理 | 可信身份、版本键、结果存储、遥测 | 安全缓存、分页导出、限流熔断、容量、部署与保留 | 缓存/导出不得跨权限或版本；升级回滚和删除须可验证 |

每阶段只有同时满足明确契约、真实实现、单元和必要集成/E2E、超时取消降级、
配置和观测、权限隔离、迁移说明、实际测试通过及文档一致，才可标记完成。

## 3. 系统架构与请求链路

### 分层

```text
FastAPI / Bootstrap
        ↓
LangGraph Workflow
        ↓
Schema Linker ─ LLM Provider ─ SQLGlot Validator
        ↓
PostgreSQL Connector
        ↓
Trace / Evaluation
```

### 一次请求

1. API 校验长度和数据源，生成 `request_id`、`trace_id`，注入可信身份。
2. 预处理问题和时间表达式。
3. 权限节点得到允许的 Schema/表。
4. Schema Linking 在授权范围内以最大候选预算 20 生成探测候选。
5. ComplexityRoute 根据问题结构、正分候选、JOIN Path 和修复历史生成
   `simple/medium/complex`、5/10/20 与理由码。
6. Schema Linking 在同一授权 `schema_version` 上按决策预算物化最终候选；
   不再次读取数据库元数据。
7. 不能唯一确定业务对象时直接澄清，不生成 SQL。
8. 模型路由选择服务端批准的生成配置，生成节点返回目标方言 SQL。
9. 校验节点执行 AST、只读、对象和函数检查。
10. 真实数据库只读执行并规范化结果。
11. Schema 错误重新探测、决策和 Linking；语法/方言错误直接有限重生成；
    其他错误按路由终止。
12. Finalize 形成唯一 `FinalStatus` 和响应。

## 4. AgentState 核心字段

```python
from __future__ import annotations

from pydantic import BaseModel, Field


class SQLTaskState(BaseModel):
    request_id: str
    trace_id: str
    question: str
    normalized_question: str | None = None
    datasource_id: str
    dialect: str = "postgres"

    allowed_schemas: list[str] = Field(default_factory=list)
    allowed_tables: list[str] = Field(default_factory=list)

    candidate_tables: list[CandidateTable] = Field(default_factory=list)
    candidate_fields: list[CandidateField] = Field(default_factory=list)
    join_paths: list[JoinPath] = Field(default_factory=list)
    schema_version: str | None = None
    complexity_decision: ComplexityDecision | None = None

    current_sql: str | None = None
    sql_attempts: list[SQLAttempt] = Field(default_factory=list)
    seen_sql_fingerprints: set[str] = Field(default_factory=set)

    validation_result: ValidationResult | None = None
    execution_result: ExecutionResult | None = None
    database_error: DatabaseError | None = None

    error_type: ErrorType | None = None
    repair_strategy: RepairStrategy | None = None
    repair_count: int = 0
    infrastructure_retry_count: int = 0

    clarification: Clarification | None = None
    final_status: FinalStatus | None = None

    token_usage: TokenUsage = Field(default_factory=TokenUsage)
    node_timings: list[NodeTiming] = Field(default_factory=list)
```

| 字段组 | 写入方 | 主要读取方 | Trace |
|---|---|---|---:|
| 请求与数据源 | API、Preprocess | 全部节点 | 是 |
| 授权范围 | Permission | Linking、Generate、Validate | 记录版本与数量 |
| Schema 候选 | Linking | Generate、Reflect | 只记录版本、数量和脱敏分数摘要 |
| 复杂度决策 | ComplexityRoute | Linking、模型路由、上下文裁剪 | 等级、K、理由码和策略版本 |
| SQL attempts | Generate、Validate、Execute | Reflect、Finalize | 是，结果脱敏 |
| 错误与计数 | 失败节点、Reflect、Connector wrapper | Router、Finalize | 是 |
| 终态与观测 | Finalize、通用 wrapper | API、评测 | 是 |

规则：

- `GenerateSQLNode` 创建 attempt；Validate/Execute 只更新当前 attempt。
- `repair_count` 仅在接受一个新的修复 SQL 后增加。
- 基础设施重试只增加 `infrastructure_retry_count`。
- 探测 Linking 固定使用 20；最终 Linking 必须使用
  `complexity_decision.schema_top_k`，且两次结果使用同一授权快照版本。
- `ComplexityRouteNode` 不读取数据库、不调用 LLM，也不使用 Pagila
  `difficulty`、Gold SQL、Gold fields 或 Gold Result。
- Trace 追加写；凭据、完整 Prompt 和未脱敏结果不进入 State。

## 5. Workflow 节点契约

### RequestPreprocessNode

- **职责**：校验并规范化问题，解析相对时间。
- **核心输入**：`question`、默认时区。
- **核心输出**：`normalized_question`。
- **主要处理**：长度检查、空白规范化、把可确定时间转为绝对边界。
- **失败路由**：空问题/格式错误 → Finalize；语义依赖缺失 → Clarification。
- **下一节点**：PermissionResolve。

### PermissionResolveNode

- **职责**：确定数据源、方言和静态 Schema/表权限。
- **核心输入**：`datasource_id`、可信身份、服务端 allowlist。
- **核心输出**：`dialect`、`allowed_schemas`、`allowed_tables`。
- **主要处理**：请求范围与服务端权限求交集；权限不能由请求正文扩大。
- **失败路由**：范围为空或越权 → `PERMISSION_DENIED`。
- **下一节点**：SchemaLinking。

### SchemaLinkingNode

- **职责**：找到回答问题所需的表、字段和 JOIN Path。
- **核心输入**：`normalized_question`、授权范围、Schema 元数据。
- **核心输出**：候选表、字段、JOIN Path、`schema_version`。
- **主要处理**：首次从 Connector 读取授权快照并以 K=20 探测；复杂度决策后
  复用同一快照，以 K=5/10/20 重新物化候选。双路召回实现后，两次处理均复用
  同版本检索语料和索引。
- **失败路由**：无候选或候选互斥 → Clarification；修复时仍无对象 → Finalize。
- **下一节点**：探测完成 → ComplexityRoute；物化完成 → GenerateSQL。

### ComplexityRouteNode

- **职责**：显式、确定性地决定复杂度和 Schema Top-K，并为后续服务端模型
  路由及上下文预算选择提供封闭等级。
- **核心输入**：`normalized_question`、探测候选、JOIN Path、
  `has_repair_history`、版本化本地策略。该布尔值由已有 attempt、
  `repair_strategy` 和 `repair_count` 派生，不改变现有修复计数语义。
- **核心输出**：`ComplexityDecision`，至少包含 `level`、
  `schema_top_k`、`reason_codes` 和 `policy_version`。
- **主要处理**：结合聚合、窗口、子查询、时间、正分多表、相关 JOIN Path 和
  修复历史；相同输入与版本必须产生相同结果。
- **硬边界**：不调用 Connector、Embedding、Reranker 或 LLM；不扩大授权；
  不读取评测 `difficulty` 或任何 Gold 预期。
- **失败路由**：无效或不一致证据 → Finalize/`FAILED_INTERNAL`。
- **下一节点**：SchemaLinking（同版本物化）。

### GenerateSQLNode

- **职责**：生成初始 SQL 或修复 SQL。
- **核心输入**：问题、授权候选、JOIN Path、方言、修复策略。
- **核心输出**：`current_sql`、新 `SQLAttempt`、Token。
- **主要处理**：结构化输出；计算 SQL 指纹；新修复 SQL 才增加 `repair_count`。
- **失败路由**：模型超时/格式无效 → Finalize；重复指纹 → `DUPLICATE_SQL`。
- **下一节点**：ValidateSQL。

### ValidateSQLNode

- **职责**：执行 SQLGlot AST 和安全校验。
- **核心输入**：`current_sql`、方言、授权对象、函数策略。
- **核心输出**：`validation_result` 或结构化错误。
- **主要处理**：单 statement、只读、对象、字段存在性、函数和资源规则。
- **失败路由**：语法/Schema/方言 → Reflect；权限/危险 SQL/资源硬限制 → Finalize。
- **下一节点**：ExecuteSQL。

### ExecuteSQLNode

- **职责**：在真实 PostgreSQL 中只读执行。
- **核心输入**：已通过校验的 SQL、Connector。
- **核心输出**：`execution_result` 或 `database_error`。
- **主要处理**：只读事务、30 秒 timeout、读取最多 1001 行以判断 1000 行截断、取消与清理。
- **失败路由**：SQL 类错误 → Reflect；连接错误有限同 SQL 重试；权限/超时/资源 → Finalize。
- **下一节点**：Finalize 或 Reflect。

### ReflectSQLNode

- **职责**：根据确定性错误选择下一修复动作。
- **核心输入**：当前 attempt、错误类型、SQL 历史、剩余预算。
- **核心输出**：`repair_strategy`。
- **主要处理**：语法最小修复；Schema 错误重做 Linking；方言错误重生成；检查预算和循环。
- **失败路由**：业务知识缺失/语义不唯一 → Clarification；预算耗尽/重复策略 → Finalize。
- **下一节点**：SchemaLinking、GenerateSQL、Clarification 或 Finalize。

### ClarificationNode

- **职责**：在执行前返回最小澄清问题。
- **核心输入**：互斥候选或缺失的口径/范围。
- **核心输出**：`clarification`、`CLARIFICATION_REQUIRED`。
- **主要处理**：只展示授权范围内的候选，不执行 SQL。
- **失败路由**：模板构造失败 → Finalize/`FAILED_INTERNAL`。
- **下一节点**：Finalize。

### FinalizeNode

- **职责**：生成唯一终态和 API 响应。
- **核心输入**：SQL attempts、结果、错误、澄清、观测数据。
- **核心输出**：`final_status` 和响应。
- **主要处理**：成功、澄清、拒绝、失败互斥；清除敏感内部信息。
- **失败路由**：本地序列化异常 → `FAILED_INTERNAL`。
- **下一节点**：END。

通用 wrapper 统一处理节点 timeout、异常封装、Token、耗时和 Trace，节点契约不重复这些规则。

## 6. 条件路由和错误类型

```text
ErrorType =
  SYNTAX_ERROR
  SCHEMA_ERROR
  DIALECT_ERROR
  BUSINESS_KNOWLEDGE_MISSING
  AMBIGUOUS_SEMANTICS
  PERMISSION_DENIED
  CONNECTION_ERROR
  TIMEOUT
  RESOURCE_RISK
  DUPLICATE_SQL
  UNKNOWN

FinalStatus =
  SUCCEEDED_FIRST_PASS
  SUCCEEDED_REPAIRED
  CLARIFICATION_REQUIRED
  REJECTED_SECURITY
  FAILED_REPAIR_EXHAUSTED
  FAILED_DUPLICATE_LOOP
  FAILED_TIMEOUT
  FAILED_CONNECTION
  FAILED_RESOURCE_RISK
  FAILED_INTERNAL
```

唯一完整路由表：

| ErrorType/条件 | LLM 修复 | 数据库重试 | 下一步/FinalStatus |
|---|---:|---:|---|
| 无错误，初始 attempt 执行成功 | 否 | 否 | `SUCCEEDED_FIRST_PASS` |
| 无错误，修复 attempt 执行成功 | 否 | 否 | `SUCCEEDED_REPAIRED` |
| `SYNTAX_ERROR` | 是 | 否 | Reflect → Generate |
| `SCHEMA_ERROR` | 是 | 否 | Reflect → Linking → Generate |
| `DIALECT_ERROR` | 是 | 否 | Reflect → Generate |
| `BUSINESS_KNOWLEDGE_MISSING` | 否 | 否 | Clarification |
| `AMBIGUOUS_SEMANTICS` | 否 | 否 | Clarification |
| `PERMISSION_DENIED` 或安全规则 | 否 | 否 | `REJECTED_SECURITY` |
| `CONNECTION_ERROR` | 否 | 有限同调用重试 | 用尽后 `FAILED_CONNECTION` |
| `TIMEOUT` | 否 | 否 | 取消并 `FAILED_TIMEOUT` |
| `RESOURCE_RISK` | 否 | 否 | 可安全缩小范围则澄清，否则 `FAILED_RESOURCE_RISK` |
| `DUPLICATE_SQL` | 否 | 否 | `FAILED_DUPLICATE_LOOP` |
| `UNKNOWN` | 否 | 否 | `FAILED_INTERNAL` |
| 修复失败且 `repair_count >= 3` | 否 | 否 | `FAILED_REPAIR_EXHAUSTED` |
| Workflow 步数达到 32 | 否 | 否 | `FAILED_INTERNAL` |

数据库错误优先使用 SQLSTATE 分类：`42601`→语法，`42P01/42703/42702`→Schema，`42501`→权限，class `08`→连接，`57014`→超时，class `53`→资源。不能只靠错误文本。

## 7. Schema Linking

### 元数据

每个数据源快照至少包含：

- Schema、表、字段、类型、nullable、注释。
- PK、FK、unique constraint/index。
- 表和字段别名。
- `schema_version` 指纹。

### MVP 算法

1. 在授权 Schema/表范围内建立表文档和字段文档。
2. 用规范化问题进行词法/BM25 检索。
3. 字段命中汇总到表，保留命中证据。
4. 用 FK 图补充 JOIN Path 和必要中间表。
5. 按名称、注释、字段覆盖和关系连通性排序。
6. 返回最多 10 张表及相关字段。

修复时可重新检索，但仍受 Top-K 和权限约束。Embedding、RRF、Rerank、动态 Top-K、Few-shot 和业务指标知识库均不进入 MVP。

### 增强阶段 1 算法

1. 授权过滤必须发生在分词、BM25 文档统计、Embedding、融合和 Rerank 之前。
2. 探测候选固定上限 20；显式 `ComplexityRouteNode` 决定最终
   `simple=5`、`medium=10`、`complex=20`。
3. BM25 与 Embedding 各自产生稳定 rank；不得直接混合两路原始分值。
4. 使用 `RRF k=60` 融合，保存每路 rank 和贡献，使用规范对象 ID 稳定
   tie-break。
5. Rerank 使用可解释白名单特征：字段覆盖、已批准 alias、PK/FK 连通、
   中间表、JOIN path 成本、表粒度和断开惩罚；不得使用 Gold 特征。
6. 最终物化只保留决策预算内候选；上下文裁剪优先保留命中字段、PK/FK、
   JOIN、过滤、聚合、时间和粒度字段。
7. 索引键至少绑定 datasource、授权范围摘要、Schema 版本、语义版本、
   Embedding 模型、文档构建器和融合/Rerank 策略版本。
8. Embedding 或 Rerank 故障只允许按预定义矩阵降级到同版本安全路径；不得使用
   陈旧索引、扩大权限或隐藏降级。

阶段 1 调参只使用独立非 Gold development/calibration 数据。18 条 Pagila
Gold 只用于冻结后的最终验收，不进入检索语料、Few-shot、训练、权重选择或
重复抽样择优。

## 8. SQL 生成

### 上下文

- 原问题和规范化时间。
- PostgreSQL 方言。
- 候选表、字段、类型、PK/FK、JOIN Path。
- 当前错误和修复策略。
- 只读、安全、行数和函数约束。

### 模型输出

```python
class GeneratedSQL(BaseModel):
    sql: str | None = None
    clarification_reason: str | None = None
```

二者必须且只能出现一个。Prompt 负责约束输出格式和优先使用提供的对象；权限、安全和对象真实性由确定性校验负责。

每个 attempt 保存序号、SQL、指纹、校验结果、执行结果和错误。MVP 不启用
Few-shot 和业务 RAG。增强阶段 1 的模型路由只能从服务端版本化路由表选择；
请求不能指定模型，基础设施回退最多一次且必须保持相同数据边界。阶段 2
Few-shot 和业务 RAG 上线前必须完成参考 SQL 的验证、对账、批准、版本和撤销
闭环。

## 9. AST 与安全校验

### 校验顺序

```text
SQLGlot(postgres)
→ 单 statement
→ SELECT/受控 CTE
→ 禁止节点和锁定变体
→ 表/字段存在性
→ Schema/表 allowlist
→ 函数策略
→ 允许执行
```

### 允许的 MVP 函数

| 类别 | 初始允许清单 |
|---|---|
| 聚合 | `COUNT`, `SUM`, `AVG`, `MIN`, `MAX` |
| 空值 | `COALESCE`, `NULLIF` |
| 文本 | `LOWER`, `UPPER`, `LENGTH`, `TRIM`, `SUBSTRING` |
| 时间 | `DATE_TRUNC`, `EXTRACT`, `CURRENT_DATE` |
| 数值 | `ROUND`, `ABS`, `CEIL`, `FLOOR` |
| 条件表达式 | `CASE` |
| 类型转换 | `CAST` |

该清单是 MVP 基线，可通过版本化配置扩展。大小写不敏感，但必须按 AST 函数标识匹配。

### 明确拒绝

- INSERT、UPDATE、DELETE、MERGE、CREATE、ALTER、DROP、TRUNCATE。
- COPY、CALL、DO、SET、RESET、多 statement。
- `SELECT INTO`、`FOR UPDATE`、`FOR SHARE`。
- `pg_sleep`、文件访问函数、`dblink`、外部网络访问函数。
- 未审批 UDF、数据库管理/系统执行函数、明显有副作用的函数。
- `SELECT *`、未授权对象、未知 AST 节点和解析失败。

数据库账号仍必须只有 SELECT 权限；AST 校验不是唯一安全边界。

## 10. 数据库执行

`PostgreSQLConnector` 负责：

- 连接测试和 Schema introspection。
- 按 datasource 隔离连接池和凭据。
- 开启只读事务并设置 30 秒 statement timeout。
- 最多读取 1001 行：返回前 1000 行并设置 `truncated`。
- 规范化 NULL、Decimal、日期、时间戳、时区和 JSON。
- 将驱动异常转为 SQLSTATE、`ErrorType`、是否可重试和脱敏消息。
- 超时后取消查询；无法确认已取消的连接不得直接放回池。

连接类瞬时错误可在同一调用上有限重试，不生成新 SQL，不增加 `repair_count`。认证、权限、配置和 SQL 确定性错误不盲重试。

## 11. 反思修复与循环终止

- attempt 0 为初始 SQL；最多接受 attempt 1、2、3 三个不同修复 SQL。
- 新修复 SQL 通过指纹去重后才增加 `repair_count`。
- 语法错误做最小修改；Schema 错误先重新 Linking；方言错误按 PostgreSQL 重生成。
- 权限、安全、连接、超时、资源和语义歧义不进入 SQL 修复。
- 每次修复后必须重新 Validate，再 Execute。
- 可解析 SQL 使用 SQLGlot 稳定序列化计算指纹；解析失败使用原始 SQL 精确哈希。
- 已见指纹不再执行；A→B→A 循环同样终止。
- `repair_count >= 3`、重复 SQL、请求超时或步骤达到 32 时终止。

## 12. API 输入输出

### 请求

```python
class QueryRequest(BaseModel):
    question: str
    datasource_id: str = "pagila"
    schemas: list[str] = Field(default_factory=list)
    debug: bool = False
```

- Endpoint：`POST /api/v1/text-to-sql`
- `question` 去除空白后长度为 1～2000。
- 用户身份由可信认证依赖注入，不能由正文声明。
- 普通客户端的 `debug=true` 不能绕过服务端调试权限。

### 响应

```python
class QueryResponse(BaseModel):
    request_id: str
    trace_id: str
    status: FinalStatus
    sql: str | None = None
    columns: list[ResultColumn] = Field(default_factory=list)
    rows: list[list[JsonValue]] = Field(default_factory=list)
    returned_row_count: int = 0
    truncated: bool = False
    attempts: int = 0
    repair_count: int = 0
    clarification: Clarification | None = None
    error: PublicError | None = None
```

约束：

- 成功：SQL 非空，`error`/`clarification` 为空；合法空结果允许 `rows=[]`。
- 澄清：不执行 SQL，`clarification` 非空。
- 权限/安全：不返回可枚举未授权对象的 SQL 或错误。
- 失败：结果为空，错误消息脱敏；原始驱动堆栈不对外。

## 13. 配置项

```yaml
database:
  dialect: postgres
  max_result_rows: 1000
  statement_timeout_seconds: 30

workflow:
  max_repair_count: 3
  max_workflow_steps: 32

schema_linking:
  probe_top_k: 20
  simple_top_k: 5
  medium_top_k: 10
  complex_top_k: 20
  rrf_k: 60

complexity_routing:
  policy_version: complexity-v1

llm:
  protocol: openai_compatible
  base_url: ${LLM_BASE_URL}
  api_key: ${LLM_API_KEY}
  model: ${LLM_MODEL}
  timeout_seconds: 30
  temperature: 0
  max_input_tokens: 32768
  max_output_tokens: 2048

model_routing:
  simple_override_prefix: LLM_SIMPLE_
  standard_override_prefix: LLM_STANDARD_
  complex_override_prefix: LLM_COMPLEX_
  fallback_override_prefix: LLM_FALLBACK_
  data_boundary_id: ${MODEL_ROUTING_DATA_BOUNDARY_ID}
  simple_fallback_enabled: false
  standard_fallback_enabled: false
  complex_fallback_enabled: false

embedding:
  protocol: openai_compatible
  base_url: ${EMBEDDING_BASE_URL}
  api_key: ${EMBEDDING_API_KEY}
  model: text-embedding-v4
  dimension: 1024
  timeout_seconds: 10
  max_batch_documents: 64
  max_response_bytes: 4194304

api:
  path: /api/v1/text-to-sql
  method: POST
  request_timeout_seconds: 120
  question_max_chars: 2000

time:
  default_timezone: Asia/Shanghai
```

基础 LLM 配置为三条主路由的默认值；每个非空的路由前缀覆盖项必须形成完整、
合法的路由配置。Fallback 只有在配置了独立 Provider 且显式为至少一条路由开启
时才生效，并且必须满足同一数据边界及 Token 上限约束。凭据只通过
Secret/环境变量注入。启动时校验配置；缺少数据库、声明的生成模型路由或
Embedding 必要配置时不得以宽松模式运行。

## 14. 日志与 Trace

每个请求至少记录：

- `request_id`、`trace_id`、节点、attempt、路由和 `FinalStatus`。
- SQL 指纹、`ErrorType`、稳定错误码、修复策略。
- 输入/输出 Token、节点耗时、数据库耗时、返回行数、是否截断。
- Prompt 版本、模型配置 ID、Schema 版本。
- 复杂度等级、实际 Top-K、理由码和策略版本。
- BM25/Embedding 版本与候选数、RRF 配置摘要、Rerank 理由码、
  上下文裁剪前后计数、模型路由和降级状态。

不得记录问题原文、SQL 原文、表/字段原名、数据库凭据、完整 Prompt、未脱敏
样例值和完整敏感结果。Trace sink 失败只记录降级事件，不改变已完成的业务结果。

## 15. 项目目录

```text
app/
├── api/
├── workflow/
│   ├── models.py
│   ├── complexity.py
│   ├── graph.py
│   └── nodes.py
├── schema_linking/
│   ├── authorization.py
│   ├── embedding.py
│   ├── fusion.py
│   ├── index.py
│   ├── linker.py
│   └── rerank.py
├── generation/
│   ├── context.py
│   ├── routing.py
│   ├── provider.py
│   └── service.py
├── validation/
├── connectors/
├── observability/
└── config.py
evaluation/
├── cases/
│   ├── pagila_mvp.jsonl
│   ├── retrieval_routing_development.jsonl
│   └── retrieval_routing_calibration.jsonl
├── code_freeze.py
├── comparator.py
├── loader.py
├── report.py
├── runner.py
└── reports/
    ├── pagila_mvp_stage10.md
    └── enhancement_stage1_qualification.md
tests/
├── unit/
├── integration/
├── security/
└── fixtures/pagila/
docs/
├── Text-to-SQL项目复现规格.md
├── Text-to-SQL测试与验收规格.md
├── decisions/
└── superpowers/

```

首批提交只创建当前纵向闭环需要的文件，不预建空的生产化模块。
`docs/Text-to-SQL原项目参考信息.md` 不是编码需求，也不得纳入后续推送。

## 16. MVP 编码任务清单

- [ ] 锁定 Pagila 和 PostgreSQL 测试环境。
- [ ] 实现配置加载和启动校验。
- [ ] 实现 PostgreSQL Connector 与错误归一化。
- [ ] 实现 Schema introspection 和版本指纹。
- [ ] 实现词法/BM25 Schema Linking。
- [ ] 实现 SQLGlot AST、安全和函数策略。
- [ ] 实现结构化 SQL 生成。
- [ ] 实现真实只读执行、超时、截断和取消。
- [ ] 保留 MVP 九节点基线，并在增强阶段 1 增加显式
      `ComplexityRouteNode`，形成十种节点。
- [ ] 实现修复预算、SQL 指纹和循环终止。
- [ ] 实现 FastAPI Request/Response。
- [ ] 实现 Trace、Comparator 和 JSONL Case runner。
- [ ] 运行 Pagila、路由、Connector 和安全回归。

## 17. MVP 默认技术选型

本项目不要求用户在编码前逐项研究和确认底层技术选型。除 LLM 接入协议外，其余选型由 Codex 按以下默认方案执行，并记录到项目配置和技术决策文档中。

### 17.1 LLM 接入要求

LLM 统一使用 OpenAI-compatible API 协议，不与 OpenAI、Kimi、DeepSeek 或其他具体厂商绑定。

通过环境变量配置：

```yaml
llm:
  protocol: openai_compatible
  base_url: ${LLM_BASE_URL}
  api_key: ${LLM_API_KEY}
  model: ${LLM_MODEL}
  timeout_seconds: 30
  temperature: 0
```

要求：

* 所有模型调用统一经过 `LLMProvider` 接口；
* 业务节点不得直接依赖某个厂商的 SDK；
* 支持配置 Kimi、DeepSeek，以及其他兼容 OpenAI API 协议的模型；
* `base_url`、`api_key` 和 `model` 必须从环境变量读取；
* 不得在代码、配置文件或日志中写死密钥；
* 模型响应应在 Provider 层转换成项目统一的结构化结果；
* 不同兼容服务之间的参数差异应封装在 Provider 内部，不能扩散到 Workflow 节点。

### 17.2 默认基础环境

MVP 默认采用：

```yaml
database:
  type: postgresql
  version: "16"

python_database_driver:
  name: psycopg
  major_version: "3"

example_database:
  name: pagila
  version_policy: pin_specific_commit
```

Pagila 不要求用户提前指定 commit。Codex 应：

1. 选择一个能够在 PostgreSQL 16 中正常初始化的 Pagila commit；
2. 将 commit ID、来源和数据校验和记录到项目文档；
3. 后续测试、Gold SQL 和 Gold Result 全部使用该固定版本；
4. 不得在开发过程中静默切换 Pagila 版本。

### 17.3 测试模型策略

测试分为两种模式。

#### 固定 Stub

用于：

* Workflow 路由测试；
* SQL 修复次数测试；
* 重复 SQL 测试；
* 权限和安全测试；
* 超时与异常测试；
* API Contract 测试。

Stub 必须返回固定、可预测的模型结果，保证测试可以重复运行。

#### 真实模型

用于：

* Text-to-SQL E2E；
* Schema Linking 与生成联合效果；
* 首次可执行率；
* 修复后可执行率；
* Gold Result 正确性；
* Token 和响应时间统计。

真实模型通过 OpenAI-compatible API 配置接入。

固定 Stub 负责验证系统逻辑，真实模型负责验证实际 Text-to-SQL 效果，两者不能互相替代。

### 17.4 Codex 的执行规则

Codex 应直接采用上述默认选型推进 MVP，不需要在每个编码任务开始前重复询问。

只有以下情况才需要暂停并说明：

* Pagila 无法在 PostgreSQL 16 中正常初始化；
* Psycopg 3 与当前项目已有依赖产生不可解决的冲突；
* 所配置的模型服务不兼容项目需要的 OpenAI API 调用格式；
* 默认方案会导致安全、数据或测试结果无法保证；
* 用户明确要求更换选型。

遇到普通实现细节时，Codex应自行采用合理方案，写入配置和技术决策记录，然后继续开发，不要把常规技术选型反复交给用户确认。


除以上五项外，MVP 行为使用本文默认值，不再等待额外设计决策。
