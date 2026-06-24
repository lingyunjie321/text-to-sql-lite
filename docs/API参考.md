# API 参考

本文档集中列出项目所有 HTTP 接口的方法、路径、请求模型、响应模型和错误码。接口定义在 `src/text_to_sql_demo/main.py`，请求/响应模型在 `src/text_to_sql_demo/api/models.py` 和 `src/text_to_sql_demo/runtime/models.py`。运行时配置相关接口的细节见 [运行时配置](运行时配置.md)。

## 基础信息

- Base URL：`http://127.0.0.1:8000`
- Content-Type：`application/json`
- 统一错误响应结构见文末[错误响应](#错误响应)。

## 健康检查

### `GET /health`

返回最小可用存活检查。

**响应**：

```json
{"status": "ok", "service": "text-to-sql-demo"}
```

## 查询与运行记录

### `POST /api/v1/query`

执行一次 Text-to-SQL 工作流。

**请求体**（`QueryRequest`）：

| 字段 | 类型 | 必填 | 默认 | 说明 |
| --- | --- | --- | --- | --- |
| `question` | `string` | 是 | - | 自然语言问题，min_length=1 |
| `target_dialect` | `string` | 否 | `sqlite` | 目标 SQL 方言，可选 `sqlite`/`postgres`/`mysql` |
| `max_attempts` | `int` | 否 | `3` | 最大修复尝试次数，范围 0-3 |
| `debug` | `bool` | 否 | `false` | 是否返回调试信息（trace summary 等） |
| `runtime_config_id` | `string` | 否 | - | 运行时配置 ID，使用前端创建的临时配置 |
| `database_preset_id` | `string` | 否 | - | 数据库预设 ID，指定自动发现的 SQLite 数据源 |

**响应**（`serialize_run` 输出）：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `request_id` | `string` | 请求 ID |
| `status` | `string` | 最终状态：`success`/`failed`/`needs_human_review` |
| `final_sql` | `string` | 最终 SQL |
| `result` | `object` | 执行结果（columns/rows/duration_ms） |
| `attempts` | `int` | 修复尝试次数 |
| `selected_model` | `string` | 选中的模型 alias |
| `routing_reason` | `string` | 模型路由原因 |
| `linked_schema` | `object` | linked schema 子集 |
| `retrieved_examples` | `array` | Top-K SQL 示例 |
| `rag_context` | `object` | RAG 上下文（reference_sql/documents/metrics/semantic_models） |
| `repair_history` | `array` | 修复历史 |
| `reflection_decision` | `object` | 反思决策 |
| `sql_contexts` | `array` | 脱敏 SQL 尝试记忆（只含 hash/长度/错误/策略） |
| `hitl_required` | `bool` | 是否需要人工介入 |
| `hitl_reason` | `string` | 人工介入原因 |
| `errors` | `array` | 错误列表 |
| `trace` | `array` | 节点级 Trace |

**示例**：

```bash
curl -X POST http://127.0.0.1:8000/api/v1/query \
  -H 'Content-Type: application/json' \
  -d '{
    "question": "统计每个地区的订单总金额",
    "target_dialect": "sqlite",
    "max_attempts": 3,
    "debug": true
  }'
```

### `GET /api/v1/runs`

列出持久化运行记录摘要。

**查询参数**：

| 参数 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| `limit` | `int` | `20` | 返回条数上限 |

**响应**：`{"items": [...], "total": int}`

### `GET /api/v1/runs/{request_id}`

按 `request_id` 查询某次工作流运行记录。返回结构与 `POST /api/v1/query` 响应一致。

## 收藏 SQL 与审核

### `POST /api/v1/saved-queries`

保存一条可复用 SQL。默认状态为 `draft`，不进入 prompt 检索；需审核为 `approved` 后才进入。

**请求体**（`SavedQueryCreateRequest`）：

| 字段 | 类型 | 必填 | 默认 | 说明 |
| --- | --- | --- | --- | --- |
| `name` | `string` | 是 | - | 名称，min_length=1 |
| `request_id` | `string` | 否 | - | 关联的运行 ID |
| `question` | `string` | 否 | - | 自然语言问题 |
| `sql` | `string` | 否 | - | SQL |
| `tags` | `array[string]` | 否 | `[]` | 标签 |
| `status` | `string` | 否 | `draft` | 状态：`draft`/`approved`/`deprecated` |

### `GET /api/v1/saved-queries`

列出收藏 SQL。

**查询参数**：

| 参数 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| `limit` | `int` | `20` | 返回条数上限 |

### `PATCH /api/v1/saved-queries/{saved_query_id}/status`

轻量审核入口，更新收藏 SQL 状态。真实权限控制留给后续产品化。

**请求体**（`SavedQueryStatusUpdateRequest`）：

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `status` | `string` | 是 | `draft`/`approved`/`deprecated` |

**示例**（审核为 approved）：

```bash
curl -X PATCH http://127.0.0.1:8000/api/v1/saved-queries/{saved_query_id}/status \
  -H 'Content-Type: application/json' \
  -d '{"status": "approved"}'
```

## 反馈

### `POST /api/v1/runs/{request_id}/feedback`

记录用户对一次查询运行的反馈。

**请求体**（`FeedbackCreateRequest`）：

| 字段 | 类型 | 必填 | 默认 | 说明 |
| --- | --- | --- | --- | --- |
| `rating` | `string` | 是 | - | 评分：`up`/`down`/`neutral` |
| `issue_type` | `string` | 否 | - | 问题类型 |
| `comment` | `string` | 否 | - | 评论 |

## Schema

### `GET /api/v1/schema`

返回当前 demo 数据库 Schema 元数据。

**查询参数**：

| 参数 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| `runtime_config_id` | `string` | - | 运行时配置 ID |
| `database_preset_id` | `string` | - | 数据库预设 ID |

## 运行时配置

### `GET /api/v1/runtime/options`

返回运行时配置可选项（预置数据库、预置模型）。详见 [运行时配置](运行时配置.md)。

### `POST /api/v1/runtime/configs`

创建短生命周期运行时配置。详见 [运行时配置](运行时配置.md)。

## SQL 执行与转换

### `POST /api/v1/sql/execute`

执行用户编辑后的只读 SQL。会做 SQLGlot 只读校验，拒绝写入/DDL/多语句。

**请求体**（`ExecuteSQLRequest`）：

| 字段 | 类型 | 必填 | 默认 | 说明 |
| --- | --- | --- | --- | --- |
| `sql` | `string` | 是 | - | SQL，min_length=1 |
| `target_dialect` | `string` | 否 | `sqlite` | 方言 |
| `max_rows` | `int` | 否 | `100` | 最大返回行数，范围 1-500 |
| `runtime_config_id` | `string` | 否 | - | 运行时配置 ID |
| `database_preset_id` | `string` | 否 | - | 数据库预设 ID |

### `POST /api/v1/transpile`

转换已有 SQL 到目标方言。

**请求体**（`TranspileRequest`）：

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `sql` | `string` | 是 | SQL，min_length=1 |
| `source_dialect` | `string` | 是 | 源方言 |
| `target_dialect` | `string` | 是 | 目标方言 |

**响应**（`DialectRenderResult`）：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `source_dialect` | `string` | 源方言 |
| `target_dialect` | `string` | 目标方言 |
| `normalized_sql` | `string` | 标准化 SQL |
| `rendered_sql` | `string` | 渲染后 SQL |
| `transpiled` | `bool` | 是否发生转换 |

**兼容路径**：`POST /transpile` 为旧路径，功能相同，兼容已有测试和示例。

## 错误响应

所有错误使用统一结构（`ErrorResponse`）：

```json
{
  "error": {
    "code": "错误码",
    "message": "人类可读说明",
    "details": {}
  }
}
```

### 错误码

| 错误码 | HTTP 状态码 | 说明 |
| --- | --- | --- |
| `validation_error` | 422 | 请求参数校验失败（Pydantic/FastAPI） |
| `http_error` | 400/404/... | FastAPI HTTPException |
| `service_config_error` | 500 | 服务初始化失败（配置/凭据/LLM/数据库） |
| `runtime_config_not_found` | 404 | 找不到运行时配置 |
| `runtime_config_expired` | 410 | 运行时配置已过期 |
| `runtime_config_invalid` | 400 | 运行时配置结构无效 |
| `runtime_preset_not_found` | 404 | 数据库或模型预设不存在 |
| `runtime_connection_failed` | 400 | 创建配置时数据库或模型连通性检查失败 |
| `runtime_secret_missing` | 400 | 缺少 API Key 或数据库密码 |
| `runtime_provider_unsupported` | 400 | provider 不支持 |

`details` 中不包含密码、API Key、Authorization、完整数据库 URL、完整 prompt、完整 SQL 或完整结果集。

维护规范见 [文档维护规范](文档维护规范.md)。
