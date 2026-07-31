# Text-to-SQL Agent

一个以安全执行为核心的 Text-to-SQL 工程实现：接收自然语言问题，在服务端授权
范围内检索 Schema，调用 OpenAI-compatible 模型生成 SQL，经 SQLGlot 校验后，
只读执行 PostgreSQL 查询并返回结构化结果。

当前仓库面向本地开发、架构研究和评测复现。生产启动配置固定使用
PostgreSQL 16.14、Pagila 3.1.0、`public` Schema 和 13 张授权表；它尚不是支持
任意数据库即插即用的生产服务。当前成熟度、验证证据和后续路线图见
[RELEASE.md](RELEASE.md)。

## 主要能力

- **完整请求闭环**：自然语言问题 → 权限解析 → Schema Linking → SQL 生成 →
  AST 校验 → 只读执行 → 有限修复 → 结构化响应。
- **检索与路由**：确定性 BM25、OpenAI-compatible Embedding、RRF 融合、
  可解释 Rerank，以及显式 `ComplexityRouteNode` 驱动的动态 Top-K
  （5/10/20）。
- **服务端模型路由**：按 `simple`、`standard`、`complex` 路由选择模型和
  上下文预算，可为批准的数据边界配置受限 fallback；客户端不能指定模型、
  复杂度或 Top-K。
- **SQL 安全门**：只接受单条只读 `SELECT` 或受控 CTE；校验授权对象、字段、
  函数、通配符和危险 AST；模型输出、修复 SQL 都必须重新校验。
- **数据库执行边界**：PostgreSQL 只读账号和只读事务、最长 30 秒、最多
  1000 行、连接类有限重试、公开错误脱敏。
- **有限反思修复**：初始 SQL 后最多三次不同修复，使用 SQL 指纹阻止重复和
  A→B→A 循环，权限和资源风险不会交给模型盲修。
- **API 与可观测性**：同步 FastAPI 接口、请求/Trace ID、节点耗时、Token、
  检索与路由摘要；Trace 不保存问题、SQL、Prompt、结果行或凭据。
- **可复现评测**：锁定 Pagila 快照、18 条 MVP Case、结果 Comparator、基线
  冻结、逐 Case 审核和 Gold 状态更新门。

## 请求链路

```mermaid
flowchart LR
    A["POST /api/v1/text-to-sql"] --> B["RequestPreprocess"]
    B --> C["PermissionResolve"]
    C --> D["SchemaLinking<br/>probe K=20"]
    D --> E["ComplexityRoute"]
    E --> F["SchemaLinking<br/>materialize K=5/10/20"]
    F --> G["GenerateSQL"]
    G --> H["ValidateSQL"]
    H --> I["ExecuteSQL"]
    I --> J["Finalize"]
    H -->|可修复错误| K["ReflectSQL"]
    K -->|Schema 错误| D
    K -->|语法/方言错误| G
    B -->|语义不唯一| L["Clarification"]
    L --> J
```

同一检索周期的探测和物化复用同一个授权快照。授权过滤发生在 BM25 统计、
Embedding 文档构建、融合、Rerank 和 Prompt 之前；Schema、语义、Embedding
配置或检索策略版本不匹配时，旧索引会被拒绝。

## 环境要求

- Python `>=3.12,<3.15`
- Docker Desktop 或兼容的 Docker Engine + Compose
- 首次获取 Pagila fixture 时能够访问 GitHub
- 一个 OpenAI-compatible Chat Completions 服务
- 一个 OpenAI-compatible Embeddings 服务
- 一个 ASGI server（例如 Uvicorn；本项目不把部署服务器固定为运行时依赖）
- 完整仓库检出；当前 wheel 不包含 `evaluation/`、`infrastructure/` 和运行所需
  的语义 manifest，不能脱离仓库独立部署

## 快速开始

### 1. 安装项目

```bash
git clone https://github.com/lingyunjie321/text-to-sql-lite.git
cd text-to-sql-lite

python3.12 -m venv .venv
.venv/bin/python -m pip install -e '.[test]'
```

### 2. 获取锁定的 Pagila 数据

```bash
.venv/bin/python tools/fetch_pagila.py \
  --manifest infrastructure/pagila/manifest.json \
  --output tests/fixtures/pagila/upstream
```

下载工具会校验归档和 SQL 文件的 SHA-256。生成的 fixture 目录已被 Git 忽略。

### 3. 配置本地环境

复制模板，并只在本地 `.env` 中填写凭据：

```bash
cp .env.example .env
```

最小配置如下。示例中的值都是占位符，不要把真实密码或 API Key 提交到仓库。

```dotenv
PAGILA_POSTGRES_PASSWORD=replace-with-local-admin-password
PAGILA_APP_USER=text_to_sql_reader
PAGILA_APP_PASSWORD=replace-with-local-reader-password
PAGILA_HOST_PORT=55432

TEXT_TO_SQL_DATABASE_DATASOURCE_ID=pagila
TEXT_TO_SQL_DATABASE_DSN=postgresql://text_to_sql_reader:replace-with-local-reader-password@127.0.0.1:55432/pagila

LLM_BASE_URL=https://your-provider.example/v1
LLM_API_KEY=replace-with-llm-key
LLM_MODEL=replace-with-chat-model

EMBEDDING_BASE_URL=https://your-provider.example/v1
EMBEDDING_API_KEY=replace-with-embedding-key
EMBEDDING_MODEL=text-embedding-v4
EMBEDDING_DIMENSION=1024
```

`LLM_BASE_URL` 和 `EMBEDDING_BASE_URL` 是 API 根地址；Provider 会分别追加
`/chat/completions` 和 `/embeddings`。远程地址必须使用 HTTPS，回环测试地址
可以使用 HTTP。

默认情况下，三个复杂度路由都继承基础 `LLM_*` 配置。若要使用不同模型，在
`.env.example` 所列的 `LLM_SIMPLE_*`、`LLM_STANDARD_*`、
`LLM_COMPLEX_*` 中覆盖相应字段。Fallback 至少要覆盖一个使其区别于主模型的
`LLM_FALLBACK_*` 字段，其余字段继承基础配置；override 和至少一个对应的
`MODEL_ROUTING_*_FALLBACK_ENABLED` 开关必须同时存在，且启用路由的输入/输出
预算必须一致，否则启动失败。

### 4. 启动 Pagila

```bash
docker compose -f infrastructure/pagila/compose.yaml config --quiet
docker compose -f infrastructure/pagila/compose.yaml up -d --wait
```

首次创建数据卷时会导入 Pagila，并创建由 `.env` 指定的只读应用角色。
初始化脚本只在命名卷首次创建时运行；之后修改 `.env` 中的角色或密码不会自动
更新已有卷。

Compose 当前没有把宿主机端口显式绑定到 `127.0.0.1`，Docker 可能将 55432
发布到所有网络接口。只应在受信开发机或有防火墙保护的环境运行，不要把该
数据库端口暴露到不可信网络。

### 5. 启动 API

项目导出标准 ASGI 应用 `app.main:app`。可以使用现有部署环境中的任意 ASGI
server；以下以 Uvicorn 为例：

```bash
.venv/bin/python -m pip install uvicorn
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Uvicorn 只是启动示例，未写入 `pyproject.toml`，也不属于当前资格冻结；正式
部署应自行固定和验证 ASGI server 版本。

生产容器化部署（含 `Dockerfile` 构建、环境契约、升级与回滚预案）见
[部署与回滚](docs/部署与回滚.md)。

启动时会加载 `.env`、连接数据库、读取授权元数据、校验锁定语义 manifest，
并创建 LLM/Embedding runtime。缺少必需配置时进程会 fail closed。

### 6. 发起查询

```bash
curl --fail-with-body \
  --request POST \
  --header 'Content-Type: application/json' \
  --data '{
    "question": "列出前 10 部影片的编号和标题",
    "datasource_id": "pagila",
    "schemas": ["public"],
    "debug": false
  }' \
  http://127.0.0.1:8000/api/v1/text-to-sql
```

成功响应包含：

- `status`：`SUCCEEDED_FIRST_PASS` 或 `SUCCEEDED_REPAIRED`
- `sql`：通过安全门并实际执行的规范 SQL
- `columns`、`rows`、`returned_row_count` 和 `truncated`
- `attempts` 和 `repair_count`
- 独立的 `request_id` 和 `trace_id`

需要澄清时返回 `CLARIFICATION_REQUIRED` 和结构化 `clarification`；拒绝或
失败时只返回脱敏 `error`，不会返回当前或历史 SQL。交互式 OpenAPI 文档默认
位于 `http://127.0.0.1:8000/docs`。

## 配置说明

| 配置组 | 用途 | 关键约束 |
|---|---|---|
| `PAGILA_*` | Docker 初始化和端口 | 密码必须只保存在本地或 Secret 管理中 |
| `TEXT_TO_SQL_DATABASE_*` | 数据源、连接池、超时和行数 | 当前数据库名必须为 `pagila`；超时 ≤ 30 秒；行数 ≤ 1000 |
| `LLM_*` | 基础 Chat Completions Provider | `temperature=0`；远程 URL 必须为 HTTPS |
| `LLM_SIMPLE_*` / `STANDARD_*` / `COMPLEX_*` | 路由级模型覆盖 | 未设置的路由完整继承基础配置 |
| `LLM_FALLBACK_*` | 可选备用模型 | 必须与启用开关、上下文预算和数据边界一致 |
| `MODEL_ROUTING_*` | 数据边界和 fallback 策略 | 只由服务端配置，客户端不能覆盖 |
| `EMBEDDING_*` | Embedding Provider、维数和批量限制 | 当前批量上限 64，响应上限 4 MiB，超时 ≤ 10 秒 |

完整变量和默认值见 [.env.example](.env.example)。

## API 约束

`POST /api/v1/text-to-sql` 的请求字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `question` | string | 必填，去除首尾空白后 1～2000 字符 |
| `datasource_id` | string | 默认 `pagila`；生产 Bootstrap 只接受 `pagila` |
| `schemas` | string[] | 可缩小服务端授权 Schema，不能扩大权限 |
| `debug` | boolean | 默认 `false`；当前固定身份没有 debug 权限 |

API 不接受 SQL、表 allowlist、复杂度、Top-K、模型、Prompt 或超时参数。这些
都属于服务端可信上下文。

业务成功、澄清和业务失败通常都以 HTTP 200 返回，并由响应内的 `status`
区分；未授权 `debug=true` 返回 403，请求体校验失败返回 422，未处理的服务
边界异常返回 500。当前没有独立的认证、Session 或健康检查端点。

## 安全边界

- 生产 Bootstrap 当前只授权 Pagila 的 `public` Schema 和 13 张固定表。
- 默认身份是代码内固定的 `mvp-fixed-user`，没有认证或多租户隔离；即使 API
  示例只绑定回环地址，也不要把服务直接暴露到不可信网络。
- 所有模型生成、修复或其他来源的 SQL 都必须重新经过权限、SQLGlot AST、
  函数策略和执行边界。
- Prompt、Schema 候选和结构化模型输出不是安全凭证。
- 数据库账号与事务都应保持只读；Connector 的只读约束是第二道防线，不替代
  AST 校验。
- Trace 和评测报告使用白名单字段与摘要，不应记录问题、SQL、Prompt、结果行、
  DSN、API Key、原始 Provider 响应或向量。
- `.env` 已被 Git 忽略。提交前仍应执行独立的敏感信息检查。

## 测试

单元和安全测试不需要外部模型或数据库：

```bash
PYTHONDONTWRITEBYTECODE=1 \
  .venv/bin/pytest -q -p no:cacheprovider tests/unit tests/security
```

完整集成测试要求锁定的 Pagila 服务正在运行，并且当前进程能读取
`TEXT_TO_SQL_DATABASE_DSN`。测试 fixture 不会自动加载 `.env`，必须把同一
只读 DSN 显式导出到 pytest 进程。Provider 协议测试使用本地确定性服务，不会
调用真实外部模型：

```bash
export TEXT_TO_SQL_DATABASE_DSN='postgresql://text_to_sql_reader:replace-with-local-reader-password@127.0.0.1:55432/pagila'
PYTHONDONTWRITEBYTECODE=1 \
  .venv/bin/pytest -q -p no:cacheprovider tests/integration
```

其他静态检查：

```bash
.venv/bin/python -m compileall -q app evaluation tools tests
.venv/bin/python -m pip check
docker compose -f infrastructure/pagila/compose.yaml config --quiet
git diff --check
```

Pagila 正式评测会调用真实模型、Embedding 和数据库，并受冻结基线约束；不要
把它当作普通 smoke test，也不要为迎合结果修改 Gold。查看可用命令：

```bash
.venv/bin/python -m tools.run_pagila_evaluation --help
```

新的 Stage 1 正式候选必须使用新的报告文件，不能覆盖或与历史 Stage 10 报告
交叉执行审核/状态更新。

## 停止本地环境

```bash
docker compose -f infrastructure/pagila/compose.yaml down
```

该命令保留 Pagila 命名卷。不要把删除数据卷作为日常 teardown；只有确认不再
需要本地数据后再单独处理。

## 项目结构

```text
app/
  api/              FastAPI 契约、Bootstrap 和响应映射
  connectors/       PostgreSQL、元数据、只读执行和锁定语义
  schema_linking/   BM25、Embedding、RRF、Rerank 和版本化索引
  generation/       Prompt、OpenAI-compatible Provider、模型路由与上下文裁剪
  validation/       SQLGlot AST、对象和函数安全策略
  execution/        校验后执行边界
  reflection/       SQL 指纹、修复策略和循环终止
  workflow/         LangGraph State、十种节点和条件路由
  observability/    脱敏 Trace 模型与采集
evaluation/         Case、Comparator、基线冻结、报告和审核工具
infrastructure/     锁定 Pagila Compose、初始化和语义 manifest
tests/              unit、security 和 integration 测试
tools/              Pagila fixture 与正式评测命令
docs/               主规格、验收规格、ADR、设计和实施记录
```

## 项目状态与路线图

核心 PostgreSQL/Pagila MVP 闭环已实现，增强阶段 1 的确定性实现和本地集成已
建立，但完整真实环境资格仍为 `not_passed`。业务知识与 Few-shot、Session /
Checkpoint / Memory、多数据库与跨源查询、缓存与生产治理属于后续必做阶段，
当前版本均不能宣称已支持。

详细完成项、验证结果、已知限制和推荐推进顺序见 [RELEASE.md](RELEASE.md)；
实现契约以 [项目复现规格](docs/Text-to-SQL项目复现规格.md) 和
[测试与验收规格](docs/Text-to-SQL测试与验收规格.md) 为准。

## License

本项目以 [MIT License](LICENSE) 开源。
