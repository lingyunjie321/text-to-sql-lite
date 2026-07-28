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

第四开发阶段已实现：

- Unicode NFKC、snake_case/camelCase 分词和确定性 BM25；
- 表名、字段名、显式 aliases 和 comments 检索；
- 字段命中向表聚合，固定 `Top-K=10`；
- 授权过滤先于索引统计、评分、FK 建图和版本计算；
- 授权 FK 图的确定性最短路径和必要中间表扩展；
- 不可变候选表、候选字段和 JOIN Path 契约；
- 无命中窄授权 fallback 和授权视图 `schema_version`；
- 真实 Pagila Gold Case 的表字段召回集成测试。

第五开发阶段已实现：

- 单模型 OpenAI-compatible `LLMProvider` 协议；
- 无厂商 SDK 的标准库 `chat/completions` 实现；
- `GeneratedSQL` 的 SQL/澄清严格二选一结构输出；
- 同版本授权候选、字段、PK/FK 和 JOIN Path 的确定性 Prompt；
- 固定 `temperature=0`、1～30 秒可配置（默认 30 秒）的超时和 1 MiB 响应上限；
- 禁止 HTTP redirect、API key 控制字符和原始 Provider 错误泄漏；
- Token usage、模型标识和 Prompt 版本统一结果；
- 生成后串联 Stage 3 安全校验的 Stub/协议集成测试。

真实执行编排属于第六阶段，尚未实现。

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

## 关联 Schema

```python
from app.schema_linking import link_schema


linking = link_schema(
    "列出影片标题和语言名称",
    allowed_schemas=("public",),
    allowed_tables=("public.film", "public.language"),
    snapshot=snapshot,
)
```

Linker 只使用传入的可信授权快照，不查询数据库，也不会根据问题扩大权限。
`candidate_tables` 最多包含 10 张表，`candidate_fields` 提供这些表的完整字段
上下文，`join_paths` 只包含授权快照中的真实 FK。调用方不得把不同
`schema_version` 的候选和快照混用。

## 生成 SQL

LLM 配置使用 `.env.example` 中的 `LLM_*` 变量名。API key 只放在被 Git
忽略的本地环境或 Secret 管理中，不要写入源码、README、提交或日志。

```python
from app.config import load_llm_settings
from app.generation import (
    GenerationContext,
    OpenAICompatibleLLMProvider,
    generate_sql,
)


llm_settings = load_llm_settings()
provider = OpenAICompatibleLLMProvider(llm_settings)
generated = generate_sql(
    GenerationContext(
        question="列出影片标题和语言名称",
        normalized_question="列出影片标题和语言名称",
        normalized_time=None,
        dialect="postgres",
        schema_linking=linking,
        snapshot=snapshot,
    ),
    provider=provider,
)
```

`snapshot` 必须是生成 `linking` 的同一授权快照。模型返回 SQL 时，调用方仍须
使用原始可信权限和该快照调用 `validate_sql()`；只有校验成功的规范 SQL 才能
进入 Connector。澄清结果不得执行。

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
- Schema Linking 的候选不是新的授权结果；后续 SQL 校验仍必须使用原始可信
  `allowed_schemas`、`allowed_tables` 和同版本快照；
- Prompt 和结构化输出不是安全边界；模型 SQL 无论看起来是否只读，都必须通过
  `app.validation.validate_sql()`，Provider 错误不得记录完整请求或响应；
- 第一阶段的只读账号和只读事务是数据库侧第二道防线，不替代上层校验。
