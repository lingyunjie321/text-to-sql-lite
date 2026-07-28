# 分阶段迭代 Prompt Playbook

> 本文是**基于当前代码仓库反向复盘整理的重构版 Prompt / Prompt Playbook**，不是历史真实聊天记录，也不声称为当时逐字使用过的 Prompt。

## 使用方式

每轮 Prompt 都包含固定结构：

- **Goal**：本轮目标。
- **Context**：给 Codex 的仓库背景和输入。
- **Constraints**：必须遵守的工程约束。
- **Done when**：可判定完成的验收标准。
- **Verification**：必须执行的命令。
- **Failure rule**：验证失败时如何处理。
- **Prompt**：可以直接交给 Codex 的指令。

这套 Playbook 的重点不是“一次性命令 AI 写完整项目”，而是展示如何用 Prompt 将模糊需求拆成可审查的小步任务。

## 1. 需求澄清 Prompt

**Goal**
把“做一个 Text-to-SQL demo”澄清为 MVP、用户场景、边界、不做事项和验收标准。

**Context**
当前只有模糊需求：运营/分析师用自然语言查数，希望展示 AI Agent、SQL 生成和工程化能力。

**Constraints**
- 先反问，不要直接写代码。
- 每个问题必须服务于范围收敛。
- 不要引入重型平台能力。
- 明确哪些是 MVP，哪些是后续生产化方向。

**Done when**
- 输出目标用户、核心场景、MVP 功能、非 MVP、不做事项。
- 输出成功路径、修复路径、终止路径的验收标准。
- 输出需要我确认的问题列表。

**Verification**
- 无代码验证；只评审需求说明是否具体、可执行、可验收。

**Failure rule**
- 如果需求仍然模糊，继续提问，不进入技术方案。

**Prompt**

```text
你是我的产品技术负责人和 Codex Prompt Reviewer。

Goal
把“做一个 Text-to-SQL Agent demo”澄清成一个可执行 MVP。

Context
目标用户是运营/分析师，他们用自然语言查询业务数据。数据团队维护可信上下文。项目需要展示 AI 编程、Prompt 约束、工程化和接近生产级代码意识。

Constraints
- 先反问关键问题，不要写代码。
- 不要引入认证、多租户、BI dashboard、scheduler、MCP、多 Agent 工作台等重型能力。
- 所有范围都要能在本地 demo 中验证。
- 必须区分 MVP / later / explicitly out of scope。

请输出：
1. 你需要我确认的 5-8 个关键问题。
2. 基于合理默认值给出 MVP 草案。
3. 明确不做事项。
4. 成功路径、修复路径、终止路径的验收标准。
5. 你会如何约束后续 AI 编码，避免它过度设计或乱改。

Done when
我能基于你的输出决定是否进入技术方案阶段。

Verification
- 人工检查 MVP 是否具体、可执行、可验收。
- 检查每个“later/out of scope”是否有清晰理由。

Failure rule
如果仍存在关键不确定项，不进入技术方案；先继续提问并收敛范围。
```

## 2. 技术方案 Prompt

**Goal**
让 Codex 提出架构方案，并解释为什么选择自研轻量 workflow、节点注册、Provider-neutral LLM 和 SQLGlot 校验。

**Context**
需求已收敛为轻量业务交付版 Text-to-SQL demo。

**Constraints**
- 只做方案，不写代码。
- 比较至少 2 种方案：简单脚本式、可配置 workflow、LangGraph/LangChain。
- 明确为什么不用 LangGraph/LangChain。
- 明确目录结构、数据流、模块职责和测试策略。

**Done when**
- 输出架构图、目录结构、关键模块职责、数据流、错误路径。
- 输出每个模块的验收标准。
- 输出风险和取舍。

**Verification**
- 人工评审架构是否满足需求和边界。

**Failure rule**
- 如果方案依赖未知框架或新增重型组件，退回重写方案。

**Prompt**

```text
你是 Staff Engineer，请为 Text-to-SQL Agent demo 设计技术方案。

Goal
产出可执行架构方案，后续 Codex 能按该方案小步实现。

Context
MVP 需要：FastAPI API、自研可配置 workflow、Schema Linking、Top-K 示例和知识库检索、LLM SQL 生成、SQLGlot 校验、SQLAlchemy 执行、反思修复、最多 3 次终止、Trace、React 前端演示。

Constraints
- 只做方案，不写代码。
- workflow engine 不使用 LangGraph/LangChain。
- LLM 必须 provider-neutral，测试必须可用 Mock。
- Prompt 不得写在 API route。
- 新增节点不得要求修改 WorkflowEngine 或 NodeFactory。
- SQL 默认只读，不要在业务代码中暴露数据库凭据。

请输出：
1. 方案比较：脚本式 / 自研 workflow / LangGraph-LangChain，每项优缺点。
2. 推荐方案和理由。
3. 目录结构草案。
4. 核心数据流 Mermaid 图。
5. 关键模块职责表。
6. 状态模型、节点接口、注册表、工厂和依赖注入设计。
7. SQL 生成、校验、执行、反思修复的状态转移。
8. 测试策略：unit、integration、frontend。
9. 风险与生产化短板。

Done when
我可以基于该方案进入脚手架阶段。

Verification
- 人工评审方案是否满足架构约束和 MVP。
- 检查目录结构、数据流、状态流转和测试策略是否可落地。

Failure rule
如果方案依赖重型框架、硬编码流程或真实 LLM 测试，退回重写方案。
```

## 3. 项目脚手架 Prompt

**Goal**
初始化最小可运行项目结构，建立质量工具和基础 README。

**Context**
已经确认 Python + FastAPI 后端、React/Vite 前端、自研 workflow。

**Constraints**
- 先列出将创建/修改的文件。
- 只创建脚手架和最小健康检查，不实现完整业务。
- 不添加不必要依赖。
- 使用 `src/` layout。

**Done when**
- `pyproject.toml`、`src/text_to_sql_demo/main.py`、`tests/unit/test_app_health.py` 可运行。
- 前端 `frontend/package.json`、`vite.config.ts`、`src/App.tsx` 最小页面可 build。
- README 有本地启动和测试命令。

**Verification**
- `ruff check .`
- `python -m pytest tests/unit/test_app_health.py`
- `cd frontend && npm test`
- `cd frontend && npm run typecheck`
- `cd frontend && npm run build`

**Failure rule**
- 任一命令失败，停止新增功能，先修复脚手架。

**Prompt**

```text
请进入脚手架实现阶段。

Goal
建立最小可运行 Text-to-SQL demo 仓库骨架。

Context
技术方案已确认：FastAPI + Pydantic 后端，React/Vite/TypeScript 前端，自研 workflow 后续实现。

Constraints
- 编码前先列出文件计划：新增/修改文件、原因、是否影响 workflow/node/state/API。
- 只做脚手架，不实现完整 Text-to-SQL。
- 不添加 LangChain、LangGraph、数据库迁移框架或重型依赖。
- 公共函数/类必须有类型注解。
- 中文 docstring 简洁说明重要类和入口。

Tasks
1. 创建 Python package 和 FastAPI /health。
2. 配置 pyproject.toml：依赖、pytest、ruff。
3. 创建基础 pytest。
4. 创建 frontend 最小 Vite React TS 项目。
5. 创建 README：环境要求、启动命令、测试命令、项目边界。

Done when
- 后端健康检查测试通过。
- 前端最小 build 通过。
- README 能让新人本地启动。

Verification
运行：
- ruff check .
- python -m pytest tests/unit/test_app_health.py
- cd frontend && npm test
- cd frontend && npm run typecheck
- cd frontend && npm run build

Failure rule
如果任一验证失败，先修复失败，不要继续下一个阶段。
```

## 4. Workflow Core Prompt

**Goal**
实现可配置 workflow engine、节点接口、注册表、工厂和状态模型。

**Context**
脚手架已可运行，现在要建立项目架构地基。

**Constraints**
- WorkflowEngine 不得导入具体节点。
- NodeFactory 不得 if/elif 分发节点。
- 状态必须 Pydantic typed model。
- 每个节点执行产生 TraceEvent。
- 添加架构约束测试。

**Done when**
- 可用 minimal workflow 配置跑通 dummy nodes。
- 架构测试能防止 engine/factory 依赖具体节点。

**Verification**
- `ruff check .`
- `python -m pytest tests/unit/workflow`

**Failure rule**
- 如果架构测试失败，优先修正依赖方向，而不是放宽测试。

**Prompt**

```text
请实现 workflow core。

Goal
建立可配置、多节点、可 Trace 的轻量 WorkflowEngine。

Context
项目目标需要 Begin -> Selection -> Schema -> Retrieval -> SQLGeneration -> Validation -> Execution -> Reflection 等可配置节点。当前阶段只实现核心抽象和测试，不写具体业务节点。

Constraints
- 编码前输出计划，精确到文件、类、函数。
- WorkflowEngine 只依赖 WorkflowConfig、NodeFactory、WorkflowState、NodeResult。
- NodeFactory 只通过 NodeRegistry 解析类型。
- 不允许 engine/factory import `text_to_sql_demo.nodes`。
- 不允许在 NodeFactory 中对具体 node type 写 if/elif/match。
- TraceEvent 记录 node_name、node_type、status、outcome、duration_ms、input_summary、output_summary。

Tasks
1. 实现 WorkflowState、TraceEvent、WorkflowError。
2. 实现 BaseNode、NodeResult 生命周期钩子。
3. 实现 NodeRegistry 和 register_node decorator。
4. 实现 NodeFactory。
5. 实现 WorkflowEngine：max_steps、terminal、outcome edges、Trace。
6. 添加架构约束测试。

Done when
- dummy workflow 能按配置从 start_node 到 terminal。
- 缺失 node config 或未注册 node type 有清晰错误。
- 架构测试保护 engine/factory 不依赖具体节点。

Verification
- ruff check .
- python -m pytest tests/unit/workflow

Failure rule
测试失败时，不要绕过架构约束；先修正设计。
```

## 5. 核心功能开发 Prompt

**Goal**
按里程碑实现 Schema/RAG/Prompt/LLM/SQL 生成/校验/执行。

**Context**
Workflow core 已完成，需要逐步接入具体业务节点。

**Constraints**
- 每次只实现一个小里程碑。
- 每个里程碑先写/补测试，再实现。
- 不要为了方便把 prompt 写进 route。
- 不要让节点直接读取全局配置，必须通过 config/dependencies/state。

**Done when**
- 成功路径可通过 MockLLM 从自然语言生成 SQL 并执行。
- API 返回 SQL、结果、linked_schema、retrieved_examples、rag_context、trace。

**Verification**
- `ruff check .`
- `python -m pytest tests/unit/schema tests/unit/retrieval tests/unit/prompts tests/unit/llm tests/unit/sql tests/integration/test_api_workflow.py`

**Failure rule**
- 如果成功路径集成测试失败，不继续修复路径，先让 happy path 稳定。

**Prompt**

```text
请按小步实现 Text-to-SQL 核心功能。

Goal
让 /api/v1/query 在 MockLLM 下跑通成功路径：Schema Linking -> Context Retrieval -> Example Retrieval -> SQL Generation -> Validation -> Execution -> Finalization。

Context
Workflow core 已实现。现在需要真实节点、PromptBuilder、LLMClient、SQLValidator 和 SQLExecutor。

Constraints
- 编码前先输出本阶段计划，说明改哪些文件、类、函数，以及是否影响 workflow/node/state/API。
- 每次只做一个里程碑，不要混入 runtime config、metadata、frontend。
- Prompt 模板放在 configs/prompts，不写进 API route。
- LLM 使用 `LLMClient` 协议，测试使用 `MockLLMClient`。
- SQL 执行只能执行 SQLValidator 校验后的 SQL。
- 只注入 linked schema 和 Top-K 上下文，不要把完整 schema 全量塞进 prompt。

Milestones
1. Schema catalog + SchemaLinker。
2. ExampleStore + KnowledgeStore + BusinessPatternStore。
3. PromptBuilder + YAML template renderer。
4. LLMClient / MockLLMClient / OpenAI-compatible adapter。
5. GenSQLAgenticNode + complexity routing。
6. SQLValidator + SQLExecutionNode。
7. API service 串通 workflow。

Done when
- MockLLM 返回正确 SQL 时，/api/v1/query 返回 success。
- response 包含 final_sql、result、linked_schema、retrieved_examples、rag_context、trace。
- selected_model 和 routing_reason 可解释。

Verification
- ruff check .
- python -m pytest tests/unit/schema tests/unit/retrieval tests/unit/prompts
- python -m pytest tests/unit/llm tests/unit/routing tests/unit/sql tests/unit/execution
- python -m pytest tests/integration/test_api_workflow.py

Failure rule
任何验证失败时，停止后续里程碑，先修复失败并重跑对应命令。
```

## 6. 测试补齐 Prompt

**Goal**
系统性补齐单元测试、集成测试、边界场景、错误场景和 Mock fixture。

**Context**
核心功能已实现，但需要用测试约束 AI 生成代码质量。

**Constraints**
- 测试不得依赖真实 LLM API。
- 测试要覆盖成功路径、修复路径、终止路径。
- 不只测试“状态码 200”，要断言关键字段和 trace outcome。
- 失败测试不能通过放宽业务约束解决。

**Done when**
- 后端关键模块都有 unit tests。
- 集成测试覆盖三条 demo 场景。
- 架构约束测试存在。
- 前端 API client、adapter、主交互有 Vitest。

**Verification**
- `ruff check .`
- `python -m pytest`
- `cd frontend && npm test`
- `cd frontend && npm run typecheck`
- `cd frontend && npm run build`

**Failure rule**
- 如果测试暴露真实 bug，修代码；如果测试本身假设错误，说明原因再修测试。

**Prompt**

```text
请作为测试负责人补齐测试，不要新增功能。

Goal
用测试锁住 Text-to-SQL demo 的关键行为和架构边界。

Context
项目已有 workflow、nodes、LLM mock、SQL 校验执行和 API。现在要确保后续 AI 修改不会破坏核心链路。

Constraints
- 先列测试计划：模块、场景、fixture、断言。
- 不调用真实付费 LLM API。
- 不连接外部数据库服务；SQLite 使用 tmp_path 或 demo fixture。
- 测试要断言 trace、attempts、reflection_decision、repair_history、hitl_required。
- 架构测试必须检查 WorkflowEngine/NodeFactory 不导入具体节点、不按 node type 分支。

Required tests
1. Workflow core: success, missing node, max_steps, trace。
2. Registry/factory: duplicate registration, unknown type。
3. Schema/Retrieval/Prompt: Top-K、prompt summary、只注入裁剪上下文。
4. SQL: write SQL rejected, unknown table/column, ambiguous column, dialect parse。
5. LLM: Mock sequence/alias responses, provider error handling。
6. Integration: complex query success once, wrong column reflected and fixed, 3 failed repairs -> HITL。
7. API: error response, saved query draft/review, feedback, runtime config。
8. Frontend: query submit, runtime panel, debug panel, SQL edit execution, error display。

Done when
测试能证明成功路径、修复路径、终止路径和架构边界。

Verification
- ruff check .
- python -m pytest
- cd frontend && npm test
- cd frontend && npm run typecheck
- cd frontend && npm run build

Failure rule
失败后先分类：实现 bug / 测试假设错 / 环境问题。分类写清楚，再做最小修复。
```

## 7. 代码审查 Prompt

**Goal**
让 Codex 以 Staff Engineer 身份审查当前实现，优先找 bug、风险、缺失测试和生产化短板。

**Context**
核心功能已经跑通，但要展示“我审查 AI 输出，而不是完全放任”。

**Constraints**
- 先只审查，不改代码。
- Findings 按严重程度排序。
- 每条 findings 必须有文件/函数证据。
- 修复只做低风险高收益，不做大重构。

**Done when**
- 输出 P0/P1/P2 findings。
- 输出建议修复顺序。
- 明确哪些问题本阶段不修。

**Verification**
- 人工确认修复范围后，再执行局部修复和测试。

**Failure rule**
- 如果发现高风险安全问题，暂停新功能，先修安全边界。

**Prompt**

```text
请作为 Staff Engineer 对当前仓库做代码审查。

Goal
找出影响正确性、安全性、可维护性、测试可靠性和生产化边界的问题。

Context
这是 Text-to-SQL Agent demo。重点模块是 workflow、nodes、LLM、SQL validator/executor、runtime config、metadata、observability、frontend API/client。

Constraints
- 只做审查，不要改代码。
- Findings 必须按 P0/P1/P2 排序。
- 每个 finding 必须引用具体文件和函数/类。
- 不要泛泛建议“加强测试”，必须指出缺哪类测试。
- 不要建议引入重型平台能力，除非它直接解决当前风险。
- 区分 demo 可接受限制和必须修复的问题。

Review checklist
1. Workflow 是否有无限循环风险？
2. NodeFactory/WorkflowEngine 是否违反扩展边界？
3. SQLValidator 是否拒绝写入/DDL/多语句/未知表字段？
4. SQLExecutor 是否只执行已校验 SQL？
5. LLM provider 是否泄露 API key 或绑定具体模型？
6. Prompt 是否可能注入完整敏感上下文？
7. Runtime config 是否脱敏、过期、错误响应稳定？
8. 日志是否输出完整 SQL、prompt、数据库 URL 或密钥？
9. Metadata 是否和业务目标库隔离？
10. 前端是否有用户错误和技术错误分层？
11. 测试是否覆盖成功、修复、终止、架构约束？

Done when
输出 findings、修复优先级、低风险修复建议、暂不处理事项。

Verification
- 人工确认每条 finding 都有文件/函数证据。
- 确认建议修复没有扩大到无关重构。

Failure rule
如果发现 P0 安全或数据破坏风险，停止功能开发，先修复或记录明确阻断原因。
```

## 8. 生产化加固 Prompt

**Goal**
在不扩成重型平台的前提下，继续增强安全、配置、日志、部署和可维护性。

**Context**
项目是 demo，但需要体现接近生产级代码意识。

**Constraints**
- 不实现完整认证、多租户、BI 平台。
- 不引入分布式基础设施。
- 所有加固都必须有测试或文档验证。
- 不宣称性能指标。

**Done when**
- README 和运行手册明确安全边界。
- SQL 执行、日志、密钥、runtime config、metadata 有清晰限制。
- CI/Docker 可作为后续任务，不伪装已完成。

**Verification**
- `ruff check .`
- `python -m pytest`
- `python scripts/run_demo.py`
- `cd frontend && npm test`
- `cd frontend && npm run typecheck`
- `cd frontend && npm run build`

**Failure rule**
- 生产化加固失败时，不用“demo 可以忽略”掩盖；要明确是修复还是记录为限制。

**Prompt**

```text
请做一轮生产化加固设计与低风险实现。

Goal
在保持轻量 demo 边界的前提下，提高安全、可配置、可观测和可维护性。

Context
系统已有 workflow、SQL 校验执行、runtime config、metadata、frontend。现在要补齐最值得做的生产化 guardrails。

Constraints
- 先输出加固计划和风险分级，得到确认后再改。
- 不做认证、多租户、scheduler、BI dashboard、MCP、多 Agent 工作台。
- 不引入强依赖向量库或分布式组件。
- 不编造性能指标。
- 所有改动必须小步、可测试、可回滚。

Candidate hardening areas
1. 环境变量与密钥：SecretStr、脱敏响应、日志红线。
2. SQL 安全：只读账号建议、statement timeout 文档、max_rows、拒绝写入。
3. 错误处理：自定义异常、API 统一错误体、可定位日志。
4. 可观测性：request_id、node trace、sql hash、warning/error 分级。
5. Runtime config：TTL、过期错误、连接测试、内存存储限制说明。
6. Docs：README、运行手册、演示脚本、生产限制。
7. CI/Docker：如实现则保持最小；如不实现则列为后续。

Done when
- 加固项有清晰前后对比。
- 所有新增限制写进 README/docs。
- 测试覆盖安全和错误场景。

Verification
- ruff check .
- python -m pytest
- python scripts/run_demo.py
- cd frontend && npm test
- cd frontend && npm run typecheck
- cd frontend && npm run build

Failure rule
任何验证失败都先修复；如果属于外部环境问题，记录具体命令、错误和人工验证方式。
```

## 9. 面试复盘 Prompt

**Goal**
把项目整理成可信 STAR 故事，重点体现 Prompt 设计、AI 约束、测试验证和代码审查。

**Context**
代码已经完成，现在要准备面试表达。

**Constraints**
- 不伪造历史聊天记录。
- 不说“这些 Prompt 是当时逐字用过的”。
- 必须区分真实证据和复盘推断。
- 回答要能经得起追问：为什么这样拆、怎么限制 AI、怎么验证输出。

**Done when**
- 有 30 秒、2 分钟、深挖版本。
- 有面试官追问 Q&A。
- 有“诚实边界”表述。

**Verification**
- 人工朗读 2 分钟版本，能自然讲完。
- 每个技术亮点能对应到真实代码文件。

**Failure rule**
- 如果某句话无法用代码证据支撑，改成“复盘推断/后续方向/待确认”。

**Prompt**

```text
请把这个 Text-to-SQL Agent 项目整理成面试复盘材料。

Goal
展示我重度使用 Codex / Claude Code 等 AI 编程工具，并且具备 Prompt 编写、约束 AI、审查 AI 输出、验证代码和项目级交付能力。

Context
当前仓库真实实现包括：可配置 workflow、节点注册、Pydantic state、Schema/RAG Top-K、LLM provider abstraction、SQLGlot 校验、SQLAlchemy 执行、反思修复、最多 3 次终止、Trace、metadata、runtime config、React 前端、pytest/Vitest。

Constraints
- 不要伪造历史真实聊天记录。
- 不要说 Prompt 是当时逐字使用。
- 所有亮点尽量引用具体文件或模块。
- 必须体现我是如何控制 AI，而不是“让 AI 帮我写代码”。
- 必须提到 demo 边界：无认证、多租户、长期密钥托管、生产级权限隔离。

请输出：
1. 30 秒版本。
2. 2 分钟版本。
3. 深挖版本：架构、Prompt 策略、测试、审查、生产化意识。
4. 面试官可能追问的 10 个问题和回答。
5. 简历 bullet 版本。
6. 诚实边界：哪些只能说复盘整理，不能说历史原始 Prompt。

Done when
这份材料能直接用于面试准备，并且每个技术主张能回到仓库证据。

Verification
- 人工朗读 30 秒和 2 分钟版本，确认自然、可信、不夸大。
- 抽查每个技术亮点是否能指向具体文件或测试。

Failure rule
如果某个说法没有证据支撑，改成“复盘推断”“后续计划”或删除。
```
