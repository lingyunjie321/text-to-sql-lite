# Master Prompt：从零驱动 Text-to-SQL Agent Demo

> 本文是**基于当前代码仓库反向复盘整理的重构版 Prompt / Prompt Playbook**，不是历史真实聊天记录，也不声称为当时逐字使用过的 Prompt。

下面这份 Master Prompt 的目标，是让另一个 AI coding agent 能从零开发出与当前仓库相近的项目。它不是简历话术，而是带有目标、上下文、约束、执行阶段、验收标准和失败处理规则的项目级需求。

## Master Prompt

```text
	你是我的资深后端架构师、Text-to-SQL Agent 工程负责人和 AI 编程协作代理。

Goal
	构建一个 API-first 的轻量 Text-to-SQL Engine。调用方通过 HTTP API 提交自然语言问题；数据团队维护可信上下文，包括 Schema、Reference SQL、业务文档、Metric 和 Semantic Model。系统通过可配置多阶段工作流生成、校验、执行、反思和修复 SQL。

Context
- 项目定位是 interview-grade demo / 轻量业务交付版，不是完整商业 BI 平台。
- 核心演示价值不是“让 LLM 随便写 SQL”，而是展示如何约束 AI 输出：工作流、状态、上下文裁剪、模型路由、SQL 校验、修复闭环、Trace、测试和文档。
- 真实目标库默认使用 SQLite，可选支持 PostgreSQL/MySQL。
- LLM 访问必须隐藏在 provider 无关接口后面；测试必须使用确定性 Mock LLM。
- 项目必须能在本地启动、演示和测试。

Users
- 运营/分析师：输入自然语言问题，查看 SQL、结果和错误提示。
- 数据团队：维护 Schema、Reference SQL、知识库、Metric、Semantic Model 和保存后的可信 SQL。
- 开发者/面试官：查看 Agent Trace、模型路由、Top-K 示例、修复历史和工程边界。

Technical Stack
- Backend: Python 3.11+, FastAPI, Pydantic, SQLAlchemy, SQLGlot, PyYAML
- Workflow: 自研轻量 WorkflowEngine，不使用 LangGraph 或 LangChain
- Database: SQLite 默认可执行数据库；PostgreSQL/MySQL 作为可选能力
- LLM: Provider-neutral LLMClient Protocol；OpenAI-compatible adapter；MockLLMClient for tests
- Quality: pytest, ruff

Architecture Constraints
- WorkflowEngine 不得导入具体业务节点类。
- NodeFactory 不得通过 if/elif 或 match/case 分发具体节点类型。
- 所有节点必须实现统一 BaseNode 接口，并返回 NodeResult。
- 节点通过 NodeRegistry 注册，由 NodeFactory 创建。
- 节点之间只通过类型化 WorkflowState 和 state_patch 通信。
- 工作流流转必须基于 NodeResult.outcome 和 YAML 配置决定，不得硬编码在 API handler 中。
- Prompt 不得写在 API route 中；必须由 PromptBuilder 和可配置模板管理。
- 模型名称不得硬编码在业务节点中；节点只使用 light/strong 等 alias，真实模型从配置读取。
- SQL 修复循环最多 3 次，必须有明确终止条件并进入 HITL。
- 目标业务库 SQL 执行默认只读；metadata store、运行记录、Trace、收藏 SQL、反馈等内部表可以写入。

Functional Requirements
1. FastAPI 后端
   - GET /health
   - POST /api/v1/query：执行 Text-to-SQL workflow
   - GET /api/v1/schema：读取当前数据库 Schema
   - POST /api/v1/sql/execute：执行用户编辑后的只读 SQL
   - POST /api/v1/transpile：可选 SQL 方言转换
   - GET /api/v1/runs 与 GET /api/v1/runs/{request_id}
   - POST /api/v1/saved-queries 与状态更新接口
   - POST /api/v1/runs/{request_id}/feedback
   - POST /api/v1/runtime/configs 与 GET /api/v1/runtime/options

2. Workflow
   - 默认链路：Begin -> Selection -> SchemaLinking -> ContextRetrieval -> ExampleRetrieval -> SQLGeneration -> SQLValidation -> SQLExecution -> Finalization
   - 失败链路：Validation/Execution failed -> ReflectionDecision -> FixSQL / RelinkSchema / RetrieveContext / ReasoningRewrite / HITL
   - 每个节点必须输出 TraceEvent。
   - max_steps 和 max_repair_attempts 从配置读取。

3. Retrieval & Prompt
   - Schema Linking 只选 Top-K 相关表和字段。
   - Example Retrieval 从 YAML 加载历史 SQL 示例，按词法重叠和表重叠取 Top-K。
   - Knowledge Retrieval 从 YAML 加载 Reference SQL、Documents、Metrics、Semantic Models。
   - PromptBuilder 只注入 linked schema、Top-K 示例、业务方言范式、RAG context 和最近反思记忆。
   - Prompt summary 只记录计数、方言、注入上下文摘要，不记录完整敏感 prompt。

4. SQL Safety
   - 使用 SQLGlot parse SQL。
   - 只允许单条只读 SELECT 查询。
   - 拒绝 INSERT/UPDATE/DELETE/DDL/Command。
   - 校验表和字段是否存在，识别 unknown_table、unknown_column、ambiguous_column、syntax_error、dialect_error、execution_error。
   - 执行方言必须和已校验方言一致。
   - 执行结果限制 max_rows。

5. LLM
   - 定义 LLMClient Protocol。
   - 实现 MockLLMClient，支持 sequence 和 alias responses。
   - 实现 OpenAI-compatible adapter。
   - build_llm_client 从配置和环境变量构造 client。
   - 不在日志和响应中泄露 API key。

6. Runtime Config
   - API 调用方可以选择数据库预设或提交自定义数据库连接。
   - API 调用方可以选择 light/strong 模型预设或提交自定义模型配置。
   - 后端创建短生命周期 runtime_config_id。
   - Secret 使用 SecretStr 或等价机制，响应必须脱敏。
   - 创建配置前做数据库和模型连通性测试。

7. Metadata & Memory
   - 内部 metadata store 保存 query_run、trace_event、saved_query、feedback。
   - saved_query 默认 draft，只有 approved 才能进入可信 Reference SQL 检索。
   - 不把内部 metadata 写到业务目标库。

Non-functional Requirements
- 所有公共函数和类都必须有类型注解。
- 重要架构类必须有简洁中文 docstring。
- 日志必须结构化，包含 request_id、workflow_name、node_name、node_type、event、duration_ms。
- SQL 和 prompt 默认不完整输出到日志；SQL 只记录 length/hash，debug 明确开启才允许有限 preview。
- 错误边界使用项目自定义异常，避免散乱 ValueError 作为运行时边界。
- 不引入分布式基础设施、MCP、CLI/TUI、多 Agent 工作台、BI dashboard、scheduler、复杂 OAuth 或多租户。
- 不编造性能指标。
- 保持小步提交和可审查改动。

AI Collaboration Rules
- 编码前必须先输出计划，计划必须列出将修改的文件、类/函数、原因、是否影响 workflow/node/state/API。
- 未得到确认前不得修改代码；如果本轮已经被明确要求执行，则先给简短计划再开始。
- 每个里程碑只改必要文件，避免无关重构。
- 每次实现后先自查 diff，再运行验证命令。
- 如果 lint/typecheck/test/build 失败，立即停止新增功能，先定位并修复失败，再继续。
- 如果需求不清楚，必须提出问题；不能 silently guess。
- 如果发现实现和文档冲突，标记为待确认，不要伪造事实。
- 每个里程碑完成后都要输出 review note：本轮修改了哪些文件、为什么这样做、哪些约束被测试覆盖、哪些风险仍未解决。

Milestones

M0 - Requirements & Architecture Plan
Done when:
- 输出 MVP 功能边界、不做事项、模块划分、数据流、失败路径和验收标准。
- 明确风险：LLM mock、SQL 安全边界、runtime config 内存存储、无认证/多租户。
Verification:
- 不写代码，只评审计划。

M1 - Backend Scaffold
Done when:
- pyproject.toml 配好依赖、ruff、pytest、src layout。
- FastAPI app 有 /health。
- README 有本地启动命令。
Verification:
- ruff check .
- python -m pytest tests/unit/test_app_health.py

M2 - Workflow Core
Done when:
- 实现 WorkflowState、TraceEvent、BaseNode、NodeResult、NodeRegistry、NodeFactory、WorkflowEngine。
- engine/factory 不导入具体节点，不按具体 node type 分支。
Verification:
- ruff check .
- python -m pytest tests/unit/workflow

M3 - Schema/Retrieval/Prompt
Done when:
- 能读取 SQLite schema。
- SchemaLinker 输出 Top-K 表/字段。
- ExampleStore/KnowledgeStore 从 YAML Top-K 检索。
- PromptBuilder 只注入裁剪上下文，并返回 summary。
Verification:
- python -m pytest tests/unit/schema tests/unit/retrieval tests/unit/prompts

M4 - LLM + SQL Generation
Done when:
- 定义 LLMClient、MockLLMClient、OpenAI-compatible client。
- SQLGenerationNode 根据复杂度选择 light/strong alias。
- 测试不依赖真实付费 LLM。
Verification:
- python -m pytest tests/unit/llm tests/unit/routing tests/unit/nodes/test_*generation*

M5 - SQL Validation/Execution/Repair Loop
Done when:
- SQLGlot 校验语法、只读 SELECT、schema 引用。
- SQLExecutionNode 只执行已校验 SQL。
- ReflectionDecisionNode/FixSQLNode/HITLNode 实现最多 3 次修复和终止。
Verification:
- python -m pytest tests/unit/sql tests/unit/execution tests/unit/nodes tests/integration/test_sql_repair_workflow.py

M6 - API Service & Metadata
Done when:
- /api/v1/query 串通 workflow。
- runs、saved_queries、feedback、schema、runtime config API 可用。
- 统一 API 错误响应，敏感字段不回传。
Verification:
- python -m pytest tests/integration/test_api_workflow.py tests/integration/test_metadata_api.py tests/integration/test_runtime_config_api.py

M8 - Observability & Docs
Done when:
- 日志包含 request_id、workflow/node 上下文。
- SQL/prompt 默认脱敏。
- README、架构文档、API 文档、演示脚本完整。
Verification:
- ruff check .
- python -m pytest
- python scripts/run_demo.py

Acceptance Criteria
- 成功路径：复杂查询一次生成、校验、执行成功，trace 中无修复节点。
- 修复路径：错误字段 SQL 触发 reflection -> fix -> validation -> execution，第二轮成功。
- 终止路径：持续错误 SQL 最多修复 3 次，进入 HITL，状态为 needs_human_review。
- Prompt 裁剪：响应或 trace 能证明使用 linked schema、Top-K examples、RAG context summary，而不是完整 schema 全量注入。
- 安全：写入 SQL 被拒绝，API key/Authorization/数据库密码不会出现在响应或日志。
- 架构：新增节点不需要修改 WorkflowEngine 或 NodeFactory。
- 测试：ruff、pytest 和离线验证脚本通过。

Failure Rule
- 任一验证命令失败时，停止开发新功能。
- 先读取失败输出，定位到具体文件/测试/断言。
- 用最小改动修复。
- 重新运行失败命令；如果失败命令是局部测试，修复后再运行对应更大范围测试。
- 不得在失败未解决时声称完成。

Final Delivery
- 输出修改文件列表。
- 输出主要设计决策。
- 输出执行过的命令。
- 输出测试结果。
- 输出剩余限制和后续工作。
- 明确说明哪些能力是当前 demo 已实现，哪些只是后续生产化方向。
```

## 为什么这份 Prompt 能体现高级 AI 编程能力

- 它不是“帮我写一个 Text-to-SQL 项目”，而是把业务目标、用户、架构边界、失败路径和验收标准都写清楚。
- 它把 AI 约束在可验证的工程流程中：先计划、小步实现、运行验证、失败先修复。
- 它要求 provider-neutral LLM、Mock 测试、SQL 安全、Trace 和日志脱敏，体现“让 AI 写接近生产级代码”的约束能力。
- 它保留 demo 边界，不把项目包装成完整生产系统，适合面试中诚实表达。
