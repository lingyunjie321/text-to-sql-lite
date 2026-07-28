# 面试复盘话术

> 本文是**基于当前代码仓库反向复盘整理的重构版 Prompt / Prompt Playbook**，不是历史真实聊天记录，也不声称为当时逐字使用过的 Prompt。

## 30 秒版本

我做过一个轻量级 Text-to-SQL Agent，重点不是让 LLM 直接拼 SQL，而是用 Codex/Claude Code 这类 AI 编程工具，把模糊需求拆成项目级工程流程：需求澄清、架构设计、自研 workflow、节点注册、Prompt 裁剪、SQLGlot 校验、最多 3 次反思修复、Trace 和 Mock LLM 测试。这个项目能说明我如何约束 AI 输出，而不是完全放任 AI 写代码。需要诚实说明的是：现在整理的 Prompt Playbook 是基于当前仓库反向复盘的重构版，不是当时逐字历史 Prompt。

## 2 分钟版本

这个项目的背景是：运营或分析师希望用自然语言查业务数据，但 Text-to-SQL 最大风险是 LLM 生成错误或危险 SQL。所以我把目标拆成一个 API-first 的轻量 Engine：数据团队维护 Schema、Reference SQL、文档知识、Metric 和 Semantic Model，调用方通过 API 获取 SQL、结果、Trace 和修复历史。

我用 AI 编程工具时，不是直接说“帮我写一个 Text-to-SQL”。我会先给 Codex 明确 Goal、Context、Constraints 和 Done when。例如 workflow engine 不能导入具体节点，NodeFactory 不能 if/elif 分发节点，LLM 必须 provider-neutral，测试必须用 Mock LLM，SQL 修复最多 3 次，失败进入 HITL。这样 AI 生成的代码会被架构边界限制住。

从代码上看，`WorkflowEngine`、`BaseNode`、`NodeRegistry`、`NodeFactory` 构成可配置工作流；`PromptBuilder` 只注入 linked schema、Top-K examples 和 RAG context；`LLMClient` 隐藏具体 provider；`SQLValidator` 用 SQLGlot 做只读 SELECT 和 schema 校验；`ReflectionDecisionNode` 把错误路由到修复、重新链接 Schema、重新推理或人工介入。测试里用 Mock LLM 覆盖复杂查询成功、错误字段自动修复和三次失败终止。

面试里我会强调：这不是完整生产 BI 平台，还没有认证、多租户、长期密钥托管和生产级数据库权限隔离。但它体现了我如何用 Prompt 把 AI 约束在可审查、可测试、可交付的项目流程里。

## 深挖版本

### Situation

我需要做一个能展示 AI 编程能力的 Text-to-SQL Agent demo。问题不是简单调用 LLM，而是如何让 AI 生成的 SQL 在工程上可控、可测试、可解释。

### Task

我要让项目体现：

- 可配置多阶段 workflow。
- 节点注册表、工厂和生命周期。
- 基于状态的节点通信。
- Schema / Example / Knowledge / Metric / Semantic Model Top-K 检索。
- SQL 生成、校验、执行、反思和修复。
- 最多 3 次修复和明确终止条件。
- Provider-neutral LLM 和 Mock 测试。
- Trace、日志脱敏、运行记录和稳定 API 契约。

### Action

我把 Prompt 分成多轮，而不是一次性大命令：

1. 需求澄清 Prompt：让 AI 先反问，明确 MVP 和不做事项。
2. 技术方案 Prompt：要求 AI 比较脚本式、自研 workflow、LangGraph/LangChain，并说明为什么当前 demo 选择自研 workflow。
3. 脚手架 Prompt：先建立 FastAPI、pytest 和 ruff。
4. Workflow Prompt：实现 `WorkflowEngine`、`BaseNode`、`NodeRegistry`、`NodeFactory`，并添加架构约束测试。
5. 核心链路 Prompt：小步实现 Schema Linking、RAG、PromptBuilder、LLM abstraction、SQL validation/execution。
6. 修复闭环 Prompt：错误分类、定向修复、SQLContext 记忆和 HITL。
7. 测试 Prompt：覆盖成功路径、修复路径、终止路径，不依赖真实 LLM API。
8. 代码审查 Prompt：让 Codex 以 Staff Engineer 身份找安全、可维护性和测试缺口。
9. 生产化加固 Prompt：明确 demo 边界和后续加固项。

每轮 Prompt 都有 Goal / Context / Constraints / Done when / Verification / Failure rule。比如我会明确要求：如果 `ruff check .` 或 `python -m pytest` 失败，必须停止新增功能，先修复失败。

### AI 审查闭环

我不会把 AI 输出当成最终答案，而是按下面的闭环处理：

| 环节 | 我如何约束 AI | 例子 |
| --- | --- | --- |
| 计划 | 编码前先列修改文件、类/函数、影响面和风险 | workflow core 阶段先确认只改 `workflow/*` 和测试 |
| 小步实现 | 每轮只做一个里程碑，不混入无关功能 | 先完成 workflow，再接 Schema/RAG，再接 SQL 修复 |
| Diff 自查 | 要求 AI 说明哪些约束被满足，哪些风险仍存在 | `NodeFactory` 不写 if/elif，`WorkflowEngine` 不导入具体节点 |
| 验证 | 把 lint/test 写进 Prompt | `ruff check .`、`python -m pytest`、`python scripts/run_demo.py` |
| 失败处理 | 验证失败时停止新增功能，先定位再最小修复 | 修复 SQL 失败路径前，先让成功路径集成测试稳定 |
| 复盘 | 输出真实证据、合理推断和待确认项 | Prompt Playbook 明确不是历史逐字记录 |

### Result

当前仓库形成了一个完整 demo：

- 后端可通过 `/api/v1/query` 执行 Text-to-SQL workflow。
- workflow 可配置，节点按 outcome 路由。
- LLM provider 被隐藏在接口后，测试可用 Mock。
- SQL 不直接执行 LLM 原始输出，而是先经过 SQLGlot 校验。
- 修复循环最多 3 次，失败进入 HITL。
- API 支持运行配置、只读 SQL 执行、运行记录、反馈和 Debug Trace。
- 测试覆盖复杂查询成功、错误字段修复和终止路径。

## 最能体现 AI 编程能力的 5 个点

1. **Prompt 结构化能力**：每轮都写清 Goal / Context / Constraints / Done when，而不是一句“帮我写”。
2. **架构约束能力**：要求 AI 保持 engine/factory 与业务节点解耦，并用架构测试防回归。
3. **安全约束能力**：Prompt 要求 SQLGlot 校验、只读 SELECT、schema 引用检查和日志脱敏。
4. **验证驱动能力**：用 Mock LLM 和集成测试证明成功、修复、终止三条路径。
5. **审查 AI 输出能力**：让 AI 以 Staff Engineer 审查安全、错误处理、测试缺口和生产边界，只做低风险高收益修复。

## 面试官追问与回答

### Q1：你是不是只是让 AI 帮你写了代码？

不是。我主要做的是把 AI 放进工程约束里。比如我要求它先给计划，明确修改文件和影响面；实现时要小步提交；每轮都有 Done when 和验证命令；失败后不能继续写新功能，必须先修复。这和单纯让 AI 生成代码不一样，更像用 AI 执行一个受控开发流程。

### Q2：为什么不用 LangChain 或 LangGraph？

这个 demo 的目标是展示工作流引擎、状态传递、节点注册和可配置路由，所以我刻意选择自研轻量 workflow。这样能更清楚地展示节点接口、工厂、注册表和终止条件。LangGraph/LangChain 可以用于更复杂生产场景，但当前项目会掩盖我要展示的工程能力。

### Q3：如何防止 LLM 生成危险 SQL？

我没有直接执行 LLM 输出。生成后先经过 `SQLValidator`：SQLGlot parse、只读 SELECT、拒绝写入/DDL、schema 表字段校验；执行节点还要求执行方言和已校验 SQL 方言一致。生产上还需要数据库只读账号和资源隔离，我会诚实说明当前 demo 不等于完整权限隔离。

### Q4：AI 写错代码怎么办？

我用测试和审查约束它。比如 Mock LLM 覆盖成功、修复和终止路径；架构测试检查 engine/factory 不导入具体节点；日志测试检查敏感信息脱敏。出现失败时，Prompt 明确要求停止新增功能，先看失败输出，做最小修复，再重跑验证。

### Q5：你怎么设计 Prompt？

我习惯用固定结构：Goal、Context、Constraints、Done when、Verification、Failure rule。这样 AI 不会只追求“生成代码”，而会知道成功标准、禁止事项和验证方式。复杂任务再拆成需求、技术方案、脚手架、核心功能、测试、审查、加固、文档几个阶段。

### Q6：项目哪里体现生产级意识？

几个地方：provider-neutral LLM；测试用 Mock；Prompt 不写在 route；SQL 执行前校验；修复循环有上限；日志不输出完整 SQL/prompt/key；运行记录和业务库分离；README 明确 demo 边界和生产化短板。

### Q7：当前项目离生产还差什么？

主要是认证、多租户、长期密钥托管、生产级数据库权限隔离、CI/CD、Docker/部署、向量检索和评估体系、provider 重试/熔断/预算控制。这些我不会包装成已完成，而会作为后续加固路线。

### Q8：为什么选择 API-first？

API-first 让核心能力可以由 curl、Python 服务或其他调用方复用，也让请求、响应、错误和 Trace 契约能够被集成测试直接验证。

### Q9：怎么证明不是硬编码 demo？

workflow 在 `workflow.yaml` 配置；节点通过 registry/factory 创建；LLM 模型通过 alias 配置；数据库可通过 runtime config 选择；测试用 MockLLM sequence 覆盖不同路径。虽然 demo 数据集是固定的，但架构不是单条 if/else 脚本。

### Q10：这些 Prompt 是你当时原文吗？

不是。我会明确说：这些是基于当前仓库反向复盘整理的重构版 Prompt Playbook。它们不是历史真实聊天记录，但能反映我如何把项目拆成 AI 可执行、可审查、可验证的开发流程。

## 简历 Bullet 示例

- 使用 Codex/Claude Code 辅助构建 Text-to-SQL Agent demo，将模糊需求拆解为需求澄清、架构设计、workflow core、RAG、SQL 校验、修复闭环、测试和文档交付。
- 设计自研轻量 workflow：`BaseNode` / `NodeRegistry` / `NodeFactory` / `WorkflowEngine`，通过配置驱动节点流转，避免 API handler 硬编码流程。
- 通过 Prompt 约束 AI 输出：只注入 linked schema 和 Top-K 上下文，LLM provider-neutral，Mock LLM 覆盖成功、修复和终止路径。
- 引入 SQLGlot 校验、只读 SELECT 限制、schema 引用检查、最多 3 次修复和 HITL 终止，提升 Text-to-SQL 安全性和可解释性。
- 建立可观测 Trace、结构化日志、metadata store、稳定 API 契约和 pytest 测试体系。

## 诚实边界

| 可以说 | 不能说 |
| --- | --- |
| “我基于当前仓库反向整理了 Prompt Playbook。” | “这些就是我当时逐字使用的 Prompt。” |
| “项目体现了我如何约束 AI 写代码。” | “AI 自动完成了生产级系统。” |
| “当前 demo 有 SQL 校验和只读约束。” | “已经具备完整生产数据库权限隔离。” |
| “测试覆盖成功、修复、终止路径。” | “所有真实业务场景都已验证。” |
| “OpenAI-compatible adapter 和 Mock LLM 可替换。” | “已经支持所有 LLM provider。” |
| “Runtime config 是短生命周期内存配置。” | “已经具备生产密钥托管。” |
