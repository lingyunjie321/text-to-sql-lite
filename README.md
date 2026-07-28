# Text-to-SQL Agent

当前仓库正在按 MVP 规格重新实现 PostgreSQL + Pagila 的安全
Text-to-SQL 闭环。

第一开发阶段已实现：

- 固定 PostgreSQL 16.14 和 Pagila 3.1.0 快照；
- 环境变量配置与启动校验；
- psycopg 3 连接池；
- 数据库强制只读执行；
- 30 秒默认超时、1000 行返回上限和截断标记；
- PostgreSQL 值的 JSON 稳定表示；
- SQLSTATE 错误归一化、脱敏和有限连接重试；
- 单元测试与真实 PostgreSQL 集成测试。

第二开发阶段已实现：

- 授权范围内的 Schema、表、字段、类型、nullable 和注释读取；
- 复合 PK/FK、unique constraint 和独立 unique index 读取；
- 固定参数化 `pg_catalog` 查询和只读一致性快照；
- 与 psycopg 解耦的不可变元数据模型；
- 规范 JSON 的确定性 `schema_version` SHA-256 指纹；
- 查询与组装两层授权过滤、公开安全错误和连接类有限重试；
- 单元测试与真实 Pagila Metadata Contract 集成测试。

第三开发阶段已实现：

- 锁定 SQLGlot 30.13.0，并只使用 PostgreSQL 方言解析和序列化；
- 单 statement、只读 `SELECT`/受控 CTE 和危险 AST 默认拒绝；
- `SELECT *` 拒绝，`COUNT(*)` 作为明确聚合特例允许；
- 授权 Schema/表、快照对象和字段存在性校验；
- 别名、CTE、派生表和相关子查询作用域解析；
- 主规格 `mvp-v1` 函数白名单，未知函数和 UDF 默认拒绝；
- 结构化、可路由且不泄露 SQL 或对象名的校验结果；
- 完整 P0 安全矩阵和真实 Pagila Gold SQL 校验回归。

Schema Linking 属于第四阶段，尚未实现。

## 本地准备

需要：

- Python 3.12；
- Docker Desktop 和 Docker Compose 5；
- 可访问 GitHub 以首次下载锁定 Pagila 快照。

创建环境并安装依赖：

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -e '.[test]'
```

下载并校验 Pagila：

```bash
.venv/bin/python tools/fetch_pagila.py \
  --manifest infrastructure/pagila/manifest.json \
  --output tests/fixtures/pagila/upstream
```

下载的 SQL 文件属于可再生成的本地 fixture，已被 Git 忽略。

## 启动 PostgreSQL

在当前终端创建仅用于本地开发的临时凭据：

```bash
export PAGILA_POSTGRES_PASSWORD="$(openssl rand -hex 24)"
export PAGILA_APP_USER="text_to_sql_reader"
export PAGILA_APP_PASSWORD="$(openssl rand -hex 24)"
export PAGILA_HOST_PORT="55432"
export TEXT_TO_SQL_DATABASE_DSN="postgresql://${PAGILA_APP_USER}:${PAGILA_APP_PASSWORD}@127.0.0.1:${PAGILA_HOST_PORT}/pagila"
```

启动并等待健康检查：

```bash
docker compose -f infrastructure/pagila/compose.yaml config --quiet
docker compose -f infrastructure/pagila/compose.yaml up -d --wait
```

数据库首次创建时会导入锁定 Pagila 数据，并创建只读应用角色。

## 读取授权元数据

```python
from app.config import load_database_settings
from app.connectors.postgresql import PostgreSQLConnector


settings = load_database_settings()
with PostgreSQLConnector(settings) as connector:
    snapshot = connector.read_metadata(
        ("public",),
        ("public.film", "public.language"),
    )
```

`allowed_schemas` 和 `allowed_tables` 必须来自服务端可信授权结果。不得根据
用户问题文本扩大范围。表名必须使用 `schema.table` 形式；任一授权范围为空时
返回确定性的空快照，不扫描数据库中其他可见对象。

## 校验 SQL

```python
from app.validation import validate_sql


result = validate_sql(
    "SELECT film_id, title FROM film",
    allowed_schemas=("public",),
    allowed_tables=("public.film",),
    snapshot=snapshot,
)
if result.is_valid:
    execution = connector.execute(result.normalized_sql)
```

`allowed_schemas`、`allowed_tables` 和 `snapshot` 必须来自同一份服务端可信授权
上下文。`is_valid` 为 false 时不得执行；失败结果不会返回部分 SQL、对象引用或
SQLGlot 原始错误。

## 运行测试

单元测试不需要数据库：

```bash
.venv/bin/pytest tests/unit -v
```

集成测试要求上述容器正在运行，且同一终端仍保留
`TEXT_TO_SQL_DATABASE_DSN`：

```bash
.venv/bin/pytest tests/integration -v -m integration
```

运行确定性检查：

```bash
.venv/bin/python -m compileall -q app tools tests
docker compose -f infrastructure/pagila/compose.yaml config --quiet
```

## 停止服务

正常停止不会删除 Pagila 数据卷：

```bash
docker compose -f infrastructure/pagila/compose.yaml down
```

不要把删除数据卷作为日常 teardown。只有确认不再需要本地 Pagila 数据时，
才应单独决定是否删除该命名卷。

## 安全说明

- 不要把真实 DSN 或密码写进 `.env.example`、源码、提交或日志；
- Connector 不负责 SQL 安全解析；所有模型 SQL 必须先经过
  `app.validation.validate_sql()`；
- 第一阶段的只读账号和只读事务是数据库侧第二道防线，不替代上层校验。
