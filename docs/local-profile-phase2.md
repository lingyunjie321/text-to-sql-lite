# 本地 Profile 阶段 2 设计

## 1. 目标与边界

本阶段只建立本地 Profile、非敏感持久化、进程内凭据和
Profile-ID 查询路径。它不创建动态 Connector 或 Provider，不修改
Workflow、Schema Linking、Prompt、模型路由、Embedding 必需行为或 SQL
安全边界。

调用关系：

```text
API
→ ModelProfileService / DatasourceProfileService
→ LocalProfileStore + InMemoryCredentialStore
→ ProfileResolver
→ 现有静态 WorkflowContext
→ Text-to-SQL Workflow
```

## 2. Profile 模型

`ModelProfile` 保存：

```text
id
name
provider_type
base_url
model_name
embedding_base_url（可选）
embedding_model（可选）
```

`DatasourceProfile` 保存：

```text
id
name
database_type
host
port
database
username
allowed_schemas
allowed_tables
```

Profile 使用严格 Pydantic 模型，禁止额外字段。ID 是不可变的小写
ASCII slug。本阶段新建 Profile 只允许 `openai_compatible` 模型和
`postgresql/mysql` 数据库；现有 StarRocks 静态兼容仍是实验能力。

Profile 中不存在 API Key、密码、DSN、连接池参数、模型路由或
运行时对象。

## 3. SQLite Store

默认文件为 `~/.text-to-sql-lite/config.db`。测试必须注入临时路径。
导入模块时不创建目录或文件。

- 使用 Python 标准库 `sqlite3`，不引入 ORM。
- 数据库版本使用 `PRAGMA user_version=1`。
- 空库自动初始化；未知版本 fail closed，不引入通用迁移框架。
- allowlist 使用标准 JSON 字符串，读取后重新经过 Profile 验证。
- 所有值都使用 `?` 参数绑定；表名和列名是代码常量。
- 写入使用显式事务和进程内锁，每次操作自行关闭 connection。
- 锁、损坏和 I/O 失败映射为固定错误码，不返回 SQL、路径或原始
  SQLite 异常。

## 4. 内存凭据

`InMemoryCredentialStore` 由 FastAPI lifespan 持有一个单例：

```text
model_profile_id      → generation_api_key / embedding_api_key
datasource_profile_id → password
```

规则：

- 创建 Profile 可以不提供凭据，状态为 `missing`。
- Replace 请求未提供凭据时保留旧值；显式 `null` 时清除。
- 模型 endpoint/provider 或数据源 host/port/database/username 变化且
  没有新凭据时，清除旧凭据。
- 只修改 name 或 allowlist 不清除凭据。
- 删除 Profile 后清除对应凭据；应用退出时执行 `clear_all()`。
- 重启后 Profile 保留，凭据不保留。不宣称 Python 字符串可物理擦除。

## 5. API 契约

CRUD 端点：

```text
POST   /api/v1/local/models
GET    /api/v1/local/models
GET    /api/v1/local/models/{id}
PUT    /api/v1/local/models/{id}
DELETE /api/v1/local/models/{id}

POST   /api/v1/local/datasources
GET    /api/v1/local/datasources
GET    /api/v1/local/datasources/{id}
PUT    /api/v1/local/datasources/{id}
DELETE /api/v1/local/datasources/{id}
```

POST 返回 201，GET/PUT 返回 200，DELETE 返回 204。Secret 字段是
write-only，响应只返回 `configured`/`missing`/`not_applicable` 状态。

新标准查询：

```json
{
  "question": "统计每个月的订单金额",
  "datasource_id": "local-postgres",
  "model_profile_id": "local-model"
}
```

没有 `model_profile_id` 时使用原有查询路径。Profile 模式与 Override 模式
互斥。成功查询的响应 JSON 不改变。

## 6. 静态 runtime 绑定

阶段 2 不建立 `RuntimeRegistry`。`ProfileResolver` 只能返回 Bootstrap
已创建的静态 `WorkflowContext`和模型路由。

- 数据源 Profile ID 必须与已启动 Context ID 一致，且公开连接身份和
  allowlist 必须匹配。
- 模型 Profile 必须与当前基础 LLM 的公开身份匹配。现有
  simple/standard/complex 路由和 fallback 保持不变。
- 未匹配或未绑定返回 `PROFILE_RUNTIME_UNAVAILABLE`，在进入 Workflow 前
  终止。
- 不得因为 Profile 不可用而回退到默认 Context 或默认模型。

## 7. 错误与脱敏

| HTTP | 错误码 | 场景 |
|---:|---|---|
| 404 | `MODEL_PROFILE_NOT_FOUND` / `DATASOURCE_PROFILE_NOT_FOUND` | Profile 不存在 |
| 409 | `PROFILE_ALREADY_EXISTS` | 创建重复 ID |
| 409 | `PROFILE_RUNTIME_UNAVAILABLE` | 未绑定现有静态 runtime |
| 503 | `PROFILE_STORE_UNAVAILABLE` | Store 无法安全读写 |

公开错误使用固定消息，不回显 Profile 内容、数据库路径、SQL、
驱动异常、Host、URL、用户名或凭据。

凭据状态会通过 CRUD 响应显示为 `configured` 或 `missing`，但阶段 2 的查询只
绑定启动时已经持有自身凭据的静态 runtime，因此不会把 Profile 内存凭据作为
重复的执行前置条件。阶段 3/4 创建动态 runtime 时，再由对应服务返回明确的凭据
缺失错误。

## 8. 迁移与后续阶段

- 这是第一个 SQLite Profile Schema，无存量数据迁移。
- 不自动导入 `.env`、`datasources.json` 或 localStorage。
- 动态 Connector、替换/删除连接池和失败重建属于阶段 3。
- 动态 Provider、单模型默认路由、模型测试和可选 Embedding 属于阶段 4。
- 前端 Profile 设置和 localStorage 凭据清理属于阶段 5。
