# 本地动态数据源阶段 3 设计

## 1. 目标与边界

本阶段把阶段 2 保存的 `DatasourceProfile` 接入真实 PostgreSQL/MySQL
Connector，并补齐连接测试、结构发现、授权校验和运行时生命周期。StarRocks
继续保持实验状态，不接入动态 Profile。

调用关系：

```text
API
→ DatasourceProfileService / DatasourceRuntimeService
→ LocalProfileStore + InMemoryCredentialStore
→ ConnectorFactory
→ RuntimeRegistry
→ ProfileScopedConnector
→ WorkflowContextFactory
→ Text-to-SQL Workflow
```

本阶段不实现动态模型 Provider、模型测试、Embedding 可选化、BM25-only、前端
设置页、凭据持久化或新数据库类型，也不修改 Workflow 图、节点、State、三次
修复规则、32 步限制、Schema Linking 算法、Comparator 或 Gold。

## 2. Metadata 发现与查询授权分离

metadata 与查询运行时使用两个用途严格分离的 Connector 路径：

```text
metadata 接口
└── 临时 raw_connector
    └── 只执行服务端固定结构发现逻辑，完成后立即关闭

DatasourceRuntime
├── raw_connector
│   └── 由 RuntimeRegistry 持有，不直接交给 API 或 Workflow
└── scoped_context
    └── ProfileScopedConnector
        └── 只接受 DatasourceProfile allowlist 内的授权子集
```

metadata 不复用查询 Runtime，因此即使已保存 allowlist 因数据库结构变化而失效，
用户仍可读取当前可发现结构并重新选择；查询 Runtime 仍会独立校验 allowlist 并
fail closed。

metadata 可发现范围不等于 AI 查询授权范围：

- metadata 可以返回数据库账号当前可见的全部非系统 Schema、表和视图。
- Workflow、Schema Linking、Prompt、SQL 校验和执行只能使用 Profile 中的
  `allowed_schemas`、`allowed_tables`。
- metadata 结果不自动修改 Profile。
- 新对象只有经用户显式 PUT 保存并通过在线校验后才进入查询授权。
- Scoped Connector 只接受 Profile allowlist 内由既有权限节点确定的非空 Schema
  子集，并要求该子集包含的表与 Profile 精确对应；数据库实际返回的关系集合必须
  与本次请求范围完全一致。任何扩大范围、空范围、失效对象或不匹配都 fail
  closed，不读取或回退到完整 metadata。

## 3. Metadata 数据与容量契约

新增接口：

```text
POST /api/v1/local/datasources/test
GET  /api/v1/local/datasources/{id}/metadata
```

连接测试接收数据库类型、Host、端口、数据库、用户名和 write-only 密码。请求只
用于临时 Connector，不保存 Profile、凭据或运行时。成功响应返回连接状态、可发现
Schema、表/视图摘要、容量限制和 `truncated`。

metadata 接口返回：

- Schema；
- 表或视图名称及类型；
- 字段名、字段类型和 nullable；
- 主键字段；
- 外键名称、源/目标表和字段；
- 容量限制和 `truncated`。

不返回样例数据、字段值、视图定义、存储过程、Trigger、唯一索引定义、凭据、
DSN、连接身份或原始驱动错误。

固定限制：

| 项目 | 上限 |
|---|---:|
| metadata 超时 | 30 秒 |
| 表/视图 | 500 |
| 字段 | 10,000 |
| 外键 | 5,000 |

关系按 Schema、名称和类型排序；字段按 ordinal position 和名称排序；主键、外键按
Schema、表和约束名排序。字段达到上限时在完整表/视图边界停止，外键在完整外键
对象边界停止。任一上限命中即返回 `truncated=true`。allowlist 精确校验直接查询
目标对象，不受展示上限影响。

PostgreSQL 排除 `pg_catalog`、`information_schema`、`pg_toast*`、
`pg_temp_*` 和 `pg_toast_temp_*`。MySQL 排除 `information_schema`、
`mysql`、`performance_schema` 和 `sys`。

## 4. Allowlist 在线校验

创建 DatasourceProfile 时，必须使用请求中的密码建立临时 Connector，确认连接
成功，并确认全部 `allowed_schemas`、`allowed_tables` 是当前账号可见的非系统
对象。缺少密码、连接失败或任一对象不可见时不保存 Profile。

PUT 规则：

- 只修改名称时不访问数据库。
- 修改 Host、端口、数据库、用户名、密码或 allowlist 时，先用候选配置和有效
  密码执行临时验证。
- 验证失败时保留原 Profile、凭据和运行时。
- 验证成功后先使旧运行时失效，再保存新 Profile 和凭据。
- 显式 `password: null` 可以清除密码并关闭旧运行时；Profile 保留，但后续动态
  查询和 metadata 返回凭据缺失。
- 应用重启后 Profile 保留、密码缺失，需要通过 PUT 重新输入。

## 5. RuntimeRegistry 生命周期

`RuntimeRegistry` 以 Profile ID 为键，按需创建并缓存 Connector 与
WorkflowContext：

- Connector 构造返回后、调用 `open()` 前即进入资源管理。
- 首次访问同一 Profile 的并发请求只创建一个运行时。
- 创建、打开、授权包装或 Context 组装任一步失败都关闭已创建 Connector，且不
  缓存失败项。
- 后续请求复用已建立的连接池。
- Profile 公开连接身份或 allowlist 与缓存项不一致时拒绝复用并重建。
- Profile 更新、密码变化或删除时关闭并移除对应运行时。
- 创建失败后下次请求可以重试。
- 应用退出时逆序关闭全部动态运行时；一个 close 失败不阻止其他资源关闭。
- 关闭错误只记录固定事件和安全 Profile ID，不记录异常文本或连接信息。

更新期间已经开始的旧查询允许因连接关闭而安全失败；不得切换到默认数据源。

## 6. Profile 解析与兼容

Profile Resolver 先加载 ModelProfile 和 DatasourceProfile。阶段 3 的模型仍必须
与现有静态模型路由公开身份一致，动态 Provider 留到阶段 4。

数据源解析顺序：

1. 如果 Profile 与阶段 2 已有静态 Context 的公开身份和 allowlist 精确一致，
   继续返回该静态 Context，保持兼容。
2. 否则由 RuntimeRegistry 按 Profile 和内存密码创建动态运行时。
3. 不存在、凭据缺失、连接失败或 Context 创建失败均直接返回对应错误，不回退到
   `.env` Context。

旧普通请求和 Override 路径保持原有行为。无静态数据库配置时允许应用启动并提供
Profile API；旧普通查询在这种情况下安全拒绝，不自动选择任意 Profile。模型和
Embedding 在阶段 4 前仍使用现有静态配置。

## 7. MySQL 安全与方言

MySQL 事务使用 `START TRANSACTION READ ONLY` 原子启动只读事务，不再先
`begin()` 后尝试修改事务特性。设置失败必须传播为脱敏数据库错误，用户 SQL 调用
为零；回滚失败的连接要关闭并从池中废弃。Docker 测试账号同时只授予 Sakila 的
读取权限，形成数据库层第二道边界。

查询 API 使用已有 `SQLTaskState.dialect` 字段，并从所选 Connector 的公开
`dialect_name` 注入 `postgres` 或 `mysql`。PostgreSQL Prompt 和版本保持不变；
新增独立 MySQL Prompt/版本，只描述 MySQL 和两种方言共同支持的安全函数。
SQLGlot 继续使用现有方言入口和安全策略。不修改 Workflow 节点或 State 定义。

MySQL metadata 查询分别渲染 Schema 和 Table 的占位符数量，支持一个 Schema 下
多张表，并区分表与视图。

## 8. 错误与脱敏

| HTTP | 错误码 | 场景 |
|---:|---|---|
| 404 | `DATASOURCE_PROFILE_NOT_FOUND` | Profile 不存在 |
| 409 | `DATASOURCE_CREDENTIAL_MISSING` | 当前进程没有密码 |
| 409 | `DATASOURCE_ALLOWLIST_INVALID` | 对象不存在、不可见或属于系统 Schema |
| 503 | `DATASOURCE_CONNECTION_FAILED` | 认证、拒绝连接或连接中断 |
| 504 | `DATASOURCE_METADATA_TIMEOUT` | metadata 超时 |
| 503 | `DATASOURCE_METADATA_UNAVAILABLE` | metadata 读取失败 |
| 503 | `DATASOURCE_RUNTIME_UNAVAILABLE` | 动态运行时无法建立 |

公开响应、OpenAPI、日志、Trace 和异常文本不得包含密码、完整 DSN、Host、用户名、
原始 SQL、驱动异常或数据库文件路径。metadata 固定查询和发现到的对象名不进入
日志或 Trace。

## 9. MySQL/Sakila 真实环境

使用锁定的 MySQL 8.4 镜像和 MySQL 官方 Sakila 归档。manifest 固定归档 URL、
版本说明、归档 SHA-256 以及 `sakila-schema.sql`、`sakila-data.sql` 的
SHA-256。首次使用前由工具下载和校验到被 Git 忽略的 fixture 目录。

Compose 初始化 Sakila 后撤销应用用户写权限并只授予需要的读取权限。真实测试至少
覆盖连接、非系统对象发现、字段、主键、外键、多表 metadata、只读写拒绝、超时、
行数截断和 MySQL Profile 查询链路。

## 10. 验收

- 原有 unit、security、Pagila integration、Python 全量和前端基线不回归。
- unit + security 分支覆盖率不低于 83%。
- MySQL/Sakila 真实测试在配置环境中全部通过，不新增无理由 skip。
- metadata 发现范围与 Workflow 授权范围有独立安全测试。
- 凭据缺失、连接失败、allowlist 无效和 metadata 超时使用不同稳定错误码。
- MySQL 只读设置失败时 fail closed，数据库只读账号拒绝写入。
- Profile 更新、删除和应用退出正确释放动态运行时。
- HTTP 旧路径、旧 JSON、Override 和 PostgreSQL/Pagila 行为保持兼容。
- Workflow 图、节点、State、修复规则、循环限制、Comparator 和 Gold 无修改。
- Gold 内容和 `16 verified / 2 draft` 状态保持不变。
- `compileall`、`pip check`、Compose config、干净安装和
  `git diff --check` 通过。
