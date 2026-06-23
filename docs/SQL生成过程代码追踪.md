# SQL 生成过程代码追踪

本文档按真实调用顺序追踪一次 `POST /api/v1/query` 如何从自然语言问题走到 SQL 生成、校验、执行和 finalization。示例调用链以当前默认配置和 `MockLLMClient` 为准。

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

维护提示：如果修改请求字段或路由路径，需要同步更新 README 的 API 示例、前端 `RunQueryRequest` 和本文档。

## 2. TextToSQLApiService.run_query 初始化运行状态

文件：`src/text_to_sql_demo/api/service.py`

`TextToSQLApiService.run_query` 执行以下动作：

1. `ensure_database()`：如果 SQLite demo 文件不存在，调用 `initialize_database` 创建。
2. `read_schema()`：通过 `read_schema_metadata` 从数据库 introspection 获取 schema。
3. 创建 `WorkflowState`，把 `schema`、`target_dialect`、`max_repair_attempts`、`debug` 放进 `state.data`。
4. 创建 `WorkflowEngine`，注入：
   - 当前请求覆盖后的 `WorkflowConfig`
   - `NodeFactory`
   - `NodeDependencies`，包含 `database_url`、`llm_client`、`model_profiles`
5. 调用 `engine.run(state)`。
6. 保存最终状态到 `InMemoryRunStore`，并用 `serialize_run` 输出 API payload。

维护提示：如果 `run_query` 增加新的 state 初始化字段，要同步更新 [工作流文档](文本转SQL工作流.md) 的状态说明和前端 API 类型。

## 3. WorkflowEngine.run 按配置流转

文件：`src/text_to_sql_demo/workflow/engine.py`

`WorkflowEngine.run` 从 `config.workflow.start_node` 读取起点，即 `schema_linking`。每轮执行：

1. 根据节点名读取 `config.nodes[current_node]`。
2. 调用 `NodeFactory.create` 创建节点。
3. 调用 `_execute_node` 执行 `node.before -> node.run -> state.apply_patch -> node.after`。
4. 追加 `TraceEvent`。
5. 如果节点返回 `terminate` 或配置边不存在，终止。
6. 否则根据 `result.outcome` 和 `edges[current_node].target_for(outcome)` 找下一节点。

维护提示：如果修改 `NodeResult` 或 edge 解析规则，要同步更新 boxed plaintext/Mermaid 图和 `tests/unit/workflow/test_engine.py`。

## 4. SchemaLinkingNode.run 选择相关 Schema

文件：`src/text_to_sql_demo/nodes/schema_linking.py`

`SchemaLinkingNode.run` 从 `state.data.schema` 读取完整 schema，调用 `SchemaLinker.link`。`SchemaLinker` 位于 `src/text_to_sql_demo/schema/linking.py`，当前策略包括：

- 表名和字段名匹配。
- 默认中文描述和同义词扩展，例如“地区”“客户”“订单”“金额”。
- CJK n-gram。
- 外键扩展，把高相关表的关联表补进候选。
- 表数和字段数裁剪。

输出写入 `state.data.schema_linking`，供检索和 prompt pruning 使用。

维护提示：如果调整 schema linking 规则、字段上限或输出结构，必须同步更新 PromptBuilder 文档、前端使用的数据表展示和 schema linking 单元测试。

## 5. ExampleRetrievalNode.run 检索 Top-K SQL 示例

文件：`src/text_to_sql_demo/nodes/example_retrieval.py`

`ExampleRetrievalNode.run` 使用 `ExampleStore.from_yaml` 加载本地示例。当前节点默认路径是 `configs/examples.yaml`。检索逻辑在 `src/text_to_sql_demo/retrieval/examples.py`：

- 对自然语言、tags、involved tables 做词法 token。
- 按 query 词项重叠打分。
- 按 linked schema 表重叠加权。
- 按 dialect 过滤。
- 返回 `top_k` 个 `ExampleSearchResult`。

输出写入 `state.data.retrieved_examples` 和 `state.data.available_example_count`。

维护提示：如果将来接入向量检索或修改 examples 路径，README 和完成度分析必须明确说明当前能力边界变化。

## 6. GenerateSQLNode.run 完成路由、Prompt 和 Mock LLM

文件：`src/text_to_sql_demo/nodes/sql_generation.py`

`GenerateSQLNode.run` 是 SQL 生成的核心节点，内部顺序为：

1. 从依赖容器读取 `llm_client`。
2. 从依赖或配置读取 `model_profiles`。
3. 读取 `schema_linking`、`retrieved_examples` 和 `target_dialect`。
4. 调用 `ComplexityClassifier().classify(question, linked_schema)`。
5. 调用 `ModelRouter(profiles).route(complexity)`，simple 选择 `light`，medium/complex 选择 `strong`。
6. 调用 `PromptBuilder().build(...)`。
7. 调用 `llm_client.complete(...)`。
8. 把 LLM 返回文本写入 `generated_sql`，并记录 `selected_model`、`complexity_level`、`routing_reason`、`prompt_summary`。

当前默认 `llm_client` 是 `MockLLMClient`。它按 alias、sequence 或 default response 返回确定性 SQL，并保存请求，方便测试断言。

维护提示：如果将复杂度路由拆成独立节点，或新增模型 alias，必须同步更新 `workflow.yaml`、本文档、README 核心能力和 `tests/unit/routing/test_complexity_routing.py`。

## 7. PromptBuilder.build 做上下文裁剪

文件：`src/text_to_sql_demo/prompts/builder.py`

`PromptBuilder.build` 只把 linked schema 和 Top-K examples 放进 prompt：

- `Linked schema`：只包含 `schema_linking.tables` 中的表和字段。
- `Top-K examples`：只包含检索结果中的自然语言问题和 SQL。
- `SQL output constraints`：要求只返回一条 SQL，不加解释和代码块，只使用 linked schema。

同时输出 `summary`：

- `target_dialect`
- `linked_table_count`
- `linked_column_count`
- `example_count`
- `original_schema_table_count`
- `injected_schema_table_count`
- `original_example_count`
- `injected_example_count`

维护提示：如果 prompt 内容、summary 字段或裁剪策略变化，要同步更新 prompt 单元测试、Trace 展示说明和面试讲解材料。

## 8. ValidateSQLNode.run 校验 SQL

文件：`src/text_to_sql_demo/nodes/sql_validation.py`

`ValidateSQLNode.run` 读取 `generated_sql` 或 `current_sql`，调用 `SQLValidator.validate`：

1. `DialectService.parse_one` 使用 SQLGlot 按目标 dialect 解析，并拒绝多语句。
2. `_validate_read_only` 只允许包含 SELECT，拒绝 insert/update/delete/drop/create/alter/command。
3. `_validate_schema` 校验表名、字段名、别名和派生列。
4. 根据 `allow_transpile` 和 `render_dialect` 渲染标准化 SQL。

成功时 outcome 是 `validation_success`，写入 `validated_sql`、`validated_sql_dialect` 和 `current_sql`。失败时 outcome 是 `validation_failed`，写入 `last_error`。

维护提示：如果新增错误类型或改变只读安全规则，需要同步更新完成度分析和修复路径说明。

## 9. ExecuteSQLNode.run 执行 SQLite SQL

文件：`src/text_to_sql_demo/nodes/sql_execution.py`

`ExecuteSQLNode.run` 只执行 SQLite 方言 SQL。如果 `execution_dialect` 或 `validated_sql_dialect` 不是 `sqlite`，直接返回 `execution_failed`。否则调用 `SQLExecutor.execute`：

- 使用 SQLAlchemy 创建 engine。
- 执行已校验 SQL。
- `fetchmany(max_rows)` 限制结果行数。
- 返回 `columns`、`rows`、`duration_ms`。
- 捕获 `SQLAlchemyError` 并包装为 `execution_error`。

维护提示：如果将来支持 PostgreSQL 执行，不要只改 executor；还要更新配置说明、只读保障策略、测试矩阵和 README 限制。

## 10. Reflect/Fix 修复闭环

文件：`src/text_to_sql_demo/nodes/error_reflection.py`、`src/text_to_sql_demo/nodes/sql_fix.py`

当 validation 或 execution 失败时，`workflow.yaml` 把流程导向 `error_classification`，实际实现类是 `ReflectErrorNode`：

- 如果 `attempt_count >= max_repair_attempts`，返回 `attempts_exhausted`。
- 否则构造 `RepairInstruction`，包含原问题、当前 SQL、错误类型、错误原文、相关 schema 和修复历史。

`FixSQLNode` 读取修复指令，用 `strong` 模型 alias 调用 LLM，返回新 SQL，并追加：

- `attempt`
- `old_sql`
- `new_sql`
- `error_type`
- `reason`

然后流程回到 `sql_validation`。

维护提示：如果新增不可修复错误策略或改变修复 prompt，必须同步更新 `tests/integration/test_sql_repair_workflow.py`、前端修复提示和 [工作流文档](文本转SQL工作流.md)。

## 11. FinalizeNode.run 与 API 响应

文件：`src/text_to_sql_demo/nodes/finalization.py`、`src/text_to_sql_demo/api/service.py`

`FinalizeNode.run` 根据 `execution_result.success` 收敛：

- 成功：`final_status=success`、`final_sql`、`final_result`、`attempt_count`。
- 失败：`final_status=failed`、`final_sql`、`final_error`、`attempt_count`、`termination_reason`。

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
- `repair_history`
- `errors`
- `trace`

维护提示：如果 API 响应结构改变，需要同步更新 `frontend/src/api/types.ts`、`frontend/src/adapters/queryRunAdapter.ts`、README API 示例和本文档。
