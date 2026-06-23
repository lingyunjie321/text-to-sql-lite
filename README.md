# Text-to-SQL Agent Demo

面向面试展示的 Text-to-SQL Agent 演示项目。它不是生产级平台，而是用一套可读、可测、可配置的工程实现，展示从自然语言问题到 SQL 生成、校验、执行、反思修复和 Trace 观测的完整链路。

当前默认使用 `MockLLMClient`，不需要 API Key；默认执行数据库是本地 SQLite demo 数据库。

## 核心能力

- 可配置工作流：`workflow.yaml` 定义节点、边、最大步数、最大修复次数、模型 alias 和数据库连接。
- 注册式节点体系：`BaseNode`、`NodeRegistry`、`NodeFactory` 和 `WorkflowEngine` 解耦，新增节点不需要改 engine。
- 状态驱动通信：节点通过 `WorkflowState.data` 共享 `schema_linking`、`retrieved_examples`、`generated_sql`、`validation_result`、`execution_result` 等中间结果。
- Prompt 裁剪：`PromptBuilder.build` 只注入 linked schema 和 Top-K 示例，不把完整 schema 和所有样例塞进 prompt。
- 模型路由：`GenerateSQLNode.run` 内根据 `ComplexityClassifier` 结果选择 `light` 或 `strong` 模型 alias。
- SQL 安全链路：`SQLValidator` 基于 SQLGlot 做方言解析、单语句、只读 SELECT 和 schema 引用校验；`SQLExecutor` 只执行已校验 SQL。
- 修复闭环：校验或执行失败后进入 `ReflectErrorNode` 和 `FixSQLNode`，最多 3 次修复尝试，失败后明确终止。
- 可观测 Trace：每个节点执行后由 `WorkflowEngine` 记录节点名、outcome、耗时、输入输出摘要和错误摘要。
- 前端演示：React/Vite 页面支持自然语言查询、SQL 查看/编辑、结果展示、修复提示和开发者 Trace 展开。

## 技术栈

| 层次 | 技术 |
| --- | --- |
| 后端 API | Python 3.11+、FastAPI、Pydantic |
| 工作流 | 自研轻量 `WorkflowEngine`，不使用 LangGraph/LangChain |
| SQL | SQLAlchemy、SQLGlot、SQLite，支持方言解析/转换接口 |
| LLM | Provider 无关 `LLMClient` 协议，默认 `MockLLMClient` |
| 配置 | YAML + Pydantic config model |
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

## 真实 LLM 配置（可选）

默认配置仍使用 `MockLLMClient`，不需要 API Key。若要调用 OpenAI-compatible Chat Completions API，请先创建本地 `.env.local`，该文件已被 `.gitignore` 忽略：

```bash
OPENAI_API_KEY=你的真实_key
OPENAI_BASE_URL=https://api.openai.com/v1/chat/completions
```

然后把 `workflow.yaml` 中 `models.aliases` 的 provider 改为 `openai_compatible`，模型名按你的账号可用模型配置：

```yaml
models:
  aliases:
    light:
      provider: openai_compatible
      model: gpt-4.1-mini
      temperature: 0.0
      api_key_env: OPENAI_API_KEY
      base_url_env: OPENAI_BASE_URL
    strong:
      provider: openai_compatible
      model: gpt-4.1
      temperature: 0.0
      api_key_env: OPENAI_API_KEY
      base_url_env: OPENAI_BASE_URL
```

如果不配置 `OPENAI_BASE_URL`，项目会使用默认 OpenAI Chat Completions endpoint。测试和内置 demo 场景仍然通过 Mock LLM 执行，不会依赖真实付费 API。

## Demo 场景

运行三条内置面试场景：

```bash
python scripts/run_demo.py
```

场景覆盖：

- 复杂查询一次成功：Schema Linking、Top-K 示例、复杂度路由、SQL 校验执行和 Trace。
- 错误字段自动修复：`unknown_column` 触发反思修复，第二轮成功。
- 终止路径：Mock LLM 持续返回错误 SQL，三次修复后 `attempts_exhausted`。

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

查询某次运行记录：

```bash
curl http://127.0.0.1:8000/api/v1/runs/<request_id>
```

查看当前 demo 数据库 Schema：

```bash
curl http://127.0.0.1:8000/api/v1/schema
```

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
- [文本转 SQL 工作流](docs/文本转SQL工作流.md)
- [SQL 生成过程代码追踪](docs/SQL生成过程代码追踪.md)
- [面试演示场景](docs/面试演示场景.md)
- [完成度分析](docs/完成度分析.md)
- [文档维护规范](docs/文档维护规范.md)
