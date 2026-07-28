# Codex 项目执行计划

> 本文是**基于当前代码仓库反向复盘整理的重构版 Prompt / Prompt Playbook**，不是历史真实聊天记录，也不声称为当时逐字使用过的 Prompt。

这份执行计划的目标，是把当前 Text-to-SQL Agent demo 拆成适合 AI coding agent 执行的小里程碑。每个 Milestone 都遵循同一节奏：

1. **先计划**：Codex 必须先说明修改文件、类/函数、影响面、风险和回滚方式。
2. **再实现**：只做当前 Milestone 范围内的最小改动，避免无关重构。
3. **再验证**：运行该阶段要求的 lint、typecheck、test、build 或人工验证。
4. **再总结**：报告修改文件、设计决策、验证结果、剩余风险。

全局失败规则：

- 任一 lint、typecheck、test、build 或 demo 验证失败时，**必须停止推进后续 Milestone**。
- 先复述失败命令和失败摘要，再定位到具体文件、测试或断言。
- 只做最小修复，修复后先重跑失败命令，再重跑对应范围的完整验证。
- 不得通过删除测试、放宽安全约束、绕过架构边界来“修复”失败。
- 如果失败来自外部环境，必须记录命令、错误、影响和人工验证方式，不能声称已通过。

## Milestone 0：需求澄清与证据基线

### 目标

把“做一个 Text-to-SQL Agent demo”收敛成可执行 MVP，并建立真实代码证据、合理推断、待确认三类边界。

### 涉及文件

- `README.md`
- `AGENTS.md`
- `pyproject.toml`
- `frontend/package.json`
- `workflow.yaml`
- `docs/codex-retrospective/00-project-analysis.md`

### 具体任务

1. 先计划：扫描项目入口、依赖、测试命令、核心配置，列出证据来源。
2. 再实现：整理目标用户、核心场景、MVP、不做事项、验收路径。
3. 再验证：确认每个技术主张都能对应到文件、配置、测试或明确标注为推断。
4. 再总结：输出需求边界、风险和后续 Milestone 切分。

### Codex Prompt

```text
你是我的 AI 编程项目复盘顾问和 Staff Engineer。

Goal
基于当前仓库整理 Text-to-SQL demo 的 MVP、边界和证据基线。

Context
当前仓库已有 FastAPI 后端、React 前端、workflow.yaml、pytest/ruff、Vitest/typecheck/build，以及 docs/codex-retrospective 文档。

Constraints
- 不改业务代码。
- 不伪造历史聊天记录。
- 每个判断必须标注为真实代码证据、合理推断或待确认。
- 不把 demo 包装成完整生产系统。

Tasks
1. 扫描 README、pyproject.toml、frontend/package.json、workflow.yaml。
2. 总结目标用户、MVP、非 MVP、核心成功路径、修复路径、终止路径。
3. 输出证据表和待确认项。

Done when
- MVP 和不做事项清晰。
- 关键技术主张能对应到真实文件。
- 不存在把推断写成事实的表述。

Verification
- rg 检查文档中是否出现“历史逐字 Prompt”“已生产可用”等危险表述。
- 人工评审证据链。

Failure rule
如果无法确认某个主张，改为“推断”或“待确认”，不要继续扩写。

Report
总结证据来源、需求边界、剩余待确认项。
```

### 验收标准

- 项目目标、用户场景、MVP 和不做事项清楚。
- 文档明确“基于当前代码仓库反向复盘整理”。
- 每个阶段都能追溯到仓库文件或标注为推断。

### 验证命令

```bash
rg -n "历史逐字|原始 Prompt|生产可用|完整生产" docs/codex-retrospective
rg -n "真实代码证据|合理推断|待确认" docs/codex-retrospective/00-project-analysis.md
```

### 风险点

- 把复盘 Prompt 误写成历史真实聊天记录。
- 把 demo 级能力夸大成生产级能力。
- 引用不存在或已漂移的文件路径。

### 回滚策略

- 只回退本 Milestone 新增或修改的复盘文档段落。
- 保留真实证据表，删除无法证明的结论。

## Milestone 1：后端脚手架与质量工具

### 目标

建立最小可运行后端骨架，配置 Python 依赖、ruff、pytest 和健康检查。

### 涉及文件

- `pyproject.toml`
- `src/text_to_sql_demo/main.py`
- `src/text_to_sql_demo/__init__.py`
- `tests/unit/test_app_health.py`
- `README.md`

### 具体任务

1. 先计划：列出 Python package、FastAPI 入口、测试和配置文件。
2. 再实现：创建 `create_app()`、`/health`、最小 pytest、ruff 配置。
3. 再验证：运行 ruff 和健康检查测试。
4. 再总结：报告启动命令、测试命令和暂未实现的业务能力。

### Codex Prompt

```text
请执行 Milestone 1：后端脚手架。

Goal
创建最小可运行 FastAPI 后端和质量工具。

Context
项目目标是 Text-to-SQL Agent demo，但当前阶段只做后端骨架，不实现 workflow、LLM 或 SQL。

Constraints
- 编码前先输出文件计划、函数计划、影响面和回滚方式。
- 使用 Python 3.11+、FastAPI、Pydantic、pytest、ruff。
- 不新增 LangChain、LangGraph、数据库迁移框架或外部服务依赖。
- 公共函数必须有类型注解。

Tasks
1. 配置 pyproject.toml。
2. 创建 src/text_to_sql_demo/main.py 和 create_app()。
3. 添加 /health。
4. 添加 tests/unit/test_app_health.py。
5. README 补充后端启动和测试命令。

Done when
- /health 返回稳定 JSON。
- ruff 和健康检查测试通过。
- README 能指导本地启动。

Verification
- ruff check .
- python -m pytest tests/unit/test_app_health.py

Failure rule
任一命令失败时停止推进，先修复脚手架。

Report
说明新增文件、设计决策、验证结果和下一步。
```

### 验收标准

- `create_app()` 可被测试导入。
- `/health` 测试通过。
- `pyproject.toml` 中测试和 lint 配置可执行。

### 验证命令

```bash
ruff check .
python -m pytest tests/unit/test_app_health.py
```

### 风险点

- 一开始引入过多依赖，导致后续维护负担变大。
- 把业务逻辑写进 API 入口，影响后续分层。

### 回滚策略

- 回退 `src/text_to_sql_demo/main.py`、健康检查测试和 `pyproject.toml` 中本阶段新增配置。
- 若依赖配置失败，恢复到最小依赖集合后重新验证。

## Milestone 2：Workflow Core

### 目标

实现可配置 workflow 引擎、类型化状态、节点接口、注册表和工厂，为后续业务节点建立架构边界。

### 涉及文件

- `workflow.yaml`
- `src/text_to_sql_demo/config/models.py`
- `src/text_to_sql_demo/workflow/state.py`
- `src/text_to_sql_demo/workflow/node.py`
- `src/text_to_sql_demo/workflow/registry.py`
- `src/text_to_sql_demo/workflow/factory.py`
- `src/text_to_sql_demo/workflow/engine.py`
- `tests/unit/workflow/*`

### 具体任务

1. 先计划：列出状态模型、节点接口、注册表、工厂、引擎职责。
2. 再实现：实现 `WorkflowState`、`TraceEvent`、`BaseNode`、`NodeResult`、`NodeRegistry`、`NodeFactory`、`WorkflowEngine`。
3. 再验证：添加 dummy node 测试、缺失节点测试、max_steps 测试、架构约束测试。
4. 再总结：说明 workflow 是否影响 node/state/API，以及新增节点如何扩展。

### Codex Prompt

```text
请执行 Milestone 2：Workflow Core。

Goal
建立可配置、多节点、可 Trace 的轻量 WorkflowEngine。

Context
项目要求工作流流转由 workflow.yaml 决定，节点通过 BaseNode/NodeResult 通信，新增节点不应修改 WorkflowEngine 或 NodeFactory。

Constraints
- 编码前先输出文件、类、函数计划。
- WorkflowEngine 不得导入具体业务节点。
- NodeFactory 不得使用 if/elif 或 match/case 分发具体 node type。
- 工作流分支必须基于 NodeResult.outcome 和配置。
- 每个节点执行必须产生 TraceEvent。

Tasks
1. 定义 WorkflowState、TraceEvent、NodeResult。
2. 定义 BaseNode 生命周期接口。
3. 实现 NodeRegistry 和 register_node。
4. 实现 NodeFactory。
5. 实现 WorkflowEngine：start_node、edges、terminal、max_steps、trace。
6. 添加架构约束测试。

Done when
- dummy workflow 可按配置执行到 terminal。
- 未注册节点、缺失边、max_steps 有明确错误。
- 架构测试证明 engine/factory 不依赖具体节点。

Verification
- ruff check .
- python -m pytest tests/unit/workflow

Failure rule
如果架构测试失败，不放宽测试；先修设计。

Report
输出修改文件、扩展方式、验证结果和剩余风险。
```

### 验收标准

- 新增节点不需要修改 `WorkflowEngine` 或 `NodeFactory`。
- `NodeResult.outcome` 能驱动配置化流转。
- workflow trace 可记录节点执行结果。

### 验证命令

```bash
ruff check .
python -m pytest tests/unit/workflow
```

### 风险点

- 引擎耦合具体业务节点，后续扩展困难。
- 工厂使用分支硬编码 node type。
- 没有 max_steps，存在循环风险。

### 回滚策略

- 回退 workflow core 文件和相关测试。
- 若模型设计不稳定，保留接口草案，先删除不必要的实现细节。

## Milestone 3：Schema、Retrieval 与 Prompt Builder

### 目标

实现 Schema 读取、Schema Linking、Reference SQL/Knowledge/Metric/Semantic Model 的轻量 Top-K 检索，并把 Prompt 从 API route 中抽离。

### 涉及文件

- `src/text_to_sql_demo/schema/*`
- `src/text_to_sql_demo/retrieval/examples.py`
- `src/text_to_sql_demo/retrieval/knowledge.py`
- `src/text_to_sql_demo/retrieval/patterns.py`
- `src/text_to_sql_demo/prompts/builder.py`
- `src/text_to_sql_demo/prompts/templates.py`
- `configs/prompts/*.yaml`
- `tests/unit/schema/*`
- `tests/unit/retrieval/*`
- `tests/unit/prompts/*`

### 具体任务

1. 先计划：说明 Schema metadata、Top-K 检索、PromptBuilder 的边界。
2. 再实现：读取 SQLite schema，基于问题选择相关表字段，加载 YAML 示例和知识片段。
3. 再验证：测试 Top-K、prompt summary、模板渲染和上下文裁剪。
4. 再总结：说明 Prompt 中注入了什么、没有注入什么。

### Codex Prompt

```text
请执行 Milestone 3：Schema、Retrieval 与 Prompt Builder。

Goal
让系统能选择相关 schema 和上下文，并构造可控 Prompt。

Context
Workflow core 已完成。现在要实现 SchemaLinking、Example Retrieval、Knowledge Retrieval 和 PromptBuilder。

Constraints
- 编码前先输出计划，列出涉及文件和测试。
- Prompt 不得写在 API route 或节点的大段字符串中。
- 只注入 linked schema、Top-K examples、RAG context summary。
- 不把完整 schema、完整 prompt 或敏感配置写入日志。
- 检索默认使用 SQLite/YAML fallback，不引入强依赖向量库。

Tasks
1. 定义 database schema metadata。
2. 实现 SQLite introspection。
3. 实现 SchemaLinker Top-K 表/字段选择。
4. 实现 ExampleStore/KnowledgeStore/BusinessPatternStore。
5. 实现 PromptBuilder 和 YAML template loader。
6. 添加 unit tests。

Done when
- PromptBuilder 可基于裁剪上下文生成生成/修复 Prompt。
- prompt summary 只包含计数、方言和摘要信息。
- Top-K 结果可测试、可解释。

Verification
- ruff check .
- python -m pytest tests/unit/schema tests/unit/retrieval tests/unit/prompts

Failure rule
如果 prompt 测试显示注入全量 schema 或敏感信息，停止推进并修复。

Report
总结上下文裁剪策略、测试覆盖和限制。
```

### 验收标准

- Schema Linking 不返回全量 schema。
- Top-K 检索有确定性测试。
- Prompt 模板可配置，不散落在 API route。

### 验证命令

```bash
ruff check .
python -m pytest tests/unit/schema tests/unit/retrieval tests/unit/prompts
```

### 风险点

- Prompt 过大，注入无关 schema。
- 词法 Top-K 召回有限，容易被误解成生产 RAG。
- 模板和代码耦合过紧，后续难调优。

### 回滚策略

- 回退新增检索和 PromptBuilder 代码。
- 保留 schema metadata 类型，重新实现更小的 Top-K 策略。

## Milestone 4：LLM 抽象、模型路由与 SQL 生成节点

### 目标

建立 provider-neutral LLM 接口、Mock LLM 测试能力、OpenAI-compatible adapter 和基于复杂度的模型 alias 路由。

### 涉及文件

- `src/text_to_sql_demo/llm/client.py`
- `src/text_to_sql_demo/llm/factory.py`
- `src/text_to_sql_demo/llm/providers.py`
- `src/text_to_sql_demo/llm/mock.py`
- `src/text_to_sql_demo/routing/*`
- `src/text_to_sql_demo/nodes/sql_generation.py`
- `tests/unit/llm/*`
- `tests/unit/routing/*`
- `tests/unit/nodes/test_*generation*`

### 具体任务

1. 先计划：说明 LLM 协议、Mock、provider adapter、模型 alias 的边界。
2. 再实现：定义 `LLMClient`、`MockLLMClient`、OpenAI-compatible client、complexity routing。
3. 再验证：用 Mock 覆盖 sequence、alias responses、provider 错误和路由。
4. 再总结：说明真实模型名称从配置读取，不硬编码在业务节点。

### Codex Prompt

```text
请执行 Milestone 4：LLM 抽象与 SQL 生成。

Goal
让 SQLGenerationNode 通过 provider-neutral LLMClient 生成 SQL，并支持 Mock 测试和模型 alias 路由。

Context
Schema/Retrieval/PromptBuilder 已完成。现在需要接入 LLM，但测试不能依赖真实付费 API。

Constraints
- 编码前先输出文件计划和测试计划。
- 业务节点只依赖 LLMClient 协议。
- 不在业务代码中硬编码真实模型名称。
- 测试必须使用 MockLLMClient。
- 日志和响应不得包含 API key、Authorization、完整 prompt。

Tasks
1. 定义 LLMClient request/response 模型。
2. 实现 MockLLMClient。
3. 实现 OpenAI-compatible adapter。
4. 实现 build_llm_client。
5. 实现 complexity routing：light/strong alias。
6. 实现 SQLGenerationNode。

Done when
- MockLLM 可按 alias 或 sequence 返回 SQL。
- SQLGenerationNode 输出 selected_model、routing_reason、generated_sql。
- provider 错误映射为项目自定义异常。

Verification
- ruff check .
- python -m pytest tests/unit/llm tests/unit/routing tests/unit/nodes/test_*generation*

Failure rule
如果测试需要真实 API key 才能通过，停止并改为 Mock。

Report
总结 provider 抽象、模型路由和敏感信息处理。
```

### 验收标准

- 测试不依赖真实 LLM。
- 模型 alias 和真实模型分离。
- provider 错误不会泄露密钥或完整 prompt。

### 验证命令

```bash
ruff check .
python -m pytest tests/unit/llm tests/unit/routing tests/unit/nodes/test_*generation*
```

### 风险点

- 节点直接绑定某个供应商 SDK。
- 测试隐式依赖网络或付费 API。
- 日志输出完整 prompt 或密钥。

### 回滚策略

- 回退 provider adapter，保留 `LLMClient` 协议和 Mock。
- 若路由设计过度复杂，恢复到 `light/strong` 两级 alias。

## Milestone 5：SQL 校验、执行与修复闭环

### 目标

实现 SQLGlot 校验、只读执行、错误分类、反思修复和最多三次尝试的终止条件。

### 涉及文件

- `src/text_to_sql_demo/sql/validator.py`
- `src/text_to_sql_demo/execution/sql_executor.py`
- `src/text_to_sql_demo/reflection/policy.py`
- `src/text_to_sql_demo/reflection/sql_context_memory.py`
- `src/text_to_sql_demo/nodes/sql_validation.py`
- `src/text_to_sql_demo/nodes/sql_execution.py`
- `src/text_to_sql_demo/nodes/error_reflection.py`
- `src/text_to_sql_demo/nodes/sql_fix.py`
- `src/text_to_sql_demo/nodes/hitl.py`
- `tests/unit/sql/*`
- `tests/unit/execution/*`
- `tests/unit/nodes/*reflection*`
- `tests/integration/test_sql_repair_workflow.py`

### 具体任务

1. 先计划：列出 SQL 安全、执行、反思和 HITL 的边界。
2. 再实现：SQL parse、只读 SELECT、多语句拒绝、schema 校验、执行、错误分类、修复节点。
3. 再验证：覆盖成功、未知字段修复、持续失败三次后 HITL。
4. 再总结：说明应用层校验和生产数据库权限隔离的区别。

### Codex Prompt

```text
请执行 Milestone 5：SQL 校验、执行与修复闭环。

Goal
让系统安全地校验和执行只读 SQL，并在失败时有限修复，最多 3 次后进入 HITL。

Context
SQLGenerationNode 已能生成 SQL。现在要确保不会直接执行 LLM 原始输出。

Constraints
- 编码前先输出修改计划、风险和回滚策略。
- SQLValidator 必须拒绝写入、DDL、多语句和未知表字段。
- SQLExecutionNode 只能执行已校验 SQL。
- 修复循环最多 3 次，必须有明确终止条件。
- 日志默认只记录 SQL length/hash，不记录完整 SQL。

Tasks
1. 实现 SQLValidator。
2. 实现 SQLExecutor。
3. 实现 ReflectionDecisionNode。
4. 实现 FixSQLNode。
5. 实现 HITLNode。
6. 添加成功、修复、终止路径测试。

Done when
- 合法 SELECT 可执行。
- 写入/DDL/多语句被拒绝。
- unknown_column 可进入修复路径并成功。
- 连续失败最多 3 次进入 needs_human_review。

Verification
- ruff check .
- python -m pytest tests/unit/sql tests/unit/execution tests/unit/nodes tests/integration/test_sql_repair_workflow.py

Failure rule
如果安全测试失败，停止所有后续功能，先修 SQL 安全边界。

Report
说明 SQL 防线、修复终止条件、测试结果和生产化限制。
```

### 验收标准

- 写入 SQL、DDL、多语句不能执行。
- 修复循环有上限，不会无限跑。
- HITL 状态和错误信息可被 API/前端展示。

### 验证命令

```bash
ruff check .
python -m pytest tests/unit/sql tests/unit/execution tests/unit/nodes tests/integration/test_sql_repair_workflow.py
```

### 风险点

- 应用层只读校验被误当作生产权限隔离。
- 修复路径递归或循环失控。
- 执行节点绕过校验直接运行 SQL。

### 回滚策略

- 回退修复节点，保留只读 SQL 校验和执行。
- 若修复策略不稳定，先将失败路由到 HITL，避免错误 SQL 被自动执行。

## Milestone 6：API Service、Metadata 与 Runtime Config

### 目标

将 workflow 串入 FastAPI API，沉淀运行记录、Trace、收藏 SQL、反馈，并支持短生命周期 runtime config。

### 涉及文件

- `src/text_to_sql_demo/api/models.py`
- `src/text_to_sql_demo/api/service.py`
- `src/text_to_sql_demo/main.py`
- `src/text_to_sql_demo/metadata/store.py`
- `src/text_to_sql_demo/memory/trusted.py`
- `src/text_to_sql_demo/runtime/*`
- `tests/integration/test_api_workflow.py`
- `tests/integration/test_metadata_api.py`
- `tests/integration/test_runtime_config_api.py`

### 具体任务

1. 先计划：列出 API route、service、metadata、runtime config 的职责边界。
2. 再实现：`/api/v1/query`、schema、SQL execute、runs、saved queries、feedback、runtime config。
3. 再验证：API 集成测试、错误响应、脱敏、metadata 隔离。
4. 再总结：说明哪些写入内部库，哪些不写目标业务库。

### Codex Prompt

```text
请执行 Milestone 6：API Service、Metadata 与 Runtime Config。

Goal
把 workflow 暴露为可演示 API，并沉淀运行记录、Trace、收藏 SQL 和反馈。

Context
核心 workflow、LLM、SQL 校验执行和修复闭环已完成。现在需要 API 层和内部数据沉淀。

Constraints
- 编码前先输出 API/Service/Store 文件计划。
- API route 保持薄，不写 Prompt 或复杂业务编排。
- 内部 metadata store 可以写入；目标业务库默认只读。
- runtime config 使用 SecretStr 或等价脱敏机制。
- 响应和日志不得返回 API key、Authorization、数据库密码、完整数据库 URL。

Tasks
1. 实现 QueryRequest/QueryResponse 等 Pydantic models。
2. 实现 TextToSQLApiService 串通 workflow。
3. 实现 runs、saved_queries、feedback API。
4. 实现 runtime config store、resolver 和 options。
5. 实现统一错误响应。
6. 添加集成测试。

Done when
- POST /api/v1/query 可跑通成功、修复、终止路径。
- runs 可按 request_id 查询 trace。
- saved query 默认 draft，approved 才进入可信上下文。
- runtime config 响应脱敏。

Verification
- ruff check .
- python -m pytest tests/integration/test_api_workflow.py tests/integration/test_metadata_api.py tests/integration/test_runtime_config_api.py

Failure rule
如果 API 错误响应泄露敏感信息，停止并先修脱敏。

Report
总结 API 契约、内部写入边界、验证结果和限制。
```

### 验收标准

- API handler 不硬编码 workflow 细节。
- metadata 和业务目标库隔离。
- runtime config 过期、脱敏和连接失败场景可测试。

### 验证命令

```bash
ruff check .
python -m pytest tests/integration/test_api_workflow.py tests/integration/test_metadata_api.py tests/integration/test_runtime_config_api.py
```

### 风险点

- 路由层膨胀，业务逻辑散落。
- metadata 写入目标业务库。
- runtime config 泄露密钥。

### 回滚策略

- 回退新增 API route，保留 service 层可测试能力。
- 如果 runtime config 风险过高，回退到只支持默认配置并记录限制。

## Milestone 7：前端工作台

### 目标

构建 React/Vite/TypeScript 工作台，支持自然语言查询、运行配置、SQL 展示与编辑执行、结果表格、历史、反馈和 Debug Trace。

### 涉及文件

- `frontend/package.json`
- `frontend/vite.config.ts`
- `frontend/src/App.tsx`
- `frontend/src/api/client.ts`
- `frontend/src/api/config.ts`
- `frontend/src/components/*`
- `frontend/src/styles.css`
- `frontend/src/lib/*`
- `frontend/src/**/*.test.ts`
- `frontend/src/**/*.test.tsx`

### 具体任务

1. 先计划：列出组件拆分、API client、状态流、错误展示和测试计划。
2. 再实现：查询输入、运行配置、SQL 面板、结果面板、历史面板、Debug 面板。
3. 再验证：运行前端 test、typecheck、build。
4. 再总结：说明用户视角和开发者 Debug 视角如何分层。

### Codex Prompt

```text
请执行 Milestone 7：前端工作台。

Goal
实现可用于 demo 的 React 工作台，而不是 landing page。

Context
后端 API 已提供 query、schema、sql execute、runs、saved queries、feedback、runtime config。

Constraints
- 编码前先输出组件计划、API 类型计划和测试计划。
- 第一屏是实际工作台，不做营销页。
- 不把密钥写入 localStorage。
- 用户错误和技术错误分层展示。
- Debug 面板可以展示 trace、routing、Top-K、修复历史，但不得展示完整密钥。
- UI 改动保持小步，不顺手重写无关组件。

Tasks
1. 实现 API client 和类型。
2. 实现 QueryComposer。
3. 实现 RuntimeConfigPanel。
4. 实现 ResultPanel 和 SqlPanel。
5. 实现 HistoryPanel、DebugPanel、feedback。
6. 添加 Vitest 测试。

Done when
- 用户能提交自然语言查询并看到 SQL、结果和摘要。
- 用户能编辑只读 SQL 并执行。
- Debug 面板能看到 trace 和修复历史。
- 错误状态清晰可读。

Verification
- cd frontend && npm test
- cd frontend && npm run typecheck
- cd frontend && npm run build

Failure rule
如果前端 test/typecheck/build 任一失败，停止新增 UI，先修失败。

Report
总结组件结构、API 契约、验证结果和 UI 限制。
```

### 验收标准

- 前端首屏是可操作工作台。
- API client 有类型约束和错误包装。
- Debug 信息可用于解释 workflow 过程。

### 验证命令

```bash
cd frontend && npm test
cd frontend && npm run typecheck
cd frontend && npm run build
```

### 风险点

- 前端保存密钥或敏感配置。
- 组件一次性过大，后续难维护。
- 技术错误直接暴露给普通用户。

### 回滚策略

- 回退本阶段新增组件，保留 API client 和最小 App。
- 如果 UI 状态管理复杂化，回退到单页受控状态，再小步拆分。

## Milestone 8：测试补齐与端到端演示

### 目标

系统性补齐单元测试、集成测试、关键用户路径测试和本地 demo 脚本，确保成功、修复、终止路径可复现。

### 涉及文件

- `tests/unit/*`
- `tests/integration/*`
- `scripts/run_demo.py`
- `frontend/src/**/*.test.ts`
- `frontend/src/**/*.test.tsx`
- `README.md`

### 具体任务

1. 先计划：列出测试矩阵、fixture、Mock LLM sequence 和断言。
2. 再实现：补足成功路径、修复路径、终止路径、架构约束、安全边界、前端关键交互测试。
3. 再验证：运行完整后端、demo、前端测试和构建。
4. 再总结：说明测试覆盖了哪些风险，哪些仍需人工验证。

### Codex Prompt

```text
请执行 Milestone 8：测试补齐与端到端演示。

Goal
用测试锁住 Text-to-SQL demo 的核心行为和 AI 生成代码的架构边界。

Context
后端、前端和核心 workflow 已实现。现在不新增业务功能，只补测试、fixture 和 demo 验证。

Constraints
- 编码前先输出测试计划。
- 不调用真实付费 LLM API。
- 不连接外部数据库；使用 SQLite fixture。
- 失败测试不能通过放宽 SQL 安全、删除断言或跳过测试解决。
- 前端测试覆盖用户主要交互，不追求脆弱快照。

Tasks
1. 覆盖 workflow core 和架构约束。
2. 覆盖 SQL validator/executor 安全边界。
3. 覆盖 Mock LLM 成功、修复、终止路径。
4. 覆盖 metadata、runtime config、observability。
5. 覆盖前端 API client 和关键工作台交互。
6. 更新 scripts/run_demo.py 或 README demo 命令。

Done when
- 后端完整 pytest 通过。
- 前端 test/typecheck/build 通过。
- demo 脚本可展示成功、修复、终止路径中的关键场景。

Verification
- ruff check .
- python -m pytest
- python scripts/run_demo.py
- cd frontend && npm test
- cd frontend && npm run typecheck
- cd frontend && npm run build

Failure rule
任何验证失败都停止推进，先分类为实现 bug、测试假设错误或环境问题，再做最小修复。

Report
总结测试矩阵、验证输出和剩余风险。
```

### 验收标准

- 成功路径、修复路径、终止路径都有集成测试。
- 架构约束测试能防止 engine/factory 依赖具体节点。
- 前端构建和类型检查通过。

### 验证命令

```bash
ruff check .
python -m pytest
python scripts/run_demo.py
cd frontend && npm test
cd frontend && npm run typecheck
cd frontend && npm run build
```

### 风险点

- 测试只检查状态码，不断言关键业务字段。
- 测试依赖真实 LLM 或外部数据库。
- 为了通过测试而弱化安全规则。

### 回滚策略

- 如果新增测试假设错误，回退该测试并补充正确 fixture。
- 如果实现暴露 bug，保留测试，回退有问题的实现后重新修复。

## Milestone 9：可观测性、日志脱敏与错误边界

### 目标

统一结构化日志、Trace、错误响应、SQL/prompt 脱敏和可恢复/不可恢复错误分级。

### 涉及文件

- `src/text_to_sql_demo/observability/*`
- `src/text_to_sql_demo/exceptions.py`
- `src/text_to_sql_demo/api/service.py`
- `src/text_to_sql_demo/workflow/state.py`
- `tests/unit/observability/*`
- `tests/integration/test_observability_api.py`
- `tests/integration/test_observability_workflow.py`

### 具体任务

1. 先计划：列出日志字段、脱敏字段、异常边界和测试计划。
2. 再实现：结构化日志、redaction、SQL hash、TraceEvent、统一错误响应。
3. 再验证：观测性单元/集成测试，敏感字段 grep。
4. 再总结：说明哪些信息默认不记录，debug 模式允许什么。

### Codex Prompt

```text
请执行 Milestone 9：可观测性、日志脱敏与错误边界。

Goal
让 Text-to-SQL workflow 可追踪、可定位，同时不泄露敏感信息。

Context
系统已有 workflow、API、SQL、LLM 和 runtime config。现在需要统一日志和错误边界。

Constraints
- 编码前先输出日志字段、异常边界和测试计划。
- 底层函数抛明确异常，边界层统一记录结构化日志。
- 日志必须包含 request_id、node_name、event、error_type 等上下文。
- 不记录 API key、Authorization、数据库密码、完整数据库 URL、完整 prompt、完整 SQL、完整结果集。
- SQL 默认只记录 length/hash。

Tasks
1. 实现或整理 project exceptions。
2. 实现 redaction 工具和格式化器。
3. 在 workflow/API/service/provider 边界记录结构化日志。
4. 确保 TraceEvent 可定位节点状态。
5. 添加日志和脱敏测试。

Done when
- 可恢复 SQL 失败记录为 warning。
- 系统配置、provider、数据库连接等不可恢复问题记录为 error。
- 测试证明敏感信息不会出现在日志和响应中。

Verification
- ruff check .
- python -m pytest tests/unit/observability tests/integration/test_observability_api.py tests/integration/test_observability_workflow.py

Failure rule
如果发现敏感信息泄露，停止推进并优先修复脱敏。

Report
总结日志字段、异常边界、脱敏策略和验证结果。
```

### 验收标准

- 日志可定位 request 和 node。
- 敏感信息默认脱敏。
- 可恢复错误和不可恢复错误分级清楚。

### 验证命令

```bash
ruff check .
python -m pytest tests/unit/observability tests/integration/test_observability_api.py tests/integration/test_observability_workflow.py
```

### 风险点

- 在多个底层函数重复 `logger.error(...); raise ...`，造成噪音。
- 日志中泄露完整 SQL、prompt 或凭据。
- 错误响应对用户不可理解。

### 回滚策略

- 回退新增日志点，保留 redaction 工具和测试。
- 如果结构化日志设计不稳定，先只在 API/service/workflow 边界记录。

## Milestone 10：文档、运行手册与面试复盘材料

### 目标

整理 README、架构说明、运行手册和 codex retrospective 文档，使项目可演示、可复盘、可用于面试。

### 涉及文件

- `README.md`
- `docs/*.md`
- `docs/codex-retrospective/00-project-analysis.md`
- `docs/codex-retrospective/01-master-prompt.md`
- `docs/codex-retrospective/02-iteration-prompts.md`
- `docs/codex-retrospective/03-production-grade-checklist.md`
- `docs/codex-retrospective/04-interview-story.md`
- `docs/codex-retrospective/05-ai-coding-workflow.md`
- `docs/codex-retrospective/06-execution-plan.md`

### 具体任务

1. 先计划：列出文档导航、需要同步的真实路径、运行命令和复盘口径。
2. 再实现：更新项目概览、启动命令、测试命令、架构说明、生产化短板、面试话术。
3. 再验证：检查命令、链接、旧路径、历史夸大表述。
4. 再总结：说明哪些内容来自真实仓库，哪些是复盘推断。

### Codex Prompt

```text
请执行 Milestone 10：文档、运行手册与面试复盘材料。

Goal
把当前 Text-to-SQL demo 整理成可运行、可审查、可面试复盘的项目材料。

Context
代码仓库已有后端、前端、测试、workflow、observability、runtime config 和 docs/codex-retrospective。

Constraints
- 不改业务代码。
- 不伪造历史真实聊天记录。
- 不说 Prompt 是当时逐字使用。
- 所有文件路径和命令必须基于当前仓库。
- 无法确认的信息标注为推断或待确认。

Tasks
1. 同步 README 文档导航和启动命令。
2. 更新架构、模块职责、运行配置、观测性说明。
3. 完善 codex retrospective：Master Prompt、迭代 Prompt、生产级 checklist、面试故事、工作流方法论、执行计划。
4. 检查文档中是否有旧组件名或旧命令。

Done when
- 新人能根据 README 启动项目。
- 面试官能根据 retrospective 理解 AI 编程方法论。
- 文档清楚区分真实证据、合理推断和待确认。

Verification
- rg 检查旧路径和危险夸大表述。
- ruff check .
- python -m pytest

Failure rule
如果文档命令无法验证，标注待确认；不要写成已通过。

Report
输出修改文档、同步依据、验证命令和剩余限制。
```

### 验收标准

- 文档导航清晰。
- Prompt Playbook 具备 Goal/Context/Constraints/Done when/Verification/Failure rule。
- 面试话术诚实说明“复盘整理”，不伪造历史。

### 验证命令

```bash
rg -n "历史逐字|原始 Prompt|生产可用|完整生产" docs README.md
ruff check .
python -m pytest
```

### 风险点

- 文档和代码结构不同步。
- 面试话术夸大项目生产成熟度。
- 把反向复盘 Prompt 说成历史原始 Prompt。

### 回滚策略

- 回退不准确的文档段落。
- 保留事实证据，删除无法验证的历史叙述。

## Milestone 11：生产化加固 Backlog

### 目标

在不把 demo 扩成重型平台的前提下，形成后续生产化加固任务池。

### 涉及文件

- `docs/codex-retrospective/03-production-grade-checklist.md`
- `README.md`
- `docs/*.md`
- 可选后续：`.github/workflows/*`
- 可选后续：`Dockerfile`

### 具体任务

1. 先计划：按 P0/P1/P2 给生产化缺口排序。
2. 再实现：仅做低风险高收益文档或测试增强；复杂能力进入 backlog。
3. 再验证：确认没有把 backlog 写成已完成功能。
4. 再总结：输出后续加固路线和每项 Prompt 示例。

### Codex Prompt

```text
请执行 Milestone 11：生产化加固 Backlog。

Goal
识别当前 demo 距离生产级代码的差距，并生成后续可执行加固任务。

Context
项目已具备 workflow、LLM abstraction、SQL safety、metadata、runtime config、frontend 和测试，但仍是轻量 demo。

Constraints
- 先输出风险分级，不直接大改。
- 不实现完整认证、多租户、BI 平台、scheduler、MCP 或多 Agent 工作台。
- 不编造性能指标、召回率或生产 SLA。
- 每项加固都要有验收标准和验证方式。

Tasks
1. 列出 P0：SQL 权限隔离、密钥托管、敏感日志。
2. 列出 P1：CI/CD、部署、provider 稳定性、runtime config 持久化。
3. 列出 P2：RAG 评估、Schema YAML loader、前端 UX、文档同步。
4. 为每项写可交给 Codex 的 Prompt 示例。

Done when
- checklist 清楚区分已实现、demo 限制、后续方向。
- 每项 backlog 都有 Prompt、验收标准、验证命令。

Verification
- 人工评审是否存在夸大。
- rg 检查“已生产可用”等危险表述。

Failure rule
如果某项能力没有代码证据，必须写成“后续方向”。

Report
输出加固优先级、原因、Prompt 示例和诚实边界。
```

### 验收标准

- 生产化差距按优先级排序。
- 每项都有可执行 Prompt 示例。
- 没有把 backlog 写成已完成。

### 验证命令

```bash
rg -n "已生产可用|完整生产|性能指标|召回率" docs/codex-retrospective README.md
```

### 风险点

- 为了显得高级，引入过重平台能力。
- 把生产化建议写成当前能力。
- 没有为 backlog 配验收和验证方式。

### 回滚策略

- 回退夸大的生产化描述。
- 保留 P0/P1/P2 风险表，把无法确认的改为待确认。

## 我作为人类开发者如何审查 Codex 输出

我不会把 Codex 输出直接当成最终交付，而是按以下方式审查：

### 1. 审查计划

- 看 Codex 是否先列出修改文件、类/函数、影响面和风险。
- 检查本轮是否只覆盖一个 Milestone。
- 如果计划包含无关重构、新依赖或重型平台能力，要求收敛。

### 2. 审查架构边界

- `WorkflowEngine` 是否仍不导入具体节点。
- `NodeFactory` 是否仍通过 `NodeRegistry` 解析，而不是 if/elif 分发。
- Prompt 是否仍由 `PromptBuilder` 和模板管理，而不是写进 API route。
- LLM 是否仍通过 provider-neutral `LLMClient`，业务节点没有硬编码模型名称。

### 3. 审查安全边界

- SQL 是否经过 `SQLValidator` 后才执行。
- 写入、DDL、多语句、未知表字段是否仍被拒绝。
- SQL 修复循环是否仍最多 3 次并进入 HITL。
- 日志、响应、trace、metadata 是否没有 API key、Authorization、数据库密码、完整 prompt、完整 SQL。

### 4. 审查测试证据

- 后端是否运行 `ruff check .` 和对应 `pytest`。
- 前端变更是否运行 `npm test`、`npm run typecheck`、`npm run build`。
- 新增核心模块是否有单元测试。
- workflow 主链路是否覆盖成功、修复、终止路径。
- 测试失败时是否先定位和修复，而不是跳过测试。

### 5. 审查文档和诚实边界

- 文档中的路径和命令是否来自当前仓库。
- “真实代码证据 / 合理推断 / 待确认”是否区分清楚。
- 是否明确说明 retrospective 文档是反向复盘整理，不是历史逐字 Prompt。
- 是否没有宣称完整认证、多租户、生产级权限隔离、生产 SLA 或量化性能指标。

### 6. 审查最终报告

每个 Milestone 完成后，我要求 Codex 报告：

1. 新增或修改的文件。
2. 主要设计决策。
3. 执行过的命令。
4. 测试结果。
5. 是否影响 workflow / node / state / API / frontend。
6. 剩余限制或后续工作。
7. 如果有失败，失败原因、修复方式和重新验证结果。

这套审查流程体现的是：我把 Codex 当作受控协作工程师使用，而不是把项目质量完全交给 AI 自行决定。
