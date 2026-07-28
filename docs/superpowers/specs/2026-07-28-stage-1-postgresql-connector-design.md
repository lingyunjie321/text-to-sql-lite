# 第一开发阶段：Pagila 与 PostgreSQL Connector 设计

## 目标

建立可复现的 PostgreSQL 16 + Pagila 测试环境，并实现后续 Text-to-SQL
流程可以复用的 PostgreSQL Connector 基础能力。

本阶段完成后，项目应能：

- 从经过启动校验的环境变量创建 Pagila 数据源连接池；
- 在数据库端只读事务中执行查询；
- 使用 30 秒 `statement_timeout`；
- 最多读取 1001 行，返回前 1000 行并正确标记截断；
- 将数据库值转换为 JSON 可序列化的稳定表示；
- 将驱动异常归一化为 SQLSTATE、项目错误类型、可重试标记和脱敏消息；
- 通过真实 PostgreSQL 16 上的本阶段 Connector 集成测试。

## 范围

### 包含

- Python 项目最小骨架和依赖配置；
- PostgreSQL 16 Docker Compose 服务；
- 固定 Pagila 快照的下载、校验与初始化；
- 管理员账号与只读应用账号分离；
- 数据库配置加载和启动校验；
- psycopg 3 连接池生命周期；
- 普通 `SELECT`、CTE、聚合和空结果执行；
- 只读事务、超时、行数上限、取消后的连接处理；
- 结果值规范化；
- SQLSTATE 错误分类与连接错误有限重试；
- 单元测试和真实数据库集成测试；
- Pagila 版本、来源、校验和与使用说明。

### 不包含

- Schema introspection 和版本指纹；
- SQLGlot AST 与安全策略；
- Schema Linking；
- LLM Provider 和 SQL 生成；
- Workflow、API、Trace 和离线评测；
- 对上层 SQL 修复次数或 Workflow State 的修改。

Schema introspection 是主规格开发顺序中的第二阶段，不在本阶段提前实现。

## Pagila 与 PostgreSQL 锁定策略

- PostgreSQL 固定为 Docker Official Image
  `postgres:16.14-bookworm@sha256:92620daddcd947f8d5ab5ba66e848702fe443d87fed30c4cea8e389fd78dfc55`。
- Pagila 使用官方仓库 `pagila-v3.1.0`：
  - 来源：`https://github.com/devrimgunduz/pagila`
  - commit：`fef9675714cfba1756df4719b5e36075a7ddf90e`
  - archive SHA-256：`6d0cf172e5d1896b5a279452060fb4cf9b2ca820366c712156fa1e656af4df88`
  - `pagila-schema.sql` SHA-256：
    `8ce358e4c8014087b85296694a0893887bd7a4190e3ce407f2721b86b98e5707`
  - `pagila-data.sql` SHA-256：
    `fb81bec377687c83e11d2a24916ae28656d85550bf0ada798305bf7e2af9823b`
- 初始化工具只接受校验和匹配的文件，避免上游内容变化造成静默漂移。
- 下载产物属于可重新生成的本地 fixture，不把大型上游 SQL 数据复制进项目源码。

若该快照不能在 PostgreSQL 16 正常初始化，按主规格暂停并报告，不能静默切换版本。

## 组件设计

### 配置

配置层只从环境变量读取凭据，提供以下数据库设置：

- 数据源 ID；
- PostgreSQL DSN；
- 连接池最小和最大连接数；
- 连接池获取超时；
- statement timeout，默认 30 秒；
- 最大结果行数，默认 1000；
- 连接类瞬时错误最大重试次数。

启动时校验必填值、正整数范围和固定 MVP 默认值。代码、示例配置和日志中不写入真实密码。

### Connector

`PostgreSQLConnector` 负责单个 datasource 的连接池。后续 Bootstrap 可以为每个
datasource 创建独立实例，从而保证连接池与凭据隔离，本阶段不增加多数据源注册中心。

一次执行调用遵循以下顺序：

1. 从连接池获取连接；
2. 开启 `READ ONLY` 事务；
3. 使用 `SET LOCAL statement_timeout` 设置数据库端超时；
4. 执行原始 SQL；
5. 读取至多 `max_result_rows + 1` 行；
6. 规范化列信息和结果值；
7. 提交只读事务并归还健康连接；
8. 将异常转换为统一错误。

只有 SQLSTATE class `08` 的瞬时连接错误可以在同一次 Connector 调用内有限重试。
重试复用相同 SQL，不生成新 attempt，也不接触 `repair_count`。

### 结果模型

Connector 返回独立于 psycopg 的结果对象，包含：

- 列名和 PostgreSQL 类型信息；
- 二维结果行；
- 实际返回行数；
- `truncated`；
- 数据库执行耗时。

值规范化规则：

- `NULL` → `None`；
- `Decimal` → 十进制字符串，避免 JSON 浮点精度丢失；
- `date`、`time`、`datetime` → ISO 8601 字符串；
- 有时区时间保留明确偏移；
- JSON/JSONB → JSON 兼容对象；
- UUID → 字符串；
- 数组和嵌套结构递归规范化。

### 错误模型

统一数据库错误包含：

- SQLSTATE；
- `ErrorType`；
- 稳定内部错误码；
- 是否可重试；
- 脱敏公开消息。

至少实现以下映射：

- `42601` → `SYNTAX_ERROR`；
- `42P01`、`42703`、`42702` → `SCHEMA_ERROR`；
- `42501` → `PERMISSION_DENIED`；
- `25006`（只读事务写入）→ `PERMISSION_DENIED`；
- SQLSTATE class `08` → `CONNECTION_ERROR`；
- `57014` → `TIMEOUT`；
- SQLSTATE class `53` → `RESOURCE_RISK`；
- 其他错误 → `UNKNOWN`。

错误对象不暴露 DSN、密码、原始堆栈或未脱敏数据库消息。

### 超时与连接安全

查询超时由 PostgreSQL `statement_timeout` 触发，确保取消发生在数据库端。发生异常后必须
回滚事务。若驱动不能确认连接已恢复到可用状态，则关闭该连接而不是归还连接池。

只读保护由数据库只读账号和 `READ ONLY` 事务共同提供。即使上层校验被绕过，写操作也应
被数据库拒绝。

## 测试设计

### 单元测试

- 配置缺失和非法数值；
- 每个 SQLSTATE 的稳定错误映射；
- 可重试判定；
- Decimal、日期、时间、时区、JSON、UUID、数组和 NULL 规范化；
- 行数截断判定；
- 脱敏错误不泄露凭据和原始查询。

### PostgreSQL 16 集成测试

- Pagila 初始化和连接成功；
- 认证失败、连接拒绝和连接池获取超时；
- 普通 SELECT、CTE、聚合和空结果；
- 1000 行边界与 1001 行截断；
- 数据类型规范化；
- 30 秒配置路径和短超时测试；
- 超时后查询确实被数据库取消，连接可安全复用或已被废弃；
- 只读账号及只读事务拒绝写操作；
- 连接类瞬时故障只重试相同调用。

本阶段不宣称完整 Connector Contract 已通过，因为其中的元数据读取属于第二阶段。测试报告
必须明确本阶段通过项和延期到第二阶段的项。

## 完成标准

- Pagila 固定快照能在 PostgreSQL 16 初始化；
- 快照来源、commit 和 SQL 文件校验和已记录；
- 配置、Connector、错误归一化和测试均已实现；
- 单元测试通过；
- Docker 中的本阶段集成测试通过；
- 没有实现本阶段范围外的生产模块；
- 三份受保护规格/Case 文件未被修改或加入后续提交。
