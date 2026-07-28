# 第六开发阶段：校验后真实执行设计

## 目标

在 Stage 3 的确定性 SQL 安全门与 Stage 1 的 PostgreSQL Connector 之间增加
一个最小、可测试的执行边界。该边界接收当前 `mvp-v1` 策略的
`ValidationResult` 和同一份可信授权快照，执行前重新调用 Stage 3 校验并要求
结果完全一致，只执行其中的规范 SQL，并把 Connector 成功或脱敏数据库错误
转换为严格二选一结果。

## 范围

### 包含

- `SQLExecutor` 协议，隔离执行服务与具体 Connector；
- `ExecutionOutcome` 成功/失败 XOR 契约；
- `execute_validated_sql()` 校验后执行入口；
- 使用同一可信授权范围和 Snapshot 重新校验，防止伪造成功结果；
- 无效、失败或不一致的校验结果零数据库调用；
- 只向 Connector 传递 `normalized_sql`；
- Connector 的只读事务、30 秒 timeout、1001 行探测、1000 行返回上限、值
  规范化、取消和同 SQL 连接重试复用；
- Stub 单元/安全测试和真实 Pagila 执行集成测试。

### 不包含

- SQL attempt、指纹、修复预算和反思策略；
- LangGraph State、节点、路由和 FinalStatus；
- FastAPI、Trace、Comparator 和评测 Runner；
- 新的数据库重试层或修改 SQL；
- 自动执行未经 Stage 3 校验的模型输出。

## 公共契约

新增：

```text
app/execution/
├── __init__.py
├── models.py
└── service.py
```

```python
class SQLExecutor(Protocol):
    def execute(self, sql: str) -> ExecutionResult:
        ...


@dataclass(frozen=True, slots=True)
class ExecutionOutcome:
    result: ExecutionResult | None
    error: DatabaseError | None


def execute_validated_sql(
    validation_result: ValidationResult,
    *,
    allowed_schemas: tuple[str, ...],
    allowed_tables: tuple[str, ...],
    snapshot: SchemaSnapshot,
    connector: SQLExecutor,
) -> ExecutionOutcome:
    ...
```

`ExecutionOutcome` 必须且只能包含 `result` 或 `error`。成功时原样保留 Connector
返回的列、规范化行、行数、截断标记和执行耗时；失败时只保留已经脱敏的
`DatabaseError`。运行时也严格检查两种对象类型，错误的 Connector Stub 不能把
任意值伪装成成功或失败结果。

## 执行前置条件

服务在数据库调用前 fail-closed 检查：

- `is_valid` 必须精确为 `True`；
- `policy_version` 必须等于当前 `POLICY_VERSION="mvp-v1"`；
- `normalized_sql` 必须是非空字符串；
- `issue` 必须为 `None`；
- 引用表和字段必须是字符串 tuple。

任一条件不满足时抛出固定
`ValueError("execution context is invalid")`，不包含 SQL、对象名、数据库错误
或凭据，且 Connector 调用次数为零。

执行服务不再接收第二份原始 SQL，因此不能出现“校验 A、执行 B”。字段形状通过
后，服务使用传入的服务端可信 `allowed_schemas`、`allowed_tables` 和
`snapshot` 重新调用 Stage 3 `validate_sql()`；重新校验结果必须与传入结果完全
相等，否则仍以通用上下文错误拒绝。这里复用 Validator 而不复制安全规则，并能
阻止调用方通过公开 `success_result()` 伪造危险 SQL。模型的澄清结果和失败校验
结果均不能进入执行。

## Connector 与错误边界

`execute_validated_sql()` 对 Connector 只调用一次 `execute(normalized_sql)`。
Stage 1 Connector 在该调用内部负责：

- 只读事务和只读账号双层防线；
- 最大 30 秒 PostgreSQL `statement_timeout`；
- 最多读取 1001 行并只返回前 1000 行；
- SQLSTATE 分类和固定公开消息；
- 超时取消、事务回滚和连接恢复/废弃；
- 仅 class `08` 瞬时连接错误的有限同 SQL 重试。

执行服务不增加第二套重试，也不改变 SQL。它只捕获
`PostgreSQLConnectorError` 并提取其脱敏 `details`；未知编程错误留给 Stage 8
通用节点 wrapper 统一封装。

## 测试

- 契约：Outcome XOR、不可变、成功/错误工厂；
- 单元：只执行规范 SQL一次、结果/错误保真、无效上下文零调用；
- 安全：失败校验、权限拒绝、多 statement、DML、危险函数、伪造成功和不一致
  结果均零调用；异常和 repr 不泄露 SQL、DSN 或驱动原文；
- 集成：真实 Pagila 普通 SELECT、CTE/聚合、合法空结果、1000 行截断以及
  运行时数据库错误归一化；
- 回归：Stage 1–5 全量单元、安全和集成测试。

## 完成标准

- 只有在同一可信授权上下文重新校验且结果完全一致的规范 SQL 才能进入
  Connector；
- 成功结果和数据库错误严格 XOR；
- 不新增生产依赖，不修改 Stage 1/3 公共接口；
- 真实 Pagila 执行、超时/截断/只读 Connector 回归通过；
- 单元、安全、集成和 Stage 1–5 回归通过；
- 独立审查 `blocking=0`、`high=0`；
- 三份受保护文件未修改；
- 未实现 Stage 7+ 功能。

## 已知边界

Stage 3 当前保留用户 SQL 的未限定表名，Stage 6 不自行重写 SQL。锁定的 MVP
只有 Pagila `public` Schema，应用角色只被授予该 Schema 的 USAGE 和表 SELECT，
且只读事务不能创建遮蔽物，因此当前门禁不产生跨 Schema 越权。未来若扩展到
多个可读 Schema，必须先让规范 SQL 绑定已解析 Schema 或固定安全
`search_path`；这不在当前 public-only MVP 范围内。
