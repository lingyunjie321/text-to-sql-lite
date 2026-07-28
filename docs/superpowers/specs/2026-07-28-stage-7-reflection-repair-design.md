# 第七开发阶段：反思修复、SQL 指纹与循环终止设计

## 目标

在不引入 LangGraph 的前提下，实现可供 Stage 8 节点直接复用的确定性反思核心：
记录每个 SQL attempt，按 SQLGlot 稳定指纹去重，只接受最多三个不同修复 SQL，
并根据 `ErrorType` 选择重新 Linking、重新生成、澄清或终止。每个接受的修复
attempt 必须重新经过 Stage 3 校验和 Stage 6 执行边界。

## 范围

### 包含

- 可解析 SQL 的 SQLGlot PostgreSQL 稳定指纹；
- 解析失败 SQL 的原始字符串精确 SHA-256；
- attempt 0 和最多 attempt 1、2、3；
- 不可变 `SQLAttempt`、`AttemptHistory` 和修复注册结果；
- 对当前 attempt 记录校验与执行结果；
- 重复 SQL 和 A→B→A 的执行前终止；
- 语法、Schema、方言、语义、权限、连接、超时、资源和未知错误的确定性决策；
- Stub 和真实 Pagila 的“错误 → 修复 → 重新校验 → 执行”集成测试。

### 不包含

- LangGraph State、节点和 32 步图级终止；
- 修改 Stage 5 Prompt 或自动调用 LLM；
- FastAPI、Trace、Comparator 和评测 Runner；
- 权限、安全、连接、超时和资源错误的 SQL 盲修；
- Few-shot、RAG、多模型或长期记忆。

## 模块

```text
app/reflection/
├── __init__.py
├── fingerprint.py
├── models.py
└── service.py
```

## SQL 指纹

```python
def sql_fingerprint(sql: str) -> str:
    ...
```

- 空 SQL 拒绝；
- 能被 SQLGlot PostgreSQL 完整解析时，对全部 statement 的稳定 PostgreSQL
  序列化结果计算 SHA-256；
- 解析或序列化失败时，对未经 strip 或改写的原始 SQL UTF-8 字节计算 SHA-256；
- 可解析 SQL 的大小写、空白和末尾分号等格式差异应得到相同指纹；
- SQL 行/块注释不参与指纹，未加引号标识符按 PostgreSQL 规则规范大小写；
- 解析失败 SQL 的任意原始字符差异都应得到不同指纹。

指纹只用于循环终止，不替代 Stage 3 单 statement/安全校验。

## Attempt 契约

```python
@dataclass(frozen=True, slots=True)
class SQLAttempt:
    attempt_number: int
    sql: str
    fingerprint: str
    validation_result: ValidationResult | None = None
    execution_result: ExecutionResult | None = None
    database_error: DatabaseError | None = None


@dataclass(frozen=True, slots=True)
class AttemptHistory:
    attempts: tuple[SQLAttempt, ...]
    seen_sql_fingerprints: frozenset[str]
    repair_count: int
```

History 至少含 attempt 0，编号连续；指纹唯一且 seen set 必须精确相等；
`repair_count == len(attempts) - 1` 且范围 0～3。校验结果只能记录一次；执行结果
只能在当前校验成功后记录一次，并且成功结果和数据库错误不能同时存在。
History 容器强制为 tuple/frozenset，不能通过外部 list/set alias 破坏不变量。
成功校验结果必须是当前策略，且其规范 SQL 指纹必须绑定当前 attempt SQL。
修复注册状态和带修复策略的决策也做运行时类型/语义绑定，不能直接构造出
“权限错误但继续生成 SQL”等不可能状态。

公共操作：

- `start_attempt(sql)`；
- `record_validation(history, result)`；
- `record_execution(history, outcome)`；
- `register_repair_sql(history, sql)`。

`register_repair_sql()` 只允许当前错误为 `SYNTAX_ERROR`、`SCHEMA_ERROR` 或
`DIALECT_ERROR`。它先检查全部历史指纹，再检查三次预算：

- 新指纹且预算可用：接受新 attempt，`repair_count + 1`；
- 已见指纹：History 不变，返回 `DUPLICATE`；
- 已有三个修复：History 不变，返回 `EXHAUSTED`。

因此重复或超预算 SQL 不会进入 Validator 或 Connector。

## 反思决策

```python
def decide_reflection(
    error_type: ErrorType,
    *,
    repair_count: int,
    can_reduce_resource: bool = False,
) -> ReflectionDecision:
    ...
```

| 条件 | Route | Strategy |
|---|---|---|
| `SYNTAX_ERROR`，预算可用 | `GENERATE_SQL` | `MINIMAL_SQL_REPAIR` |
| `SCHEMA_ERROR`，预算可用 | `SCHEMA_LINKING` | `RELINK_SCHEMA` |
| `DIALECT_ERROR`，预算可用 | `GENERATE_SQL` | `REGENERATE_POSTGRES` |
| 上述错误且已有 3 个修复 | `FINALIZE` | 无 |
| 业务知识缺失/语义歧义 | `CLARIFICATION` | 无 |
| 资源风险且可安全缩小范围 | `CLARIFICATION` | 无 |
| 权限、安全、连接、超时、其他资源、重复或未知 | `FINALIZE` | 无 |

权限、安全、连接、超时和资源风险不返回 SQL 修复策略。基础设施连接重试继续只
发生在 Stage 1 Connector 的同一次调用内，不创建 attempt、不增加
`repair_count`。

## 测试

- 指纹：格式/注释等价、引号语义、不同 SQL、多 statement、Parse/Token 失败
  原始精确 hash；
- 模型：连续编号、seen set、XOR、不可变和错误构造拒绝；
- 预算：attempt 0、三个不同修复、第四个拒绝、重复和 A→B→A；
- 路由：完整 `ErrorType` 表、预算耗尽、资源澄清；
- 安全：硬错误零修复、重复 SQL 零校验/零执行、计数不变；
- 集成：Pagila Gold reflection Case 的错误字段修复后重新 Linking/Validate/
  Execute，结果成功；确定性 Stub 覆盖重复环路。

## 完成标准

- attempt 0 和最多三个不同修复符合规格；
- 重复 SQL 在执行前终止，A→B→A 同样终止；
- 只有语法、Schema、方言错误可获得 SQL 修复策略；
- 每个接受修复重新完整校验并通过 Stage 6 边界执行；
- 不修改 Stage 5/6 公共接口，不新增生产依赖；
- 全量单元、安全、集成和此前阶段回归通过；
- 独立审查 `blocking=0`、`high=0`；
- 三份受保护文件未修改；
- 未实现 Stage 8+ 功能。
