# 生产级代码意识 Checklist

> 本文是**基于当前代码仓库反向复盘整理的重构版 Prompt / Prompt Playbook**，不是历史真实聊天记录，也不声称为当时逐字使用过的 Prompt。

## 已经比较工程化的地方

| 维度 | 当前证据 | 为什么体现工程化 |
| --- | --- | --- |
| 可配置工作流 | `workflow.yaml`、`WorkflowEngine`、`EdgeConfig.target_for()` | API handler 不硬编码流程，可通过配置调整节点边 |
| 节点扩展 | `BaseNode`、`NodeRegistry`、`NodeFactory` | 新增节点不需要改 engine/factory |
| 状态通信 | `WorkflowState`、`NodeResult.state_patch` | 节点通过显式状态传递，不靠全局变量 |
| 类型约束 | Pydantic models | 配置、请求、状态和响应可校验，便于测试 |
| LLM 抽象 | `LLMClient` Protocol、`MockLLMClient` | 测试不依赖真实付费 API |
| Prompt 管理 | `PromptBuilder`、`configs/prompts/*.yaml` | Prompt 不散落在 route handler |
| SQL 安全 | `SQLValidator` 使用 SQLGlot parse、只读 SELECT、schema 校验 | 不是直接执行 LLM 原始输出 |
| 修复闭环 | `ReflectionDecisionNode`、`FixSQLNode`、`HITLNode` | 错误可分类、修复有上限、失败可收敛 |
| 可观测性 | `TraceEvent`、`observability/events.py`、SQL hash | 能看每个节点状态，日志避免泄露完整 SQL |
| 内部数据沉淀 | `MetadataStore` | 运行记录、Trace、收藏 SQL、反馈和业务目标库分离 |
| 测试 | `tests/integration/test_demo_scenarios.py`、`test_architecture_constraints.py` | 覆盖成功、修复、终止和架构边界 |

## 离生产级还差什么

| 优先级 | 缺口 | 当前状态 | 建议加固 | Prompt 示例 |
| --- | --- | --- | --- | --- |
| P0 | 数据库权限隔离 | 应用层 SQLGlot 校验，README 已说明不等于生产权限隔离 | 使用只读数据库账号、statement timeout、查询超时、资源限制 | 见下方 Prompt A |
| P0 | 密钥托管 | Runtime config 使用 SecretStr，但没有长期密钥托管 | 生产使用 Secret Manager，不在服务内持久保存明文 | Prompt B |
| P1 | Runtime config 持久性 | `RuntimeConfigStore` 是内存字典 | 可选持久 store、过期清理、审计日志 | Prompt C |
| P1 | Provider 稳定性 | OpenAI-compatible adapter 基础可用 | 增加超时、重试、错误分类、预算控制 | Prompt D |
| P1 | CI/CD | 仓库未看到 GitHub Actions 配置 | 添加 lint/test/build pipeline | Prompt E |
| P1 | 部署 | 无 Dockerfile / compose | 增加最小 Dockerfile 或部署手册 | Prompt F |
| P1 | 检索质量 | YAML + 词法 Top-K | 增加离线评测集；可选 embedding/vector backend | Prompt G |
| P2 | Schema 来源 | 主链路以 introspection 为主 | 补 YAML schema loader 或数据团队维护配置 | Prompt H |
| P2 | 文档同步 | API 和 docs 可能随实现演进产生漂移 | 增加文档同步 checklist | Prompt J |

## Prompt A：SQL 执行安全加固

```text
Goal
加固 SQL 执行安全边界，但不把 demo 扩成完整权限平台。

Context
当前 SQL 安全依赖 SQLGlot 校验和只读 SELECT 检查。README 已说明这不等于生产级数据库权限隔离。

Constraints
- 编码前先输出计划，说明改哪些文件、函数、测试。
- 不允许放宽 SQLValidator。
- 不记录完整 SQL，日志仍只记录 length/hash。
- 不实现复杂权限系统。

Done when
- 文档明确生产建议：只读账号、statement timeout、max_rows、网络隔离。
- 代码层如新增超时/行数限制/错误分类，必须有测试。
- 写入 SQL、DDL、多语句仍被拒绝。

Verification
- ruff check .
- python -m pytest tests/unit/sql tests/unit/execution tests/integration/test_api_workflow.py

Failure rule
如果安全测试失败，停止所有其他改动，先修 SQL 安全边界。
```

## Prompt B：密钥与日志脱敏审查

```text
Goal
审查并加固 API key、Authorization、数据库密码、完整数据库 URL、完整 prompt、完整 SQL 的泄露风险。

Context
当前有 SecretStr、redact_keys、SQL hash 摘要、统一 API 错误响应。

Constraints
- 先审查，不改代码。
- 每个风险必须引用具体文件和字段。
- 不得把密钥写入配置文件、日志、响应或测试快照。

Done when
- 输出泄露路径清单：response、log、trace、metadata、runtime state。
- 给出 P0/P1/P2 修复建议。
- 只实现低风险修复。

Verification
- python -m pytest tests/unit/observability tests/integration/test_observability_api.py
- 手工 grep 确认测试 fixture 中没有真实 key。

Failure rule
发现 P0 泄露风险时，优先修复，不进入其他生产化任务。
```

## Prompt C：Runtime Config 持久化设计

```text
Goal
设计 runtime config 的可选持久化，不破坏当前内存 demo 模式。

Context
当前 `RuntimeConfigStore` 是内存存储，适合 demo，但服务重启后 `runtime_config_id` 失效。

Constraints
- 先只出设计，不写代码。
- 不能持久化明文 API key 或数据库密码。
- 保留内存 store 作为默认。
- 不实现多租户和完整权限系统。

Done when
- 输出接口抽象、存储模型、过期清理、脱敏策略、迁移步骤。
- 明确哪些内容不落库。
- 给出测试计划。

Verification
- 人工评审设计；确认后再实现。

Failure rule
如果设计需要保存明文密钥、引入多租户平台或破坏当前 demo 默认模式，停止实现并重新收敛范围。
```

## Prompt D：LLM Provider 稳定性

```text
Goal
增强 LLM provider 调用的错误分类、超时和可测试性。

Context
当前有 `LLMClient`、`MockLLMClient` 和 `OpenAICompatibleLLMClient`。

Constraints
- 编码前先输出文件计划和测试计划。
- 不改变业务节点对 `LLMClient` 的依赖方式。
- 不在业务代码中硬编码模型名称。
- 所有 provider 失败都不能泄露 key 或完整 prompt。

Done when
- provider 错误映射为稳定自定义异常。
- 日志包含 provider、model_alias、duration_ms，不含完整 prompt/key。
- Mock 测试覆盖超时/错误响应。

Verification
- ruff check .
- python -m pytest tests/unit/llm tests/unit/observability

Failure rule
如果 provider 测试失败，先修错误分类和脱敏边界；不要通过放宽断言绕过。
```

## Prompt E：CI Pipeline

```text
Goal
添加最小 CI，确保 PR 中自动运行后端验证。

Context
当前 README 已列出本地命令，但仓库未看到 CI 配置。

Constraints
- 编码前先输出 CI 文件计划和本地等价验证命令。
- 不引入复杂发布流程。
- CI 只做 lint/test/build。
- 缓存可以简单，不做过度优化。

Done when
CI 执行：
- ruff check .
- python -m pytest
- python scripts/run_demo.py

Verification
- 本地至少运行同等命令。
- CI YAML 语法可读、步骤清晰。

Failure rule
如果本地等价命令失败，不提交 CI；先修复失败或标注为现有阻断。
```

## Prompt F：最小部署手册

```text
Goal
补充本地和轻量部署运行手册，不宣称生产 SLA。

Context
项目用于 demo 和面试，当前没有 Dockerfile。

Constraints
- 写文档前先扫描 README、pyproject.toml 和运行脚本。
- 先写部署文档，再决定是否加 Dockerfile。
- 明确环境变量、数据目录、日志目录、密钥配置。
- 不编造性能指标。

Done when
- 文档包含 API 启动、环境变量、SQLite Fixture 初始化、日志路径和限制。
- 明确生产中必须替换只读账号和密钥管理。

Verification
- ruff check .
- python -m pytest
- python scripts/run_demo.py
- 人工检查文档命令与实际配置一致。

Failure rule
如果命令无法在本地验证，文档必须标注“待确认”，不能写成已验证。
```

## Prompt G：RAG 质量评估

```text
Goal
为 Schema Linking、Example Retrieval 和 Knowledge Retrieval 增加离线评估思路。

Context
当前是词法 Top-K fallback，没有 embedding/vector backend。

Constraints
- 先输出评估设计，不直接改检索实现。
- 不直接引入向量数据库。
- 先设计评估集和指标。
- 不编造召回率或准确率。

Done when
- 定义 eval fixture：问题、期望表、期望字段、期望 reference SQL。
- 定义可运行 eval 脚本或 pytest 参数化测试。
- 输出当前限制和后续向量化方案。

Verification
- python -m pytest tests/unit/retrieval
- 如新增 eval：python -m pytest tests/evals

Failure rule
如果评估结果不好，只报告当前结果和原因，不编造指标；优化作为后续任务。
```

## Prompt H：Schema YAML Loader

```text
Goal
实现或设计 YAML schema catalog fallback。

Context
`SchemaConfig.catalog_source` 支持 `database` / `yaml`，但当前主链路以 database introspection 为主。

Constraints
- 编码前先审查当前 schema 读取链路，确认是否已有 loader。
- 先确认当前主链路是否已有 loader，不能重复实现。
- YAML schema model 必须复用 `DatabaseSchemaMetadata`。
- 必须有测试覆盖字段、主键、外键、描述。

Done when
- `catalog_source=yaml` 能进入 `read_schema` 等价流程，或文档明确待实现。
- tests/unit/schema 覆盖。

Verification
- ruff check .
- python -m pytest tests/unit/schema tests/integration/test_api_workflow.py

Failure rule
如果发现已有 loader，不重复造轮子；只补测试或文档说明。
```

## Prompt J：文档同步 Checklist

```text
Goal
建立文档同步检查，避免 README/docs 与代码结构漂移。

Context
当前 API、配置和文档可能随实现演进产生漂移。

Constraints
- 修改前先用 `rg --files` 和 `rg` 列出需要同步的文档引用。
- 不改业务代码。
- 文档必须基于当前 `rg --files` 和真实路径。
- 无法确认的历史过程标注为推断。

Done when
- README 文档导航、项目结构文档、运行命令与当前代码一致。
- 新增文档维护 checklist：改入口、顶层目录、启动命令时必须同步哪些文档。

Verification
- rg 检查旧组件名是否还被文档引用。
- 人工点击 README 文档链接。

Failure rule
如果无法确认某个路径或命令是否仍有效，标注“待确认”，不要替读者做假设。
```

## 面试表达建议

可以这样讲：

> 我没有把 AI 当作“自动写代码按钮”，而是把它放进一套工程化约束里。比如 Text-to-SQL 这种场景，最危险的是直接执行 LLM SQL，所以我的 Prompt 要求先设计 workflow、状态模型、节点注册、Prompt 裁剪和 SQLGlot 校验，再通过 Mock LLM 做成功、修复、终止路径测试。后续我又用 Staff Engineer review Prompt 让 AI 自查安全、日志、密钥和架构边界。这套方法比单轮“帮我写项目”更接近真实团队开发流程。
