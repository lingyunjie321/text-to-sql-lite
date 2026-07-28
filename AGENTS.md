## AGENTS.md 同步修改要求

本次 Demo 清退必须同步更新根目录 AGENTS.md，不能只修改 README、代码和文件名。

### 新的项目使命

将项目定位更新为：

“构建一个 API-first、可配置、可执行、可测试、可评测的轻量 Text-to-SQL Engine。”

本项目不再以面试展示、前端演示或功能数量为主要目标，优先保证：

* 核心调用链真实可运行；
* 数据库查询安全且可验证；
* 节点输入输出清晰；
* 错误能够分类、定位和有限修复；
* 实现能够通过测试和评测复现；
* 代码便于本人阅读、调试和持续维护。

### 实现事实规则

增加以下强制规则：

1. 当前仓库代码、测试和可复现实验是“已实现能力”的唯一证据。
2. 简历、知识库和面试材料只能作为历史设计参考和后续需求来源。
3. 不得依据资料描述直接声称仓库已经实现某项能力。
4. 不得为了对齐简历而补写虚假代码、测试、文档或指标。
5. README 中出现的指标必须有仓库内数据集、评测命令和实际输出支撑。
6. 尚未实现的内容必须标记为 backlog、proposal 或 future work。

### Workflow 规则调整

保留当前自研 WorkflowEngine 作为默认实现。

未经单独方案设计和用户明确确认：

* 不得将现有 WorkflowEngine 整体迁移到 LangGraph；
* 不得删除现有节点注册、节点工厂和配置边机制；
* 不得为了引入框架重写所有节点和 State。

未来允许在共享 Node Contract 和 State Contract 的基础上，增加可选 LangGraphWorkflowEngine，但必须作为独立任务设计和评估。

### Demo、Fixture 与正式代码边界

增加以下规则：

1. Mock LLM、样例数据库、示例配置和测试数据属于测试或开发 Fixture。
2. Fixture 应放在 tests、examples 或 devtools 中，不得混入核心业务逻辑。
3. 正式 API 运行时不得在数据库缺失时自动创建销售演示数据库。
4. Mock Provider 不得作为正式环境默认 Provider。
5. 核心 Schema Linking 不得硬编码 orders、customers、products 等示例业务对象。
6. 示例领域的表描述、字段描述和同义词应放入示例配置或测试 Fixture。
7. 删除前端 Demo 不代表删除 Mock、测试数据和成功/修复/终止路径测试。

### 当前产品范围

当前阶段重点建设：

* API；
* 可配置 Workflow；
* Typed State 的渐进迁移；
* Schema introspection 和 Schema Linking；
* SQL 生成、校验、只读执行；
* 错误分类、反思和有限修复；
* Trace、日志和 Metadata；
* PostgreSQL 开发环境；
* 可复现离线评测。

当前阶段不做：

* Web 前端；
* BI Dashboard；
* 完整 OAuth；
* 多租户管理平台；
* MCP 工作台；
* Scheduler；
* 分布式执行基础设施；
* 与核心 Text-to-SQL 无关的产品功能。

CLI 可以用于数据库初始化、配置检查和离线评测，但不得扩展为复杂 TUI 或管理平台。

### 渐进式修改规则

所有重构必须按小步骤推进。

禁止在同一任务中同时进行：

* Demo 清退；
* Workflow 框架迁移；
* 全量 State 重写；
* 混合检索接入；
* 数据库架构替换；
* API 大规模重构。

每个任务必须：

1. 有单一主要目标；
2. 明确修改文件、类和函数；
3. 保持对外接口稳定，除非任务明确要求修改；
4. 补充或更新测试；
5. 给出回滚风险；
6. 在执行前等待用户确认。


### 保留的现有工程规则

以下现有规则继续保留：

* Workflow 流转不能硬编码在 API Handler；
* 节点统一实现 BaseNode；
* 节点通过 NodeRegistry 和 NodeFactory 创建；
* 节点不得依赖 WorkflowEngine；
* 修复循环必须有最大次数和终止条件；
* LLM 访问隐藏在 Provider 无关接口后；
* 数据库凭据不得写入代码；
* 业务目标数据库默认只读；
* 测试不得依赖真实付费 LLM；
* 修改前必须先进入 Plan Mode；
* 未经用户明确确认不得修改代码；
* 每次任务必须报告文件、设计、命令、测试和剩余限制。
