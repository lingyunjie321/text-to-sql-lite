# ADR 0006：校验后真实执行边界

## 状态

已验证，2026-07-28。

## 决策

第六开发阶段在 Stage 3 Validator 和 Stage 1 PostgreSQL Connector 之间增加
`app.execution` 薄层。公共入口只接受一个 `ValidationResult`，不再接受第二份
原始 SQL：

```python
outcome = execute_validated_sql(
    validation_result,
    allowed_schemas=allowed_schemas,
    allowed_tables=allowed_tables,
    snapshot=snapshot,
    connector=connector,
)
```

只有 `mvp-v1` 当前策略下 `is_valid=True`、`issue=None` 且具有非空
`normalized_sql` 的一致结果才进入下一步。服务随后使用同一份服务端可信授权
范围和 Snapshot 重新调用 Stage 3 `validate_sql()`，并要求结果完全相等。这样
公开的 `success_result()` 不能被当作校验凭证。服务最终只把该
`normalized_sql` 传给 Connector，因此不存在“校验 A、执行 B”的参数组合。
失败、旧策略、伪造成功或内部不一致结果都在数据库调用前以固定通用错误
fail-closed。

## 结果契约

`ExecutionOutcome` 是不可变的严格二选一：

- 成功：`result=ExecutionResult`、`error=None`；
- 失败：`result=None`、`error=DatabaseError`。

构造时同时进行运行时类型检查，错误的 Connector/Stub 不能用任意对象伪装结果
或错误。

成功结果原样保留 Stage 1 已验证的列、JSON 规范化行、返回行数、截断标记和执行
耗时。Connector 抛出的 `PostgreSQLConnectorError` 只提取脱敏 `details`，不
暴露 SQL、DSN、驱动消息、堆栈或连接信息。

## 职责边界

Stage 6 不复制数据库机制。以下职责继续只有 Stage 1 Connector 拥有：

- 只读账号和 `SET TRANSACTION READ ONLY` 双层防线；
- 最大 30 秒 PostgreSQL `statement_timeout`；
- 读取 1001 行判断截断、只返回前 1000 行；
- PostgreSQL 值的稳定 JSON 表示；
- SQLSTATE 错误分类、超时取消和连接恢复；
- 仅 class `08` 瞬时连接错误的有限同 SQL 重试。

执行服务对 Connector 只发起一次公开 `execute()` 调用，不添加重试、不改写
SQL、不解析 Prompt。未知编程错误不伪装成数据库错误，留给 Stage 8 节点通用
wrapper 处理。

## 安全边界

- 模型 SQL 必须先经过 Stage 3，Prompt 仍不能替代安全校验；
- 执行前以同一授权上下文重新运行 Stage 3，且传入/重算结果必须完全一致；
- DML、多 statement、危险函数、越权对象、伪造成功和失败校验均零数据库调用；
- 执行服务不接收权限范围或自由 SQL，避免重新解释可信上下文；
- 数据库只读账号/事务继续作为 Validator 之后的第二道防线；
- 连接、超时、权限和资源错误不在本阶段进入 LLM 修复。

## 验证证据

- 执行契约和边界聚焦单元/安全测试：27 项通过；
- 真实 Pagila 普通 SELECT、CTE/聚合、合法空结果、1000 行截断、零执行拒绝和
  运行时错误归一化：6 项通过；
- Stage 1–6 单元测试：294 项通过；
- Stage 1–6 安全测试：46 项通过；
- Stage 1–6 集成测试：60 项通过；
- Stage 1 Connector 原有只读、超时取消、连接恢复和连接重试回归继续纳入全量
  集成门禁。

## 已知边界

Stage 3 规范 SQL 当前不强制把未限定表名改写成 `schema.table`。锁定 MVP 只有
Pagila `public` Schema，应用角色只拥有 `public` USAGE 和表 SELECT，且只读
事务不能创建遮蔽对象，因此当前执行路径不产生跨 Schema 越权。未来扩展到多个
可读 Schema 前，需要在 Validator 输出或 Connector 会话中绑定安全 Schema
解析规则。

## 延后

SQL attempt、指纹、修复计数和反思策略属于 Stage 7；LangGraph State、节点、
路由、通用异常 wrapper、FinalStatus 和基础设施重试观测属于 Stage 8；
FastAPI、Trace 和评测属于 Stage 9–10。
