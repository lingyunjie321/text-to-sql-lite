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

第六开发阶段已实现：

- 以同一可信授权快照重新运行 Stage 3，并要求校验结果完全一致的执行边界；
- 只执行 `ValidationResult.normalized_sql`，避免校验与执行 SQL 不一致；
- 无效、失败、旧策略或内部不一致结果零数据库调用；
- 成功结果/脱敏数据库错误严格二选一；
- 复用 Connector 的只读事务、30 秒超时、1000 行截断、取消和同 SQL 连接
  重试，不增加第二套重试；
- 普通查询、CTE/聚合、合法空结果、截断和运行时错误的真实 Pagila 集成测试。

第七开发阶段已实现：

- 可解析 SQL 的 SQLGlot PostgreSQL 稳定指纹和解析失败原文精确 SHA-256；
- attempt 0 与最多 attempt 1、2、3 三个不同修复；
- 重复 SQL 和 A→B→A 在重新校验/执行前终止；
- 每个 attempt 的校验结果、执行结果或脱敏数据库错误记录；
- 语法最小修复、Schema 重新 Linking、方言重生成和非修复错误的确定性路由；
- PG-MVP-018 字段错误经重新 Linking、完整校验和真实 Pagila 执行的修复回归。

第八开发阶段已实现：

- 固定 LangGraph 1.2.9，显式注册主规格要求的九个业务节点；
- Pydantic `SQLTaskState` 与 frozen `WorkflowContext` 分离业务状态和可信依赖；
- 请求预处理、静态权限、Linking、生成、校验、执行、反思、澄清和 Finalize
  完整闭环；
- 首次成功、合法空结果、一次到三次不同修复、重复 SQL 和澄清的确定性路由；
- 权限/危险 SQL 零执行，连接/超时/资源风险零 LLM 盲修；
- 最多 32 个业务节点步骤、120 秒总请求预算和 LangGraph recursion limit
  双重终止保护；
- Token、模型/Prompt 版本、attempt、节点耗时和唯一 `FinalStatus` 进入严格
  State；
- Connector 内部同调用连接重试会累计到 `infrastructure_retry_count`，不增加
  SQL repair count；
- Stub Provider + 真实 Pagila 的首次成功和 Schema 修复集成测试。

第九开发阶段已实现：

- 固定 FastAPI 0.139.2 和同步 `POST /api/v1/text-to-sql`；
- 严格 `QueryRequest`/`QueryResponse`、全部终态互斥和失败隐藏 SQL；
- 递归 JSON 结果类型和非 JSON 值 fail-closed，OpenAPI 不使用任意对象；
- 独立 request/trace UUID、固定可信身份和未授权 debug 的前置 403；
- 启动时强制加载数据库/模型配置、打开 Connector，关闭时安全回收；
- 启动前锁定 `pagila` datasource、`public` Schema 和 MVP 所需 13 张表的
  服务端 allowlist；
- 未知 datasource、Schema 扩权和依赖注入零 Provider/Connector 调用；
- 422 不回显非法输入；403、500 和公开错误脱敏，未知异常不返回堆栈、DSN
  或 Prompt；
- TestClient → Workflow → 真实 Pagila 的首次成功、合法空结果、一次修复和危险
  SQL 零执行集成测试。

第十开发阶段的工程实现已完成；当前发布资格为 `not_passed`：

- 不含问题、SQL、结果行、Prompt、DSN、API Key 或原始异常的安全 Trace；
- exact、multiset 和 keyed Comparator，以及列名对齐、重复数、NULL、Decimal
  容差、时区、JSON、grain 和截断结果检查；
- 严格的 18 条 Pagila JSONL Case loader、基线哈希和脱敏证据报告；
- Gold 与预测 SQL 使用同一 Validator、只读 Connector 和数据快照；
- 逐 Case evidence SHA-256、独立审核和单 Case 原子状态更新门；
- 冻结期从锁定视图定义提取、逐条审核并聚合的通用字段语义别名；
- 请求期仅使用外部 SHA-256 锚定的只读语义 manifest，不扫描视图；
- 代码、依赖、Python、Prompt、Provider、Comparator、Evidence、Report、
  模型非秘密配置、Schema、数据、Gold 和语义 manifest 的统一 baseline ID；
- 全 `draft` 精确 Gold 起点、Case 证据 baseline 绑定和跨基线重放拒绝。

此前 17/18 的候选运行已永久作废并移入 `evaluation/reports/invalidated/`，
不能用于状态更新。重新冻结后的正式候选完成真实模型、校验、只读执行、有限
修复和逐条审核，自动证据为 `12/18`，审核为
`12 approved / 6 rejected`。未发现可由非 Gold 证据证明的通用实现缺陷，
因此按终局规则不运行随机重试；当前 18 条 Gold 全部保持 `draft`。完整脱敏
证据见 `evaluation/reports/pagila_mvp_stage10.md`。

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
from app.execution import execute_validated_sql
from app.validation import validate_sql


result = validate_sql(
    "SELECT film_id, title FROM film",
    allowed_schemas=("public",),
    allowed_tables=("public.film",),
    snapshot=snapshot,
)
if result.is_valid:
    execution = execute_validated_sql(
        result,
        allowed_schemas=("public",),
        allowed_tables=("public.film",),
        snapshot=snapshot,
        connector=connector,
    )
```

`allowed_schemas`、`allowed_tables` 和 `snapshot` 必须来自同一份服务端可信授权
上下文。`is_valid` 为 false 时不得执行；失败结果不会返回部分 SQL、对象引用或
SQLGlot 原始错误。执行入口不接收第二份 SQL，只会使用当前策略校验结果中的
`normalized_sql`；执行前还会用传入的同一份服务端可信授权范围和 Snapshot
重新校验，防止公开结果工厂被伪造成安全凭证。返回值严格包含 `result` 或脱敏
`error` 之一。

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
进入 Connector。澄清结果不得执行。工作流只对顶层
直接列、`COUNT/SUM(普通列)` 和 `DATE_TRUNC` 的输出别名做确定性规范化，
并同步无歧义的 `GROUP BY/ORDER BY` 别名引用。它不读取 Case/Gold，不修复
不可解析 SQL、不改写 `COUNT(*)`，也不改变结果值。

## 运行 Workflow

```python
from app.workflow import (
    WorkflowContext,
    new_task_state,
    run_workflow,
)


state = new_task_state(
    request_id="request-id",
    trace_id="trace-id",
    question="列出前 10 部影片标题",
    datasource_id="pagila",
    requested_schemas=("public",),
)
result = run_workflow(
    state,
    context=WorkflowContext(
        provider=provider,
        connector=connector,
        datasource_id="pagila",
        allowed_schemas=("public",),
        allowed_tables=("public.film",),
    ),
)
```

`WorkflowContext` 中的数据源和授权范围必须来自服务端可信配置。客户端请求只能
缩小 Schema 范围，不能扩大表权限。Workflow 中每个生成或修复 SQL 都会重新
经过 Stage 3 校验和 Stage 6 执行边界；不要直接调用 Connector 执行模型输出。

## FastAPI 接口

标准 ASGI 应用目标为：

```text
app.main:app
```

ASGI server 启动 lifespan 时会读取 `.env.example` 所列的数据库和 LLM 环境
变量；缺少 DSN、模型或 API Key 时启动失败，不会进入 Stub 或宽松模式。部署
服务器不属于本 MVP 代码依赖，应由运行环境选择。

请求示例：

```json
{
  "question": "列出前 10 部影片标题",
  "datasource_id": "pagila",
  "schemas": ["public"],
  "debug": false
}
```

业务成功、澄清和拒绝均返回唯一 `status`。只有成功返回 SQL 和结果；所有失败
不返回当前或历史 SQL。普通固定身份的 `debug=true` 返回 403，任意 Header 都
不能提升 debug 权限。

## Pagila MVP 评测

锁定基线记录在 `evaluation/pagila_baseline.json`。旧 17/18 报告和明确的
作废说明位于 `evaluation/reports/invalidated/`；当前正式候选的结构化报告
和脱敏验收报告分别为 `evaluation/reports/pagila_mvp_stage10.json` 与
`evaluation/reports/pagila_mvp_stage10.md`。最终结果是工程完成、发布资格
`not_passed`：自动证据 `12/18`，独立审核
`12 approved / 6 rejected`，Gold `verified=0`。
基线同时锚定经逐条审核的
`infrastructure/pagila/view_semantics.json`、候选/审核账本摘要、原始和增强
`schema_version`、受控代码根、实际行为依赖版本、数据库非秘密执行参数、
非秘密模型配置及各契约版本。运行时数据
校验和来自
`pg_dump --data-only --no-owner --no-privileges`；PostgreSQL 每次生成的
`restrict/unrestrict` nonce 会先规范化为固定 `TOKEN`，其余内容不变。

代码与语义审核完成后，先重新冻结基线：

```bash
.venv/bin/python -m tools.run_pagila_evaluation freeze-baseline \
  --baseline evaluation/pagila_baseline.json \
  --output evaluation/pagila_baseline.json \
  --cases evaluation/cases/pagila_mvp.jsonl \
  --env-file .env
```

随后生成新的证据报告；此操作不会自动修改 Gold：

```bash
.venv/bin/python -m tools.run_pagila_evaluation evaluate \
  --cases evaluation/cases/pagila_mvp.jsonl \
  --baseline evaluation/pagila_baseline.json \
  --report evaluation/reports/pagila_mvp_stage10.json \
  --env-file .env
```

审核和状态更新是两个独立的单 Case 门。`review-case` 只在证据摘要有效且自动
结果通过时允许 `--approve`；`verify-case` 还会核对审核状态和 status-neutral
Gold 哈希，并只原子替换目标行的一个 `status` token。两个命令都必须显式提供
当前外部 baseline，且会先重算代码、语义和依赖冻结，旧报告不能跨 baseline
重放：

```bash
.venv/bin/python -m tools.run_pagila_evaluation review-case \
  --report evaluation/reports/pagila_mvp_stage10.json \
  --baseline evaluation/pagila_baseline.json \
  --case-id PG-MVP-001 --approve

.venv/bin/python -m tools.run_pagila_evaluation verify-case \
  --cases evaluation/cases/pagila_mvp.jsonl \
  --report evaluation/reports/pagila_mvp_stage10.json \
  --baseline evaluation/pagila_baseline.json \
  --case-id PG-MVP-001
```

不得使用脚本预先批量标记未执行或未审核的 Case。

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
.venv/bin/python -m compileall -q app evaluation tools tests
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
- Workflow 的 Provider、Connector、DSN 和完整 Prompt 不进入 State；
  澄清和公开错误使用固定、脱敏内容；
- Trace 和评测报告只保存白名单字段、稳定 code、计数和摘要，不保存问题、
  SQL、Prompt、行值、凭据或原始异常；
- Case 从 `draft` 更新为 `verified` 前必须同时通过真实执行/安全门、Gold
  Comparator、证据摘要和逐条审核；Gold 的问题、SQL、字段与比较规则不可由
  状态更新器修改；
- 第一阶段的只读账号和只读事务是数据库侧第二道防线，不替代上层校验。
