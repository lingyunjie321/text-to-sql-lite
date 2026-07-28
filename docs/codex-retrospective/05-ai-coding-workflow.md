# AI 编程工作流方法论

> 本文是**基于当前代码仓库反向复盘整理的重构版 Prompt / Prompt Playbook**，不是历史真实聊天记录，也不声称为当时逐字使用过的 Prompt。

## 我的核心方法

我使用 AI 编程工具时，不把它当作“写代码按钮”，而是把它当作一个需要明确上下文、边界、验收标准和审查流程的协作工程师。

通用流程：

```mermaid
flowchart LR
    A[模糊需求] --> B[需求澄清 Prompt]
    B --> C[技术方案 Prompt]
    C --> D[小步实现 Prompt]
    D --> E[测试补齐 Prompt]
    E --> F[代码审查 Prompt]
    F --> G[生产化加固 Prompt]
    G --> H[文档与面试复盘]
```

## 高质量 Prompt 的结构

我会把复杂任务写成下面这种固定结构：

```text
Goal
本轮要达成什么具体结果。

Context
当前仓库状态、已有模块、业务背景、输入材料。

Constraints
必须遵守的架构、范围、安全、风格、测试约束。

Plan first
编码前必须先输出计划，列出文件、类/函数、影响面和风险。

Tasks
按小步列出任务，不允许一次性大改。

Done when
可验证的完成标准。

Verification
必须运行的 lint/typecheck/test/build 命令。

Failure rule
验证失败时停止新增功能，先定位并修复。

Report
完成后报告文件、决策、命令、测试结果、剩余限制。
```

## 为什么这样写

- **Goal** 防止 AI 不知道最终目标。
- **Context** 防止 AI 脱离代码库发明方案。
- **Constraints** 防止 AI 过度设计或破坏架构边界。
- **Done when** 把“写完”变成可验收状态。
- **Verification** 把“看起来可以”变成证据。
- **Failure rule** 防止 AI 在失败测试上继续堆功能。

## Prompt 质量自检 Rubric

每次把 Prompt 交给 Codex 前，我会用下面 10 条自检：

| 检查项 | 合格标准 |
| --- | --- |
| Goal | 一句话能说清本轮要交付什么 |
| Context | 包含当前仓库状态、相关文件、已有测试和业务背景 |
| Constraints | 写清架构边界、安全边界、范围边界和风格要求 |
| Plan first | 明确要求编码前先列文件、类/函数、影响面和风险 |
| Small steps | 本轮任务能被单独 review，避免跨多个模块大改 |
| Done when | 每个完成标准都能被观察或测试 |
| Verification | 写出必须运行的 lint/typecheck/test/build 命令 |
| Failure rule | 验证失败时停止新增功能，先定位并最小修复 |
| Review | 要求 AI 自查 diff，并说明哪些约束已被测试覆盖 |
| Evidence | 不能确认的历史过程、性能指标和生产能力必须标注推断或待确认 |

## 任务拆解方法

### 1. 先做需求边界

不直接写：

```text
帮我做一个 Text-to-SQL 项目。
```

改成：

```text
Goal
澄清 Text-to-SQL demo 的 MVP。

Context
目标用户是运营/分析师；项目要展示 AI 编程、Prompt 约束和工程化能力。

Constraints
- 先反问，不写代码。
- 区分 MVP / later / out of scope。
- 不引入认证、多租户、BI dashboard、scheduler。

Done when
输出用户场景、功能边界、不做事项、成功/修复/终止路径验收标准。
```

### 2. 再做架构方案

要求 AI 比较方案，而不是默认采用它熟悉的框架：

```text
请比较脚本式实现、自研轻量 workflow、LangGraph/LangChain 三种方案。
必须说明为什么当前 demo 选择或不选择每种方案。
```

### 3. 再做小步实现

每轮限制影响面：

```text
本轮只实现 Workflow Core：
- WorkflowState
- BaseNode / NodeResult
- NodeRegistry / NodeFactory
- WorkflowEngine
- workflow unit tests

不要实现业务节点、API、LLM、SQL。
```

这种 Prompt 能让 AI 保持上下文小、diff 小、测试清楚。

## 如何限制 AI 幻觉

1. **引用真实路径**：要求所有判断基于 `pyproject.toml`、`workflow.yaml`、`src/text_to_sql_demo/*`、`tests/*`。
2. **禁止编造历史**：复盘材料明确“基于当前仓库反向整理”，不是历史聊天记录。
3. **要求证据表**：每个技术亮点必须能指向文件、类、函数或测试。
4. **标注推断**：commit 顺序只能作为合理推断，不能当成真实开发过程。
5. **失败先停**：测试失败时不允许 AI 继续新增功能。
6. **Mock 外部依赖**：LLM 用 `MockLLMClient`，避免把网络和付费 API 当成测试前提。
7. **边界声明**：不把 demo 包装成生产 BI 平台。

## 如何让 AI 先计划再编码

我会在每个实现 Prompt 里加这段：

```text
Before coding
先输出简短计划：
1. 修改文件列表。
2. 修改类/函数。
3. 修改原因。
4. 是否影响 workflow / node / state / API / frontend。
5. 风险和回滚方式。

得到确认后再改代码。如果本轮我已经明确要求直接修改，也必须先在回复中简短说明计划，再开始改。
```

这能减少 AI 自作主张大改。

## 如何审查 AI 输出

我会用 Staff Engineer review Prompt：

```text
请只做代码审查，不要改代码。

Findings first:
- P0: 会导致安全问题、数据破坏或主链路不可用。
- P1: 会导致错误结果、测试缺口或维护风险。
- P2: 可读性、文档、边界改进。

每条 finding 必须包含：
- 文件和函数/类。
- 问题描述。
- 影响。
- 最小修复建议。
- 应补测试。
```

在这个项目里，重点审查：

- `WorkflowEngine` 是否会无限循环。
- `NodeFactory` 是否硬编码具体节点。
- `SQLValidator` 是否拒绝写入 SQL。
- `OpenAICompatibleLLMClient` 是否泄露 key/prompt。
- `RuntimeConfig` 是否脱敏和过期。
- `MetadataStore` 是否和业务库隔离。
- 前端是否把用户错误和技术错误分层。

## 如何跑测试和修复

我会把验证命令写进 Prompt，而不是事后想起来再跑：

后端基础验证：

```bash
ruff check .
python -m pytest
python scripts/run_demo.py
```

前端验证：

```bash
cd frontend
npm test
npm run typecheck
npm run build
```

失败处理 Prompt：

```text
Verification failed.

请不要继续新增功能。请按以下流程处理：
1. 复述失败命令和失败摘要。
2. 定位到具体文件、测试或断言。
3. 判断是实现 bug、测试假设错误还是环境问题。
4. 提出最小修复计划。
5. 修改后只先重跑失败命令。
6. 失败命令通过后，再重跑对应范围的完整验证。
7. 报告修复原因和剩余风险。
```

## 如何沉淀 AGENTS.md / README / Checklist

### AGENTS.md

用于写长期项目约束：

- 架构规则。
- 技术栈。
- 不做事项。
- 日志和异常约束。
- 测试要求。
- 开发流程：先计划，确认后修改。

### README

用于写使用者视角：

- 项目定位。
- 快速启动。
- API 示例。
- Demo 场景。
- 测试命令。
- 当前限制。

### Docs

用于写维护者视角：

- 架构。
- 工作流。
- API。
- runtime config。
- observability。
- 节点扩展。
- 数据库/方言扩展。

### Checklist

用于防止 AI 遗漏：

```text
完成前检查：
- 是否只改了本任务相关文件？
- 是否新增/修改了测试？
- 是否更新 README/docs？
- 是否运行 ruff/pytest？
- 前端变更是否运行 npm test/typecheck/build？
- 是否有敏感信息进入日志/响应？
- 是否把推断写成事实？
- 是否记录剩余限制？
```

## 可复用 Prompt 模板

```text
你是我的 AI 编程协作工程师。

Goal
[一句话写清本轮目标。]

Context
[当前仓库状态、相关文件、已有测试、业务背景。]

Constraints
- 先计划，再编码。
- 小步实现，避免无关重构。
- 遵守现有代码风格和架构边界。
- 不新增依赖，除非解释必要性并得到确认。
- 不伪造信息；无法从代码确认的内容标注“推断/待确认”。

Tasks
1. [任务 1]
2. [任务 2]
3. [任务 3]

Done when
- [验收标准 1]
- [验收标准 2]
- [验收标准 3]

Verification
- [lint 命令]
- [typecheck 命令]
- [test 命令]
- [build 命令]

Failure rule
如果任一验证失败，停止新增功能，先定位并修复失败。修复后重跑失败命令和对应完整验证。

Report
完成后报告：
1. 修改文件。
2. 主要设计决策。
3. 执行命令。
4. 测试结果。
5. 剩余限制或后续工作。
```

## 面试中怎么表达方法论

可以这样说：

> 我使用 AI 编程工具时，会先把需求变成结构化 Prompt：Goal、Context、Constraints、Done when、Verification 和 Failure rule。比如这个 Text-to-SQL 项目，我没有让 AI 直接生成 SQL 执行链路，而是先要求它设计 workflow、节点注册、状态模型、Prompt 裁剪、SQLGlot 校验、Mock LLM 测试和最多三次修复终止。每个阶段都有验证命令，失败后必须停止新增功能先修复。这体现的是我对 AI 输出的约束、审查和交付能力，而不是简单让 AI 代写代码。

## 不能夸大的地方

- 不能说这些 Prompt 是历史逐字使用记录。
- 不能说项目已经生产可用。
- 不能说 SQL 安全等同于数据库权限隔离。
- 不能说检索质量有量化指标。
- 不能说支持完整多租户、认证、BI 平台或长期密钥托管。

正确表述是：

> 这些文档是我基于当前仓库反向复盘整理的 Prompt Playbook，用来展示我如何把 AI 编程工具纳入项目级开发流程。它反映的是方法论和工程约束能力，而不是伪造历史聊天记录。
