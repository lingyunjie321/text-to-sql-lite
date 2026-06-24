# Text-to-SQL Agent Demo

一个轻量级的 Text-to-SQL Agent 项目：运营/分析师用自然语言提问，由数据团队维护可信上下文（Schema、Reference SQL、文档知识、Metric、Semantic Model），后端通过可配置的多阶段工作流生成、校验、执行并修复 SQL，全过程留有可观测 Trace。

> 项目定位为**轻量业务交付版 / 面试级 demo**，不包含认证、多租户、调度、BI 看板等生产级能力。详见文末[项目定位与边界](#项目定位与边界)。

## 目录

- [核心特性](#核心特性)
- [技术栈](#技术栈)
- [环境要求](#环境要求)
- [快速启动](#快速启动)
- [Demo 场景](#demo-场景)
- [API 示例](#api-示例)
- [高级配置](#高级配置)
- [项目结构速览](#项目结构速览)
- [测试](#测试)
- [文档导航](#文档导航)
- [项目定位与边界](#项目定位与边界)

## 核心特性

- **可配置工作流**：节点、边、最大步数、最大修复次数、模型 alias 和数据库连接都在 `workflow.yaml` 中声明，流转由节点输出和配置决定，不硬编码在 API handler 中。
- **注册式节点体系**：节点统一实现 `BaseNode` 接口，通过注册表按 type 创建；新增节点不需要改动工作流引擎或工厂。
- **RAG 检索与 Prompt 裁剪**：只把 linked schema、Top-K 示例、知识库上下文和业务方言范式注入 prompt，不把完整 schema 或全部样例塞给模型。
- **SQL 安全与反思闭环**：SQLGlot 做方言解析、单语句、只读 SELECT 和 schema 引用校验；校验或执行失败后按错误类型路由到修复、重新链接 Schema、重新推理或人工介入，最多 3 轮并有明确终止条件。
- **可观测与前端演示**：每个节点执行后记录 Trace；React/Vite 前端支持自然语言查询、运行配置、SQL 编辑执行、结果展示、保存 SQL、反馈和开发者 Trace 展开。

更细的实现证据、亮点和限制见 [docs/完成度分析.md](docs/完成度分析.md)。

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

## 环境要求

- **Python 3.11+**（`pyproject.toml` 声明 `requires-python = ">=3.11"`）
- **Node 18+**（前端使用 Vite 6 / React 18）
- 默认执行数据库是本地 SQLite，无需额外安装数据库服务
- 默认 LLM 走 OpenAI-compatible provider，需要可用的 API Key；测试和内置 demo 场景使用 Mock LLM，不依赖真实付费 API

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

### 配置默认 LLM

当前 `workflow.yaml` 的 `light` / `strong` alias 默认读取 `DEEPSEEK_API_KEY` 和 `DEEPSEEK_BASE_URL`。把真实密钥写到本地 `.env.local`（已被 `.gitignore` 忽略），不要提交：

```bash
cp .env.example .env.local
# 在 .env.local 中填入:
# DEEPSEEK_API_KEY=你的真实_key
# DEEPSEEK_BASE_URL=https://你的-openai-compatible-endpoint/v1/chat/completions
```

模型名和环境变量名可以按你的账号可用模型调整，但业务代码只依赖 `light` / `strong` alias。如果不配置 base URL，项目会使用默认 OpenAI Chat Completions endpoint。当前默认 alias 配置如下：

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

如果只是运行内置面试场景，可以直接使用 `python scripts/run_demo.py`，脚本会注入 `MockLLMClient`，不需要 API Key。

### 启动后端与前端

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

## Demo 场景

运行三条内置面试场景（使用 Mock LLM，无需 API Key）：

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

此外项目还提供以下接口，完整请求体和返回字段见 [docs/SQL生成过程代码追踪.md](docs/SQL生成过程代码追踪.md) 与 [docs/运行时配置.md](docs/运行时配置.md)：

- `POST /api/v1/saved-queries`：保存一次成功 SQL（先存为 `draft`，轻量审核为 `approved` 后才作为可信 Reference SQL 进入后续检索）
- `POST /api/v1/runs/<request_id>/feedback`：提交运行反馈
- `GET /api/v1/schema`：查看当前 demo 数据库 Schema，支持 `database_preset_id` 指定自动发现的 SQLite 数据源
- `POST /api/v1/runtime/configs`：创建临时运行配置（数据库连接 + `light/strong` 模型路由），返回的 `runtime_config_id` 可用于 `/api/v1/query`、`/api/v1/schema` 和 `/api/v1/sql/execute`；运行时配置只保存在后端内存中，用户提交的密码和 API Key 不会写入配置文件，也不会回传前端
- `POST /api/v1/sql/execute`：执行用户编辑后的只读 SQL
- `POST /api/v1/transpile`：转换已有 SQL 方言

## 高级配置

下面两类配置属于二次开发场景，普通使用者用默认 SQLite + 默认 LLM alias 即可：

- **连接服务型数据库（PostgreSQL/MySQL）**：先 `pip install -e ".[dev,db]"` 安装驱动，再在 `workflow.yaml` 的 `database.connections` 下用结构化字段配置连接（密码只放 `TEXT_TO_SQL_DB_PASSWORD` 等环境变量，不要明文写进 YAML），并把 `dialect`、`sql_generation`、`sql_validation`、`sql_execution` 的目标方言保持一致。完整 URL 环境变量（如 `DEMO_DATABASE_URL`）仍然可用且优先级最高。
- **扩展新的数据库类型（SQL Server、Oracle、DuckDB 等）**：需要在 driver、运行时模型、API 映射、SQLGlot 方言声明和测试等多个层做扩展，但不要改动工作流引擎或节点流转逻辑。

这两节的完整步骤和代码改动点见 [docs/项目结构与模块职责.md](docs/项目结构与模块职责.md) 的"配置与数据文件"和"核心模块职责表"部分；数据库与模型路由的整体方案见 [docs/运行时配置.md](docs/运行时配置.md)。

## 项目结构速览

```Plaintext
text_to_sql/
├── AGENTS.md                  # 项目约束、架构规则、开发流程规范
├── README.md                  # 项目介绍、启动方式、Demo 场景、API 示例
├── pyproject.toml             # Python 依赖、包配置、pytest/ruff 配置
├── workflow.yaml              # 默认 Text-to-SQL 多阶段工作流配置
├── .env.example               # 本地环境变量示例
│
├── configs/                   # 示例配置（examples / knowledge / dialect_patterns / prompts）
├── data/sqlite/               # 本地 SQLite demo 数据库
├── docs/                      # 项目说明文档
├── examples/                  # 最小工作流配置示例
├── scripts/                   # init_db.py / run_demo.py
├── src/text_to_sql_demo/      # 后端主包（api / config / workflow / nodes / schema / retrieval / routing / prompts / llm / sql / execution / runtime / metadata / observability / db）
├── tests/                     # unit / integration
└── frontend/                  # React/Vite 前端演示
```

完整目录树和每个模块的入口文件、职责与依赖见 [docs/项目结构与模块职责.md](docs/项目结构与模块职责.md)。

## 测试

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

完整文档导读（含每个文档的定位和推荐阅读顺序）见 [docs/README.md](docs/README.md)。

**架构与工作流**

- [整体架构](docs/整体架构.md)
- [文本转 SQL 工作流](docs/文本转SQL工作流.md)
- [SQL 生成过程代码追踪](docs/SQL生成过程代码追踪.md)
- [项目结构与模块职责](docs/项目结构与模块职责.md)

**记忆与可观测**

- [记忆架构与模块设计](docs/记忆架构与模块设计.md)
- [日志与可观测性](docs/日志与可观测性.md)

**运行时与配置**

- [运行时配置](docs/运行时配置.md)
- [API 参考](docs/API参考.md)
- [知识库与配置维护](docs/知识库与配置维护.md)

**扩展开发**

- [数据库与方言扩展](docs/数据库与方言扩展.md)
- [节点扩展开发](docs/节点扩展开发.md)

**演示与维护**

- [面试演示场景](docs/面试演示场景.md)
- [完成度分析](docs/完成度分析.md)
- [文档维护规范](docs/文档维护规范.md)

## 项目定位与边界

- **定位**：轻量业务交付版，面向运营/分析师自然语言查数，由数据团队维护可信上下文。同时也是面试级 demo，用于展示可配置工作流、注册式节点、RAG 检索、SQL 安全链路和反思闭环等工程能力。
- **默认 LLM**：`workflow.yaml` 默认使用 OpenAI-compatible provider，需要正确配置 `DEEPSEEK_API_KEY` / `DEEPSEEK_BASE_URL`；测试和 `scripts/run_demo.py` 仍显式注入 `MockLLMClient`，不依赖真实付费 LLM API。
- **SQL 执行安全**：SQL 只读安全依赖 SQLGlot AST 解析和执行前校验，不等同于生产级数据库权限隔离；业务目标库默认只读，项目自身的运行记录、Trace、收藏 SQL、反馈等内部表允许写入。
- **当前限制**：运行记录和运行时配置使用内存存储，服务重启后消失；Schema 来源默认是数据库 introspection；Example retrieval 是本地词法检索，不使用向量数据库或 embedding；`ComplexityClassifier` 是规则分类器而非训练模型；不实现认证、多租户或长期密钥托管。

更完整的"已实现能力 / 限制 / 后续方向"见 [docs/完成度分析.md](docs/完成度分析.md)。
