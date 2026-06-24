# SQL 生成过程代码追踪

本文档按真实调用顺序追踪一次 `POST /api/v1/query` 如何从自然语言问题走到 SQL 生成、校验、执行和 finalization。默认服务调用链以 `workflow.yaml` 的 OpenAI-compatible provider 配置为准；测试和 `scripts/run_demo.py` 会显式注入 `MockLLMClient`。

## 1. API 请求进入应用服务

入口文件：`src/text_to_sql_demo/main.py`

`create_app` 注册 `POST /api/v1/query`，路由函数只做一件事：

```python
@app.post("/api/v1/query")
def query(request: QueryRequest) -> dict[str, Any]:
    return service.run_query(request)
```

`QueryRequest` 来自 `src/text_to_sql_demo/api/models.py`，字段包括：

- `question`
- `target_dialect`，默认 `sqlite`
- `max_attempts`，范围 `0..3`
- `debug`
- `runtime_config_id`，可选，使用前端创建的短生命周期数据库和模型配置

维护提示：如果修改请求字段或路由路径，需要同步更新 README 的 API 示例、前端 `RunQueryRequest` 和本文档。

## 2. TextToSQLApiService.run_query 初始化运行状态

文件：`src/text_to_sql_demo/api/service.py`

`TextToSQLApiService.run_query` 执行以下动作：

1. `ensure_database()`：如果 SQLite demo 文件不存在，调用 `initialize_database` 创建。
2. `_resolve_runtime_config()`：根据可选 `runtime_config_id` 解析本次数据库 URL、目标方言、LLM client 和模型 profiles；不传时使用 `workflow.yaml` 默认配置。
3. `read_schema()`：通过 `read_schema_metadata` 从解析后的数据库连接 introspection 获取 schema。
4. 创建 `WorkflowState`，把 `schema`、`target_dialect`、`runtime_config_id`、`max_repair_attempts`、`debug` 放进 `state.data`。
5. 创建 `WorkflowEngine`，注入：
   - 当前请求覆盖后的 `WorkflowConfig`
   - `NodeFactory`
   - `NodeDependencies`，包含 `database_url`、`llm_client`、`model_profiles`
6. 调用 `engine.run(state)`。
7. 保存最终状态到 `InMemoryRunStore`，并用 `serialize_run` 输出 API payload。

维护提示：如果 `run_query` 增加新的 state 初始化字段，要同步更新 [工作流文档](文本转SQL工作流.md) 的状态说明和前端 API 类型。

## 3. WorkflowEngine.run 按配置流转

文件：`src/text_to_sql_demo/workflow/engine.py`

`WorkflowEngine.run` 从 `config.workflow.start_node` 读取起点，即 `begin`。每轮执行：

1. 根据节点名读取 `config.nodes[current_node]`。
2. 调用 `NodeFactory.create` 创建节点。
3. 调用 `_execute_node` 执行 `node.before -> node.run -> state.apply_patch -> node.after`。
4. 追加 `TraceEvent`。
5. 如果节点返回 `terminate` 或配置边不存在，终止。
6. 否则根据 `result.outcome` 和 `edges[current_node].target_for(outcome)` 找下一节点。

维护提示：如果修改 `NodeResult` 或 edge 解析规则，要同步更新 boxed plaintext/Mermaid 图和 `tests/unit/workflow/test_engine.py`。

## 4. BeginNode 和 SelectionNode 初始化任务与意图

文件：`src/text_to_sql_demo/nodes/begin.py`、`src/text_to_sql_demo/nodes/selection.py`

`BeginNode.run` 把原始问题、`request_id` 和入口节点写入 `state.data.task`，用于把任务初始化显式纳入 Trace。

`SelectionNode.run` 做轻量意图分类，当前默认输出 `text_to_sql`，写入 `state.data.intent`。`workflow.yaml` 通过 `on_text_to_sql` 把流程导向 `schema_linking`；后续如果接入非 SQL 意图，可以新增 outcome 和 edge，而不用改 `WorkflowEngine`。

维护提示：如果将 Selection 改成真正多意图分类，需要补充意图枚举、分支测试和 API 响应说明。

## 5. SchemaLinkingNode.run 选择相关 Schema

文件：`src/text_to_sql_demo/nodes/schema_linking.py`

`SchemaLinkingNode.run` 从 `state.data.schema` 读取完整 schema，调用 `SchemaLinker.link`。`SchemaLinker` 位于 `src/text_to_sql_demo/schema/linking.py`，当前策略包括：

- 表名和字段名匹配。
- 默认中文描述和同义词扩展，例如“地区”“客户”“订单”“金额”。
- CJK n-gram。
- 外键扩展，把高相关表的关联表补进候选。
- 表数和字段数裁剪。

输出写入 `state.data.schema_linking`，供检索和 prompt pruning 使用。

维护提示：如果调整 schema linking 规则、字段上限或输出结构，必须同步更新 PromptBuilder 文档、前端使用的数据表展示和 schema linking 单元测试。

## 6. ContextRetrievalNode.run 检索知识库上下文

文件：`src/text_to_sql_demo/nodes/context_retrieval.py`、`src/text_to_sql_demo/retrieval/knowledge.py`

`ContextRetrievalNode.run` 读取 `schema_linking.tables` 和原始问题，调用 `KnowledgeStore.search`。默认知识库路径是 `configs/knowledge.yaml`，由 `workflow.yaml` 的 `retrieval.knowledge_path` 在请求级配置中注入。

当前 `KnowledgeStore` 支持四类本地 YAML fallback：

- `reference_sql`
- `documents`
- `metrics`
- `semantic_models`

检索策略按问题词项重叠和 linked tables 重叠打分，返回 Top-K，并写入 `state.data.rag_context`。当前阶段没有强依赖向量数据库；后续接入 LanceDB/FastEmbed/PyArrow 时，应保持测试可注入本地 fallback 或 Mock store。

维护提示：如果调整 `rag_context` 结构，需要同步更新 `PromptBuilder`、`serialize_run`、前端 `RagContextPayload` 和上下文检索单元测试。

## 7. ExampleRetrievalNode.run 检索 Top-K SQL 示例

文件：`src/text_to_sql_demo/nodes/example_retrieval.py`

`ExampleRetrievalNode.run` 使用 `ExampleStore.from_yaml` 加载本地示例。当前节点默认路径是 `configs/examples.yaml`。检索逻辑在 `src/text_to_sql_demo/retrieval/examples.py`：

- 对自然语言、tags、involved tables 做词法 token。
- 按 query 词项重叠打分。
- 按 linked schema 表重叠加权。
- 按 dialect 过滤。
- 返回 `top_k` 个 `ExampleSearchResult`。

输出写入 `state.data.retrieved_examples` 和 `state.data.available_example_count`。

维护提示：如果将来接入向量检索或修改 examples 路径，README 和完成度分析必须明确说明当前能力边界变化。

## 8. GenSQLAgenticNode.run 完成路由、Prompt 和 LLM 调用

文件：`src/text_to_sql_demo/nodes/sql_generation.py`

`GenSQLAgenticNode.run` 是 SQL 生成的核心节点，旧名 `GenerateSQLNode` 保留为兼容别名。内部顺序为：

1. 从依赖容器读取 `llm_client`。
2. 从依赖或配置读取 `model_profiles`。
3. 读取 `schema_linking`、`rag_context`、`retrieved_examples` 和 `target_dialect`。
4. 按配置的 `patterns_path` 检索业务方言范式，结果写入 `business_patterns`。
5. 调用 `ComplexityClassifier().classify(question, linked_schema)`。
6. 调用 `ModelRouter(profiles).route(complexity)`，simple 选择 `light`，medium/complex 选择 `strong`。
7. 调用 `PromptBuilder().build(...)`，可使用 `prompt_template` 指向的 YAML 模板。
8. 调用 `llm_client.complete(...)`。
9. 把 LLM 返回文本写入 `generated_sql`，并记录 `selected_model`、`complexity_level`、`routing_reason`、`prompt_summary`。

默认服务中的 `llm_client` 由 `TextToSQLApiService` 根据 `workflow.yaml` 或 `runtime_config_id` 解析得到；当前默认 workflow 会构造 OpenAI-compatible adapter。测试和 demo 脚本显式传入 `MockLLMClient`，它按 alias、sequence 或 default response 返回确定性 SQL，并保存请求，方便测试断言。

维护提示：如果将复杂度路由拆成独立节点，或新增模型 alias，必须同步更新 `workflow.yaml`、本文档、README 核心能力和 `tests/unit/routing/test_complexity_routing.py`。

## 9. PromptBuilder.build 做上下文裁剪

文件：`src/text_to_sql_demo/prompts/builder.py`

`PromptBuilder.build` 只把 linked schema、Top-K examples、RAG 上下文和业务方言范式放进 prompt：

- `Linked schema`：只包含 `schema_linking.tables` 中的表和字段。
- `Top-K examples`：只包含检索结果中的自然语言问题和 SQL。
- `Knowledge context`：只包含 `rag_context` 中裁剪后的 Reference SQL、文档片段、Metric 和 Semantic Model。
- `Business dialect patterns`：只包含按问题、方言和 linked tables 检索到的业务 SQL 范式。
- `SQL output constraints`：要求只返回一条 SQL，不加解释和代码块，只使用 linked schema。

同时输出 `summary`：

- `target_dialect`
- `linked_table_count`
- `linked_column_count`
- `example_count`
- `reference_sql_count`
- `document_context_count`
- `metric_context_count`
- `semantic_model_count`
- `business_pattern_count`
- `original_schema_table_count`
- `injected_schema_table_count`
- `original_example_count`
- `injected_example_count`

维护提示：如果 prompt 内容、summary 字段或裁剪策略变化，要同步更新 prompt 单元测试、Trace 展示说明和面试讲解材料。

## 10. ValidateSQLNode.run 校验 SQL

文件：`src/text_to_sql_demo/nodes/sql_validation.py`

`ValidateSQLNode.run` 读取 `generated_sql` 或 `current_sql`，调用 `SQLValidator.validate`：

1. `DialectService.parse_one` 使用 SQLGlot 按目标 dialect 解析，并拒绝多语句。
2. `_validate_read_only` 只允许包含 SELECT，拒绝 insert/update/delete/drop/create/alter/command。
3. `_validate_schema` 校验表名、字段名、别名和派生列。
4. 根据 `allow_transpile` 和 `render_dialect` 渲染标准化 SQL。

成功时 outcome 是 `validation_success`，写入 `validated_sql`、`validated_sql_dialect` 和 `current_sql`。失败时 outcome 是 `validation_failed`，写入 `last_error`。

维护提示：如果新增错误类型或改变只读安全规则，需要同步更新完成度分析和修复路径说明。

## 11. ExecuteSQLNode.run 执行已校验 SQL

文件：`src/text_to_sql_demo/nodes/sql_execution.py`

`ExecuteSQLNode.run` 支持 `sqlite`、`postgres`、`mysql` 三类执行方言。节点会先确认 `execution_dialect` 受支持，并且与 `validated_sql_dialect` 一致；不一致时返回 `execution_failed`，避免把按一种方言校验的 SQL 直接发到另一种数据库。通过后调用 `SQLExecutor.execute`：

- 使用 SQLAlchemy 创建 engine。
- 执行已校验 SQL。
- `fetchmany(max_rows)` 限制结果行数。
- 返回 `columns`、`rows`、`duration_ms`。
- 捕获 `SQLAlchemyError` 并包装为 `execution_error`。

维护提示：如果新增数据库 driver，不要只改 executor；还要更新配置说明、driver 到 SQLGlot dialect 的映射、只读保障策略、测试矩阵和 README 限制。

## 12. 策略反思闭环

文件：`src/text_to_sql_demo/nodes/error_reflection.py`、`src/text_to_sql_demo/nodes/sql_fix.py`、`src/text_to_sql_demo/nodes/reasoning_rewrite.py`、`src/text_to_sql_demo/nodes/hitl.py`、`src/text_to_sql_demo/reflection/`

当 validation 或 execution 失败时，`workflow.yaml` 把流程导向 `error_classification`，实际实现类是 `ReflectionDecisionNode`，并兼容旧的 `ReflectErrorNode` 导入名：

- 如果 `attempt_count >= max_repair_attempts`，返回 `attempts_exhausted` 并写入 HITL 原因。
- 否则根据 `SQLError.category` 写入 `reflection_decision`，例如 `FIX_SQL`、`RELINK_SCHEMA`、`REASONING_REWRITE`。
- 每轮失败会追加 `SQLAttemptContext`，prompt 和 API 只使用 hash/长度、错误类型、策略和原因摘要。

`FixSQLNode` 读取兼容的修复指令，把定向策略和最近 SQLContext 摘要注入修复 prompt，用 `strong` 模型 alias 调用 LLM，返回新 SQL，并追加：

- `attempt`
- `old_sql`
- `new_sql`
- `error_type`
- `reason`
- `strategy_name`

`ReasoningRewriteNode` 用用户问题、linked schema、RAG 上下文、最近 SQLContext、`last_error` 和反思原因重新生成 SQL，然后流程回到 `sql_validation`。`HITLNode` 只标记 `needs_human_review`，不实现审批 UI。

维护提示：如果新增不可修复错误策略或改变修复 prompt，必须同步更新 `tests/integration/test_sql_repair_workflow.py`、前端修复提示和 [工作流文档](文本转SQL工作流.md)。

## 13. FinalizeNode.run 与 API 响应

文件：`src/text_to_sql_demo/nodes/finalization.py`、`src/text_to_sql_demo/api/service.py`

`FinalizeNode.run` 根据 `execution_result.success` 收敛：

- 成功：`final_status=success`、`final_sql`、`final_result`、`attempt_count`。
- 失败：`final_status=failed`、`final_sql`、`final_error`、`attempt_count`、`termination_reason`。
- 人工介入：`final_status=needs_human_review`、`final_sql`、`final_error`、`attempt_count`、`hitl_reason`、`termination_reason`。

`serialize_run` 最终输出：

- `request_id`
- `status`
- `final_sql`
- `result`
- `attempts`
- `selected_model`
- `routing_reason`
- `linked_schema`
- `retrieved_examples`
- `rag_context`
- `repair_history`
- `reflection_decision`
- `sql_contexts`
- `hitl_required`
- `hitl_reason`
- `errors`
- `trace`

维护提示：如果 API 响应结构改变，需要同步更新 `frontend/src/api/types.ts`、`frontend/src/adapters/queryRunAdapter.ts`、README API 示例和本文档。
