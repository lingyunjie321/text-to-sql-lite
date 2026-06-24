# Text-to-SQL Agent Demo

当前 `workflow.yaml` 默认使用 OpenAI-compatible provider，并通过 `DEEPSEEK_API_KEY` / `DEEPSEEK_BASE_URL` 读取真实模型配置；默认执行数据库是本地 SQLite demo 数据库。测试和 `scripts/run_demo.py` 仍显式注入 `MockLLMClient`，不依赖真实付费 LLM API。

## 核心能力

- 可配置工作流：`workflow.yaml` 定义节点、边、最大步数、最大修复次数、模型 alias 和数据库连接。
- 注册式节点体系：`BaseNode`、`NodeRegistry`、`NodeFactory` 和 `WorkflowEngine` 解耦，新增节点不需要改 engine。
- Datus-style 核心链路：默认 workflow 已对齐 `Begin -> Selection -> Schema -> Context Retrieval -> Example Retrieval -> GenSQL -> Validation -> Execute -> Finalization`。
- 状态驱动通信：节点通过 `WorkflowState.data` 共享 `task`、`intent`、`schema_linking`、`rag_context`、`retrieved_examples`、`generated_sql`、`validation_result`、`execution_result` 等中间结果。
- 本地知识库检索：`ContextRetrievalNode` 从 `configs/knowledge.yaml` 和 approved saved_query 检索可信 Reference SQL、文档片段、Metric 和 Semantic Model；当前实现是 YAML/SQLite/词法 Top-K fallback，后续可替换为可选向量后端。
- Prompt 裁剪：`PromptBuilder.build` 只注入 linked schema、Top-K 示例、知识库上下文和业务方言范式，不把完整 schema、所有样例或完整知识库塞进 prompt。
- Agentic SQL 生成：`GenSQLAgenticNode.run` 根据 `ComplexityClassifier` 结果选择 `light` 或 `strong` 模型 alias，并注入 linked schema、RAG 上下文、Top-K 示例和业务方言范式。
- SQL 安全链路：`SQLValidator` 基于 SQLGlot 做方言解析、单语句、只读 SELECT 和 schema 引用校验；`SQLExecutor` 只执行已校验 SQL。
- 策略反思闭环：校验或执行失败后进入 `ReflectionDecisionNode`，按错误类型路由到 `FIX_SQL`、`RELINK_SCHEMA`、`RETRIEVE_CONTEXT`、`REASONING_REWRITE` 或 `HITL`，最多 3 轮并有明确终止条件。
- 轻量 SQLContext 记忆：失败和成功 SQL 尝试都会沉淀 hash/长度、错误类型、结果摘要、反思策略和原因摘要；`SUCCESS` 只表示单次 workflow 成功收敛，用于回放和解释，不会自动变成跨运行可信知识。
- 可观测 Trace：每个节点执行后由 `WorkflowEngine` 记录节点名、outcome、耗时、输入输出摘要和错误摘要。
- 内部 metadata store：项目自身使用 SQLite 沉淀 `query_run`、`trace_event`、`saved_query` 和 `feedback`；普通 saved_query 先保存为 `draft`，经轻量审核入口更新为 `approved` 后才会作为可信 Reference SQL 进入后续检索，不写入业务目标库。
- 运行时配置：前端可临时配置数据库连接和 `light/strong` 双模型路由，请求通过 `runtime_config_id` 使用对应配置。
- 前端演示：React/Vite 页面支持自然语言查询、运行配置、SQL 查看/编辑、结果展示、保存 SQL、反馈、历史记录和开发者 Trace 展开。

## 技术栈

| 层次 | 技术 |
| --- | --- |
| 后端 API | Python 3.11+、FastAPI、Pydantic |
| 工作流 | 自研轻量 `WorkflowEngine`，不使用 LangGraph/LangChain |
| SQL | SQLAlchemy、SQLGlot、SQLite，支持 PostgreSQL/MySQL 方言校验、转换和只读执行路径 |
| LLM | Provider 无关 `LLMClient` 协议，默认 workflow 使用 OpenAI-compatible adapter；测试和 demo 脚本使用 `MockLLMClient` |
| 配置 | YAML + Pydantic config model，默认包含 `configs/examples.yaml` 和 `configs/knowledge.yaml` |
| 测试与质量 | pytest、ruff |
| 前端 | React 18、Vite、TypeScript、Vitest |

## 快速启动

建议先安装为 editable 包，测试和脚本都会更顺滑：

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

初始化 demo SQLite 数据库：

```bash
python scripts/init_db.py --db-path data/sqlite/demo.db
```

配置默认 LLM。当前 `workflow.yaml` 的 `light` / `strong` alias 默认读取 `DEEPSEEK_API_KEY` 和 `DEEPSEEK_BASE_URL`；如果你的服务端点不是默认 OpenAI Chat Completions endpoint，需要同时配置 base URL：

```bash
cp .env.example .env.local
# 在 .env.local 中填入:
# DEEPSEEK_API_KEY=你的真实_key
# DEEPSEEK_BASE_URL=https://你的-openai-compatible-endpoint/v1/chat/completions
```

如果只是运行内置面试场景，可以直接使用 `python scripts/run_demo.py`，脚本会注入 `MockLLMClient`，不需要 API Key。

启动后端 API。当前项目使用 `src/` 布局；如果没有安装 editable 包，请保留 `PYTHONPATH=src`：

```bash
PYTHONPATH=src uvicorn text_to_sql_demo.main:app --reload
```

健康检查：

```bash
curl http://127.0.0.1:8000/health
```

启动前端演示界面：

```bash
cd frontend
npm install
npm run dev
```

Vite 已把 `/api` 代理到 `http://127.0.0.1:8000`，所以前端和后端需要同时运行。

## 连接服务型数据库（可选）

默认仍使用本地 SQLite。若要连接带 `host + port + username + password` 的 Postgres/MySQL，先安装数据库驱动：

```bash
pip install -e ".[dev,db]"
```

结构化连接配置写在 `workflow.yaml` 的 `database.connections` 下，密码不要明文写进 YAML，只放到本地 `.env.local` 或 shell 环境变量：

```bash
TEXT_TO_SQL_DB_PASSWORD=你的数据库密码
```

Postgres 示例：

```yaml
database:
  default: demo_postgres
  connections:
    demo_postgres:
      driver: postgresql
      host: localhost
      port: 5432
      database_name: text_to_sql_demo
      username: readonly_user
      password_env: TEXT_TO_SQL_DB_PASSWORD
      query:
        sslmode: prefer
      read_only: true
```

切换工作流执行方言时，需要让生成、校验和执行保持一致：

```yaml
dialect:
  name: postgres
  target_dialect: postgres

nodes:
  sql_generation:
    target_dialect: postgres
  sql_validation:
    target_dialect: postgres
    render_dialect: postgres
  sql_execution:
    execution_dialect: postgres
```

完整 URL 环境变量仍然可用，并且优先级最高，例如 `DEMO_DATABASE_URL=postgresql+psycopg://user:password@host:5432/dbname?sslmode=require`。更推荐结构化字段，因为配置更清楚，密码也更容易统一放在环境变量中管理。

## 扩展新的数据库类型（可选开发）

如果只是接入新的 PostgreSQL/MySQL 数据库实例，通常不需要改代码，按上一节新增 `workflow.yaml` 连接即可。只有当项目要支持一种当前没有声明的数据库类型，例如 SQL Server、Oracle、DuckDB 等，才需要扩展 driver、方言和测试。

扩展时不要修改 `WorkflowEngine`、`NodeFactory` 或具体节点流转逻辑。数据库类型属于配置、运行时解析、Schema 读取、SQL 校验和 SQLAlchemy 执行层的能力。

建议按下面顺序修改：

1. 在 `pyproject.toml` 的可选依赖中加入对应 SQLAlchemy 驱动，例如 `mssql+pyodbc`、`oracle+oracledb` 或其他官方推荐驱动。
2. 在 `src/text_to_sql_demo/config/models.py` 扩展 `DatabaseConnectionConfig.driver` 的允许值。
3. 在 `src/text_to_sql_demo/runtime/models.py` 扩展 `RuntimeDriver`，让运行时配置 API 可以接收新 driver。
4. 在 `src/text_to_sql_demo/api/service.py` 的 `SERVER_DRIVER_NAMES` 中加入新 driver 到 SQLAlchemy driver name 的映射；如果新数据库需要额外 URL 参数，也要确保通过 `query` 或安全字段传入。
5. 在 `src/text_to_sql_demo/runtime/resolver.py` 的 `DRIVER_TO_DIALECT` 中加入 driver 到 SQLGlot 方言名的映射。
6. 在 `src/text_to_sql_demo/sql/dialect.py` 扩展 `DialectName` 和 `SUPPORTED_DIALECTS`。只有 SQLGlot 能解析并渲染该方言时，才应开放该方言。
7. 如果前端也要展示或提交该数据库类型，同步更新 `frontend/src/api/types.ts` 里的 driver 和 dialect 联合类型。
8. 在 `workflow.yaml` 增加一个只读连接预设，并把 `dialect`、`sql_generation`、`sql_validation`、`sql_execution` 的目标方言保持一致。
9. 为新类型补测试：配置解析、URL 构造、运行时配置 API、Schema introspection、SQL 方言校验和只读执行路径。

安全约束保持不变：数据库密码不要写进 YAML；优先使用 `password_env` 和 `.env.local`；数据库账号应只授予查询权限；日志、Trace 和 API 响应不能输出完整数据库 URL、密码、完整 SQL 或完整结果集。

扩展完成后至少运行：

```bash
ruff check .
python -m pytest
```

如果改了前端类型或页面，还需要运行：

```bash
cd frontend
npm test
npm run build
```

## 默认 LLM 配置

默认配置已经使用 OpenAI-compatible Chat Completions API。请先创建本地 `.env.local`，该文件已被 `.gitignore` 忽略：

```bash
DEEPSEEK_API_KEY=你的真实_key
DEEPSEEK_BASE_URL=https://你的-openai-compatible-endpoint/v1/chat/completions
```

当前 `workflow.yaml` 中的模型 alias 如下；模型名和环境变量名可以按你的账号可用模型调整，但业务代码只依赖 `light` / `strong` alias：

```yaml
models:
  aliases:
    light:
      provider: openai_compatible
      model: deepseek-v4-flash
      temperature: 0.0
      api_key_env: DEEPSEEK_API_KEY
      base_url_env: DEEPSEEK_BASE_URL
    strong:
      provider: openai_compatible
      model: deepseek-v4-pro
      temperature: 0.0
      api_key_env: DEEPSEEK_API_KEY
      base_url_env: DEEPSEEK_BASE_URL
```

如果不配置 base URL，项目会使用默认 OpenAI Chat Completions endpoint。测试和内置 demo 场景仍然通过 Mock LLM 执行，不会依赖真实付费 API。

## Demo 场景

运行三条内置面试场景：

```bash
python scripts/run_demo.py
```

场景覆盖：

- 复杂查询一次成功：Schema Linking、Top-K 示例、复杂度路由、SQL 校验执行和 Trace。
- 错误字段自动修复：`unknown_column` 触发反思修复，第二轮成功。
- 终止路径：Mock LLM 持续返回错误 SQL，三次修复后 `attempts_exhausted` 并进入 `HITL` 收敛。

详细讲解见 [docs/面试演示场景.md](docs/面试演示场景.md)。

## API 示例

执行一次 Text-to-SQL 工作流：

```bash
curl -X POST http://127.0.0.1:8000/api/v1/query \
  -H 'Content-Type: application/json' \
  -d '{
    "question": "列出订单金额",
    "target_dialect": "sqlite",
    "max_attempts": 3,
    "debug": true
  }'
```

`/api/v1/query` 响应会返回 `linked_schema`、`retrieved_examples`、`rag_context` 和 `trace`，其中 `rag_context` 是经过 Top-K 裁剪后的 Reference SQL、文档、Metric、Semantic Model 摘要。

查询某次运行记录：

```bash
curl http://127.0.0.1:8000/api/v1/runs/<request_id>
```

列出最近运行记录：

```bash
curl http://127.0.0.1:8000/api/v1/runs
```

保存一次成功 SQL：

```bash
curl -X POST http://127.0.0.1:8000/api/v1/saved-queries \
  -H 'Content-Type: application/json' \
  -d '{
    "name": "订单金额明细",
    "request_id": "<request_id>",
    "tags": ["运营", "订单"]
  }'
```

提交一次运行反馈：

```bash
curl -X POST http://127.0.0.1:8000/api/v1/runs/<request_id>/feedback \
  -H 'Content-Type: application/json' \
  -d '{
    "rating": "up",
    "issue_type": "accurate",
    "comment": "结果可直接使用"
  }'
```

查看当前 demo 数据库 Schema：

```bash
curl http://127.0.0.1:8000/api/v1/schema
```

创建临时运行配置：

```bash
curl -X POST http://127.0.0.1:8000/api/v1/runtime/configs \
  -H 'Content-Type: application/json' \
  -d '{
    "database": {"mode": "preset", "preset_id": "demo_sqlite"},
    "models": {
      "light": {"mode": "preset", "preset_id": "light"},
      "strong": {"mode": "preset", "preset_id": "strong"}
    }
  }'
```

返回的 `runtime_config_id` 可用于 `/api/v1/query`、`/api/v1/schema` 和 `/api/v1/sql/execute`。运行时配置只保存在后端内存中，用户提交的数据库密码和模型 API Key 不会写入配置文件，也不会回传给前端。

执行用户编辑后的只读 SQL：

```bash
curl -X POST http://127.0.0.1:8000/api/v1/sql/execute \
  -H 'Content-Type: application/json' \
  -d '{
    "sql": "SELECT id, amount FROM orders ORDER BY id",
    "target_dialect": "sqlite",
    "max_rows": 100
  }'
```

转换已有 SQL 方言：

```bash
curl -X POST http://127.0.0.1:8000/api/v1/transpile \
  -H 'Content-Type: application/json' \
  -d '{
    "sql": "SELECT name || email AS label FROM customers",
    "source_dialect": "postgres",
    "target_dialect": "mysql"
  }'
```

## 测试命令

后端质量检查：

```bash
ruff check .
python -m pytest
python scripts/run_demo.py
```

前端检查：

```bash
cd frontend
npm test
npm run build
```

## 文档导航

- [项目结构与模块职责](docs/项目结构与模块职责.md)
- [整体架构](docs/整体架构.md)
- [记忆架构与模块设计](docs/记忆架构与模块设计.md)
- [文本转 SQL 工作流](docs/文本转SQL工作流.md)
- [SQL 生成过程代码追踪](docs/SQL生成过程代码追踪.md)
- [面试演示场景](docs/面试演示场景.md)
- [完成度分析](docs/完成度分析.md)
- [运行时数据库与模型路由配置方案](docs/运行时数据库与模型路由配置方案.md)
- [日志系统设计](docs/日志系统设计.md)
- [文档维护规范](docs/文档维护规范.md)
