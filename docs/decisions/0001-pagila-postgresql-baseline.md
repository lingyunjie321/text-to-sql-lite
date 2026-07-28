# ADR 0001：Pagila 与 PostgreSQL 基线

## 状态

已验证，2026-07-28。

## 决策

第一开发阶段使用以下固定基线：

- Python 3.12；
- PostgreSQL Docker Official Image
  `postgres:16.14-bookworm@sha256:92620daddcd947f8d5ab5ba66e848702fe443d87fed30c4cea8e389fd78dfc55`；
- Pagila `pagila-v3.1.0`，commit
  `fef9675714cfba1756df4719b5e36075a7ddf90e`；
- psycopg 3.3.4、psycopg-pool 3.3.1、pydantic-settings 2.14.2
  和 pytest 9.1.1。

Pagila 校验和：

| 产物 | SHA-256 |
|---|---|
| GitHub archive | `6d0cf172e5d1896b5a279452060fb4cf9b2ca820366c712156fa1e656af4df88` |
| `pagila-schema.sql` | `8ce358e4c8014087b85296694a0893887bd7a4190e3ce407f2721b86b98e5707` |
| `pagila-data.sql` | `fb81bec377687c83e11d2a24916ae28656d85550bf0ada798305bf7e2af9823b` |

使用 `pagila-data.sql`，因为它是该锁定版本中与
`pagila-schema.sql` 配套的 COPY 数据集；不使用另一套 INSERT
数据文件，避免初始化路径和数据表示出现两套基线。

## 权限边界

管理员角色只用于容器初始化和验证。应用角色
`text_to_sql_reader` 仅有连接、`public` Schema 使用权和表读取权，
并设置 `default_transaction_read_only=on`。Connector 每次执行还会显式
开启只读事务，形成账号和事务两层保护。

凭据只通过环境变量进入 Compose 和 Connector，不写入源码、示例配置、
异常或日志。

## Connector 基线

- 每个 `PostgreSQLConnector` 管理一个数据源连接池；
- 默认数据库端 `statement_timeout` 为 30 秒；
- 最多读取 1001 行，只返回前 1000 行并设置 `truncated`；
- Decimal 使用字符串表示，日期、时间和时间戳使用 ISO 8601；
- SQLSTATE 决定错误类型，只有 class `08` 连接错误允许同 SQL 有限重试；
- libpq 在认证握手失败时不提供顶层 SQLSTATE，Connector 仅对其标准
  `password authentication failed` 握手响应补记 `28P01`，已建立连接后的
  数据库错误仍完全由 SQLSTATE 分类；
- 超时由 PostgreSQL 取消，事务回滚后连接必须能恢复，否则由连接池替换。

## 验证证据

- PostgreSQL 报告版本 `16.14 (Debian 16.14-1.pgdg12+1)`；
- Pagila `film` 行数为 1000；
- 应用角色报告 `default_transaction_read_only=on`；
- 应用角色读取 `film` 成功；
- INSERT 被数据库以只读事务拒绝，测试记录未写入；
- 70 项单元测试通过；
- 11 项真实 PostgreSQL Connector 集成测试通过；
- 1 秒测试超时后 `SELECT 1` 成功，且没有残留 `pg_sleep` 查询；
- 1001 行查询只返回 1000 行并标记截断。

## 延后到第二阶段

Schema、表、字段、类型、nullable、注释、PK、FK、unique
constraint/index 和 `schema_version` 指纹读取属于第二开发阶段。本阶段
不宣称包含该部分的完整 Connector Contract 已通过。
