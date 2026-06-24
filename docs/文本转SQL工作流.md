# Text-to-SQL 工作流

本文档描述 `workflow.yaml` 与当前节点实现的真实流转。工作流由 `WorkflowEngine.run` 执行，节点顺序不写在 API handler 中，而是由配置中的 `edges` 根据 `NodeResult.outcome` 决定。

## 当前配置入口

默认配置文件是仓库根目录的 `workflow.yaml`：

- `workflow.start_node`: `begin`
- `workflow.max_steps`: `30`
- `workflow.max_repair_attempts`: `3`
- `database.default`: `demo_sqlite`
- `models.aliases`: `light`、`strong`，当前默认 provider 为 `openai_compatible`
- `schema.catalog_source`: `database`
- `retrieval.examples_path`: 默认 `configs/examples.yaml`，请求级配置构建时会注入到 `example_retrieval` 节点
- `retrieval.knowledge_path`: 默认 `configs/knowledge.yaml`，请求级配置构建时会注入到 `context_retrieval` 节点

维护提示：如果修改 `workflow.yaml` 的节点名、outcome 边或最大尝试次数，必须同步更新本文档、[面试演示场景](面试演示场景.md) 和相关集成测试。

## 节点与职责

| 配置节点 | 实现类 | 主要输入 | 主要输出 | 成功/失败 outcome |
| --- | --- | --- | --- | --- |
| `begin` | `BeginNode` | `user_question`、`request_id` | `task` | `success` |
| `selection` | `SelectionNode` | `user_question` | `intent` | `text_to_sql` |
| `schema_linking` | `SchemaLinkingNode` | `user_question`、`state.data.schema` | `schema_linking` | `success` |
| `context_retrieval` | `ContextRetrievalNode` | 问题、linked tables、`configs/knowledge.yaml` | `rag_context` | `success` |
| `example_retrieval` | `ExampleRetrievalNode` | 问题、linked tables、`configs/examples.yaml` | `retrieved_examples`、`available_example_count` | `success` |
| `sql_generation` | `GenSQLAgenticNode` | 问题、linked schema、RAG 上下文、examples、业务方言范式、LLM client、model profiles | `generated_sql`、`selected_model`、`prompt_summary` | `success` |
| `sql_validation` | `ValidateSQLNode` | `generated_sql/current_sql`、schema、dialect | `validated_sql` 或 `last_error` | `validation_success`、`validation_failed` |
| `sql_execution` | `ExecuteSQLNode` | `validated_sql`、database URL | `execution_result` 或 `last_error` | `execution_success`、`execution_failed` |
| `error_classification` | `ReflectionDecisionNode`（兼容 `ReflectErrorNode`） | `last_error`、`current_sql/generated_sql`、`attempt_count`、`max_repair_attempts` | `reflection_decision`、`sql_contexts`、`last_reflection_strategy`、兼容的 `repair_instruction` | `fix_sql`、`relink_schema`、`retrieve_context`、`reasoning_rewrite`、`hitl_required`、`attempts_exhausted` |
| `reflection_fix` | `FixSQLNode` | `repair_instruction`、`reflection_decision`、`sql_contexts`、LLM client、model profile | 新 SQL、`repair_history`、`attempt_count`，历史中记录 `strategy_name` | `fix_complete` |
| `reasoning_rewrite` | `ReasoningRewriteNode` | 问题、linked schema、RAG 上下文、最近 SQLContext、`last_error`、反思原因 | 新 `generated_sql/current_sql`、`attempt_count` | `rewrite_complete` |
| `hitl` | `HITLNode` | `reflection_decision`、`last_error` | `final_status=needs_human_review`、`hitl_reason`、`final_error` | `hitl_required` |
| `finalization` | `FinalizeNode` | `execution_result`、错误状态、HITL 状态 | `final_status`、`final_sql`、`final_result/final_error` | `finalize_success`、`finalize_failed`、`finalize_hitl` |

维护提示：如果新增节点或给现有节点增加新的 outcome，需要同步更新 `workflow.yaml`、本表、plaintext/Mermaid 图和 `tests/unit/workflow/test_engine.py`。

## 流转图

先看 boxed plaintext 版，适合不渲染 Mermaid 的阅读场景：

```text
┌──────────────────────────────────────────────────────────────────────────────┐
│                       Text-to-SQL 工作流流转图                               │
└──────────────────────────────────────────────────────────────────────────────┘

                             ┌──────────────────────┐
                             │ POST /api/v1/query   │
                             │ QueryRequest         │
                             └───────────┬──────────┘
                                         │
                             ┌───────────▼──────────┐
                             │ begin                │
                             │ BeginNode            │
                             └───────────┬──────────┘
                                         │ success
                             ┌───────────▼──────────┐
                             │ selection            │
                             │ SelectionNode        │
                             └───────────┬──────────┘
                                         │ text_to_sql
                             ┌───────────▼──────────┐
                             │ schema_linking       │
                             │ SchemaLinkingNode    │
                             └───────────┬──────────┘
                                         │ success
                             ┌───────────▼──────────┐
                             │ context_retrieval    │
                             │ ContextRetrievalNode │
                             └───────────┬──────────┘
                                         │ success
                             ┌───────────▼──────────┐
                             │ example_retrieval    │
                             │ ExampleRetrievalNode │
                             └───────────┬──────────┘
                                         │ success
                             ┌───────────▼──────────┐
                             │ sql_generation       │
                             │ GenSQLAgenticNode    │
                             └───────────┬──────────┘
                                         │ success
                             ┌───────────▼──────────┐
                             │ sql_validation       │
                             │ ValidateSQLNode      │
                             └──────┬─────────┬─────┘
                                    │         │
                  validation_success│         │validation_failed
                                    │         ▼
                                    │  ┌──────────────────────┐
                                    │  │ error_classification │
                                    │  │ ReflectionDecision   │
                                    │  └──────┬─────────┬─────┘
                                    │         │         │
                                    │fix_sql  │attempts_exhausted / hitl_required
                                    │         │         ▼
                                    │         │  ┌──────────────────────┐
                                    │         │  │ hitl                 │
                                    │         │  │ HITLNode            │
                                    │         │  └───────────┬──────────┘
                                    │         │              │ hitl_required
                                    │         ▼              ▼
                                    │  ┌──────────────────────┐
                                    │  │ reflection_fix       │
                                    │  │ FixSQLNode           │
                                    │  └───────────┬──────────┘
                                    │              │ fix_complete
                                    │              └──── back to sql_validation
                                    │
                                    │  relink_schema -> schema_linking
                                    │  retrieve_context -> context_retrieval
                                    │  reasoning_rewrite -> reasoning_rewrite -> sql_validation
                                    │
                                    ▼
                             ┌──────────────────────┐
                             │ sql_execution        │
                             │ ExecuteSQLNode       │
                             └──────┬─────────┬─────┘
                                    │         │
                  execution_success │         │ execution_failed
                                    │         └──── to error_classification
                                    ▼
                             ┌──────────────────────┐
                             │ finalization         │
                             │ FinalizeNode success │
                             └───────────┬──────────┘
                                         │ terminal
                                         ▼
                                  ┌────────────┐
                                  │ API Result │
                                  │ + Trace    │
                                  └────────────┘
```

Mermaid 渲染版如下：

```mermaid
flowchart TD
    Start["POST /api/v1/query\nTextToSQLApiService.run_query"] --> Begin["begin\nBeginNode"]
    Begin -- success --> Selection["selection\nSelectionNode"]
    Selection -- text_to_sql --> Schema["schema_linking\nSchemaLinkingNode"]
    Schema -- success --> Context["context_retrieval\nContextRetrievalNode"]
    Context -- success --> Examples["example_retrieval\nExampleRetrievalNode"]
    Context -- failure --> Examples
    Examples -- success --> Generate["sql_generation\nGenSQLAgenticNode"]
    Generate -- success --> Validate["sql_validation\nValidateSQLNode"]

    Validate -- validation_success --> Execute["sql_execution\nExecuteSQLNode"]
    Execute -- execution_success --> FinalOK["finalization\nFinalizeNode: success"]

    Validate -- validation_failed --> Reflect["error_classification\nReflectionDecisionNode"]
    Execute -- execution_failed --> Reflect
    Reflect -- fix_sql --> Fix["reflection_fix\nFixSQLNode"]
    Fix -- fix_complete --> Validate

    Reflect -- relink_schema --> Schema
    Reflect -- retrieve_context --> Context
    Reflect -- reasoning_rewrite --> Rewrite["reasoning_rewrite\nReasoningRewriteNode"]
    Rewrite -- rewrite_complete --> Validate
    Reflect -- hitl_required --> HITL["hitl\nHITLNode"]
    Reflect -- attempts_exhausted --> HITL
    HITL -- hitl_required --> FinalReview["finalization\nFinalizeNode: needs_human_review"]
    FinalOK --> End["terminal"]
    FinalReview --> End
```

维护提示：这两个图必须只表达真实配置和真实节点。若改动 `edges` 中的 `on_validation_success`、`on_execution_failed` 等键名，plaintext 版、Mermaid 版和下方路径说明要一起改。

## 成功路径

一次成功路径为：

1. `TextToSQLApiService.run_query` 初始化数据库、读取 schema，创建 `WorkflowState`。
2. `WorkflowEngine.run` 从 `begin` 开始执行。
3. `BeginNode.run` 初始化任务上下文，把问题和 request_id 写入 `task`。
4. `SelectionNode.run` 做意图分类，当前默认输出 `text_to_sql`，后续可以扩展其他意图分支。
5. `SchemaLinkingNode.run` 使用 `SchemaLinker` 选出相关表列。
6. `ContextRetrievalNode.run` 使用 `KnowledgeStore` 返回 Reference SQL、文档片段、Metric、Semantic Model 的 Top-K `rag_context`。
7. `ExampleRetrievalNode.run` 使用 `ExampleStore` 返回 Top-K 本地 SQL 示例。
8. `GenSQLAgenticNode.run` 完成复杂度分类、模型 alias 路由、RAG 上下文/业务方言范式检索、prompt 构建和 LLM 调用；默认服务按 `workflow.yaml` 构造 OpenAI-compatible client，测试和 demo 脚本可注入 Mock。
9. `ValidateSQLNode.run` 用 SQLGlot 校验语法、方言、只读 SELECT 和 schema 引用。
10. `ExecuteSQLNode.run` 用 SQLAlchemy 执行已校验 SQL，执行方言必须受支持并与校验方言一致。
11. `FinalizeNode.run` 收敛 `final_status=success`、`final_sql` 和 `final_result`。

成功路径集成测试见 `tests/integration/test_api_workflow.py` 和 `tests/integration/test_demo_scenarios.py`。

维护提示：如果修改 `TextToSQLApiService.run_query` 的初始化数据、`GenSQLAgenticNode.run` 的内部步骤或 `serialize_run` 的响应字段，需要同步更新本节和 [SQL 生成过程代码追踪](SQL生成过程代码追踪.md)。

## 策略反思闭环

策略反思闭环覆盖 SQL 校验失败和执行失败：

1. `ValidateSQLNode.run` 或 `ExecuteSQLNode.run` 返回失败 outcome，并把结构化 `SQLError` 写入 `state.data.last_error`。
2. `ReflectionDecisionNode.run` 读取 `last_error`、`current_sql/generated_sql` 和尝试次数，写入 `reflection_decision`，并把本轮 SQL 尝试追加到 `sql_contexts`。
3. 策略路由由 `workflow.yaml` 决定：`FIX_SQL -> reflection_fix`，`RELINK_SCHEMA -> schema_linking`，`RETRIEVE_CONTEXT -> context_retrieval`，`REASONING_REWRITE -> reasoning_rewrite`，`HITL/STOP -> hitl`。
4. `FixSQLNode` 和 `ReasoningRewriteNode` 都会把最近 3 轮 SQLContext 摘要放进 prompt；摘要只包含 SQL hash/长度、错误类型、策略和原因。
5. `FixSQLNode` 或 `ReasoningRewriteNode` 产出新 SQL 后回到 `sql_validation`，成功后继续执行并 finalization。

当前实现保留向后兼容注册名：`error_reflection`、`error_classification` 和 `reflection_decision` 都指向策略反思节点。它不会在运行中动态插入节点，只通过 `NodeResult.outcome` 和配置边路由。

维护提示：如果将来增加新策略，必须更新 `ReflectionStrategy`、`workflow.yaml` 的 `edges`、本节、集成测试和 README 的核心能力说明。

## 终止路径

终止路径有两类：

- 修复次数耗尽：`ReflectionDecisionNode.run` 发现 `attempt_count >= max_repair_attempts`，返回 `attempts_exhausted`，进入 `HITLNode` 后再到 `finalization`，最终 `final_status=needs_human_review`、`termination_reason=attempts_exhausted`。
- 最大步骤保护：`WorkflowEngine.run` 发现 `step_count >= workflow.max_steps`，直接 `terminate("max_steps_exceeded")`。这是配置死循环保护。

当前 SQL 写入、DDL、多语句等会在 `SQLValidator` 中被拒绝为 `dialect_error`，并按配置进入修复流程；是否把安全错误改成不可修复，需要后续扩展 error category 和 edge 策略。

维护提示：如果调整 `max_attempts` 请求上限、`WorkflowSection.max_repair_attempts` 默认值或不可修复错误策略，应同步更新终止路径说明和终止路径测试。

## Trace 输出

每个节点执行后都会追加一条 `TraceEvent`。API 响应中的 trace 字段来自 `serialize_run`：

- `node_name` / `node_type`
- `start_time` / `end_time` / `duration_ms`
- `status` / `outcome`
- `input_summary`
- `output_summary`
- `error`

Trace 由 engine 自动记录，不需要每个节点手写计时逻辑。`input_summary` 和 `output_summary` 会压缩长字符串和列表，只保留演示所需摘要。

API 响应会额外返回 `reflection_decision`、脱敏后的 `sql_contexts`、`hitl_required` 和 `hitl_reason`。其中 SQLContext 只暴露 SQL 长度与 hash，不暴露完整 SQL 或完整结果集。

维护提示：如果改变 `TraceEvent` 字段或序列化结构，要同步更新前端 `TraceEventPayload`、`GenerationDetails` 展示逻辑和本文档。
