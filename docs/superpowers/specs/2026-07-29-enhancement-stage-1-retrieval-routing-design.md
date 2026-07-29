# 增强阶段 1：检索与路由增强设计

## 目标

在不重写现有 Connector、SQLGlot 安全门、执行边界、attempt、Workflow 终态和
评测体系的前提下，为当前 Text-to-SQL 闭环增加：

- 显式、可解释、确定性的 `ComplexityRouteNode`；
- 5/10/20 动态 Schema Top-K；
- OpenAI-compatible Embedding；
- BM25 与 Embedding 双路授权内召回；
- RRF 融合；
- 可解释、确定性 Rerank；
- 服务端多模型路由；
- 字段和输入预算驱动的上下文裁剪；
- 对应的版本、Trace、指标、错误、降级和安全证明。

本阶段结束时，所有生成或修复 SQL 仍必须经过现有
`validate_sql()` 和 `execute_validated_sql()`；路由、检索、模型选择和上下文
裁剪不能改变权限、安全、函数、只读、30 秒数据库超时、1000 行或三次修复
边界。

## 依赖决策

- 主规格和测试规格的阶段 0 基线；
- ADR 0002 授权元数据快照与 `schema_version`；
- ADR 0003 SQLGlot fail-closed 安全门；
- ADR 0004 BM25/FK Linking 的已验证行为；
- ADR 0005 OpenAI-compatible 生成协议和安全 HTTP 约束；
- ADR 0006 执行前重新校验；
- ADR 0007 attempt、指纹和有限修复；
- ADR 0008 的 State/Context/预算/错误路由；
- ADR 0010 的 Gold、Trace、冻结与正式评测边界；
- ADR 0011 的显式 `ComplexityRouteNode` 和两遍 Linking。

用户已确认采用显式 `ComplexityRouteNode`。本设计不再保留九节点内嵌策略作为
备选。

## 完成状态

阶段能力分别记录：

- `functional_complete`：本地真实实现和确定性测试完成；
- `integration_complete`：Workflow/API/Trace/安全/评测贯通；
- `real_environment_validated`：真实 Embedding、至少两个真实生成模型及真实
  Pagila 冻结验证完成。

只有 Stub 或本地伪向量时不得标记第三项。

## 范围

### 包含

- 十种业务节点和探测—路由—物化链路；
- 版本化 `complexity-v1`；
- 内部封闭的 5/10/20 Schema Top-K；
- Schema/语义文档的 Embedding；
- 进程内、权限安全、有界、版本化向量索引；
- BM25/Embedding 各自排名和 RRF `k=60`；
- 白名单特征、理由码驱动的确定性 Rerank；
- 关键字段保护和保守输入 token 估算；
- 多个 OpenAI-compatible 生成配置的服务端路由与一次受限回退；
- 单元、集成、安全、非 Gold 检索评测和真实环境门禁；
- 新 baseline、Trace 和报告契约版本。

### 不包含

- 动态 Few-shot、业务指标知识和业务 RAG；它们属于阶段 2；
- Session、Checkpoint、Compaction 和长期 Memory；属于阶段 3；
- MySQL、StarRocks、跨源 QueryPlan；属于阶段 4；
- 分布式缓存、外部向量数据库、结果缓存、导出、限流和 Dashboard；属于阶段 5；
- 列级/行级权限或完整多租户产品能力；
- LLM Reranker、LLM 复杂度分类或根据 Pagila Gold 调参。

这些能力仍是最终交付必做范围，只是不在本阶段混写。

## 方案选择

### 采用：本地有界混合检索

保留现有纯 Python BM25/FK 实现，增加 OpenAI-compatible Embedding、
进程内有界向量索引、纯 Python cosine、RRF 和确定性 Rerank。

优点：

- 不新增生产依赖；
- 可以完整验证授权、版本、融合和降级；
- 不把阶段 1 绑定 PostgreSQL/pgvector，避免阻碍阶段 4 多数据库；
- 后续外部索引必须保持同一行为契约，可由容量证据驱动替换。

### 拒绝：pgvector

持久化方便，但把检索基础绑定 PostgreSQL，且要求扩展、迁移和额外真实环境。
在多数据库契约稳定前不采用。

### 拒绝：独立搜索/向量服务和 Cross-encoder

容量更强，但立即增加数据出域、依赖、运维、权限同步和故障面。阶段 5 有容量
证据后另行决策。

## 总体链路

```text
RequestPreprocess
→ PermissionResolve
→ SchemaLinking(probe K=20, current authorized snapshot)
→ ComplexityRoute(complexity-v1)
→ SchemaLinking(materialize K=5/10/20, same snapshot)
→ ModelRoute
→ ContextSelect
→ GenerateSQL
→ ValidateSQL
→ ExecuteSQL
→ Finalize
```

`ContextSelect` 和 `ModelRoute` 是阶段 1 内部纯服务，不增加新的 Workflow 节点。
它们由 `GenerateSQLNode` 消费，并以独立 State/Trace observation 留证。只有用户
确认的 `ComplexityRouteNode` 新增为显式业务节点。

Schema 修复：

```text
Execute/Validate(SCHEMA_ERROR)
→ ReflectSQL(RELINK_SCHEMA)
→ clear current retrieval decision
→ SchemaLinking(probe)
→ ComplexityRoute
→ SchemaLinking(materialize)
→ GenerateSQL
```

语法/方言修复沿用当前授权快照、最终候选、复杂度、上下文和模型层级。

## 模块边界

```text
app/
├── schema_linking/
│   ├── models.py          # Top-K、候选、通道和融合证据
│   ├── linker.py          # 现有授权 BM25/FK，接受内部预算
│   ├── embedding.py       # Embedding 协议、真实 Provider、响应校验
│   ├── index.py           # 版本键、授权文档和有界进程索引
│   ├── fusion.py          # RRF
│   └── rerank.py          # 确定性特征、理由码和集合级重排
├── generation/
│   ├── context.py         # 字段选择、保守 token 估算
│   ├── routing.py         # 服务端模型路由和受限回退决策
│   └── provider.py        # 现有单 Provider 继续实现生成协议
├── workflow/
│   ├── complexity.py      # complexity-v1 纯决策
│   ├── models.py          # 决策和 observation
│   ├── nodes.py           # 显式节点及消费服务
│   └── graph.py           # 十种节点和完整边
└── observability/
    ├── models.py
    └── tracing.py
```

文件只在对应行为任务开始时创建，不预建空模块。

## 核心模型

### 复杂度

```python
class QueryComplexity(str, Enum):
    SIMPLE = "simple"
    MEDIUM = "medium"
    COMPLEX = "complex"


class ComplexityReason(str, Enum):
    AGGREGATION_REQUESTED = "aggregation_requested"
    WINDOW_OR_RANKING_REQUESTED = "window_or_ranking_requested"
    SUBQUERY_OR_ANTI_JOIN_REQUESTED = "subquery_or_anti_join_requested"
    TIME_ANALYSIS_REQUESTED = "time_analysis_requested"
    MULTIPLE_POSITIVE_TABLES = "multiple_positive_tables"
    RELEVANT_JOIN_PATH = "relevant_join_path"
    LONG_JOIN_PATH = "long_join_path"
    REPAIR_HISTORY = "repair_history"
    DEFAULT_SIMPLE = "default_simple"


class ComplexityDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    level: QueryComplexity
    schema_top_k: Literal[5, 10, 20]
    reason_codes: tuple[ComplexityReason, ...]
    policy_version: Literal["complexity-v1"] = "complexity-v1"
```

模型校验 `level/schema_top_k/reason_codes` 与 `complexity-v1` 映射完全一致；
理由去重并按枚举声明顺序稳定排序。

### 检索版本

```python
class RetrievalVersion(BaseModel):
    datasource_id: str
    authorization_scope_sha256: str
    schema_version: str
    semantic_version: str
    embedding_model: str
    embedding_dimension: int
    document_version: Literal["schema-doc-v1"]
    fusion_version: Literal["rrf-v1"]
    rerank_version: Literal["schema-rerank-v1"]
```

完整模型规范 JSON 的 SHA-256 是 `retrieval_version_id`。任何字段变化都不能
读取旧索引。

### 通道与融合证据

候选内部证据包含：

- 规范对象 ID；
- `bm25_rank`、`embedding_rank`；
- 每路匹配 token 或相似度的脱敏数值；
- RRF 每路贡献和总分；
- Rerank 前后 rank；
- Rerank 理由码；
- 是否为相关正分候选间的必需 FK bridge。

完整逐对象证据只进入请求期内部 State；Trace 只接收不含对象 ID 的数量、rank
变化、理由码和版本摘要。Prompt 只接收最终授权候选及必要 Schema。

## `complexity-v1`

### 问题信号

规范化问题使用 NFKC、casefold 和固定中英文短语表。信号类别为：

- aggregation：count/sum/average/total/minimum/maximum、数量/总数/合计/平均/
  最小/最大；
- window/ranking：rank/ranking/top/bottom/running total/moving average/
  partition/over、排名/排行/累计/移动平均；
- subquery/anti-join：without/never/not exists/except、没有/从未/不存在；
- time analysis：daily/weekly/monthly/yearly/trend/growth、每天/每周/每月/
  每年/趋势/同比/环比/增长。

ASCII 短语按 token/短语边界匹配；中文按完整短语匹配，不使用单字符“前/后/未”
等宽泛规则。

### 候选信号

- `positive_tables` 只包含探测候选中融合/BM25 分数大于零的表；
- 至少两个正分表产生 `multiple_positive_tables`；
- JOIN Path 只有连接至少两个正分表时产生 `relevant_join_path`；
- 相关路径边数至少 2 时产生 `long_join_path`；
- `has_repair_history=True` 产生 `repair_history`。Workflow 在已有 SQL attempt
  且进入修复流程，或 `repair_count > 0` 时派生该值；纯策略不直接解释
  attempt 的计数时序。

### 决策

1. 任一 window/ranking、subquery/anti-join、long join 或 repair 信号：
   `complex/20`；
2. 否则，中等信号
   `{aggregation, time, multiple_positive_tables, relevant_join_path}`
   至少两类：`complex/20`；
3. 否则，任一中等信号：`medium/10`；
4. 否则：`simple/5` 和 `default_simple`。

所有命中理由都保留，不只保留触发最终等级的理由。

## 两遍 Schema Linking

`link_schema()` 增加必填服务端关键字参数 `top_k: Literal[5, 10, 20]`，并在运行
时拒绝 bool、其他整数或外部字符串。API 不暴露该参数。

探测：

- 固定 `top_k=20`；
- 读取并过滤授权快照；
- 构建词法/向量文档和候选证据；
- 保存本轮 `SchemaSnapshot`。

物化：

- 使用 `decision.schema_top_k`；
- 复用同一个 Snapshot 和 retrieval version；
- FK 中间表计入预算；
- 最终字段、JOIN Path 只引用最终表；
- `SchemaLinkingResult` 携带 `top_k` 与 retrieval version。

Schema 修复会清除旧决策并重新读取快照；最终物化不得跨快照。

## Embedding

### Provider

```python
class EmbeddingProvider(Protocol):
    @property
    def model_id(self) -> str: ...

    @property
    def dimension(self) -> int: ...

    def embed(self, texts: Sequence[str]) -> tuple[tuple[float, ...], ...]: ...
```

真实实现调用 OpenAI-compatible `/embeddings`，复用现有 Provider 的：

- HTTPS 或 loopback HTTP 限制；
- Bearer secret；
- 禁止 redirect；
- 有界响应读取；
- timeout、连接、HTTP 和无效响应的脱敏错误；
- 不记录请求文档或原始响应。

响应必须满足：

- 向量数量等于输入数量；
- index 唯一且覆盖 `0..n-1`；
- 每个向量维数等于配置；
- 每个值是有限 float，bool 拒绝；
- 零范数向量拒绝；
- 模型标识与配置一致，或由兼容服务明确省略；
- 超过响应字节上限拒绝。

### 文档

`schema-doc-v1` 每个授权对象产生确定性 UTF-8 文档：

- 表：Schema/表名、批准 alias、注释；
- 字段：所属表、字段名、类型、批准 alias、注释；
- PK/FK：规范端点和列。

不包含样例值、视图原 SQL、未授权对象、问题、Gold、Few-shot 或业务文档。
字段和列表稳定排序后才计算文档摘要与 Embedding。

### 进程索引

索引按 `retrieval_version_id` 存储不可变文档和归一化向量。进程内最多保留
32 个版本；新版本按最近最少使用淘汰。淘汰只影响性能，不影响语义；缺失时从
当前授权快照重建。

同一 version 的并发首次构建只允许一个 builder，其余等待同一结果。构建失败
不发布部分索引。阶段 5 再决定跨实例和持久化缓存。

## 双路召回与 RRF

- BM25 继续使用 ADR 0004 的公式和授权前置过滤；
- Embedding 使用 cosine，相似度相同按对象 ID 排序；
- 每路最多提供 20 个表候选和对应字段证据；
- RRF 固定：

```text
rrf_score(d) = Σ 1 / (60 + rank_channel(d))
```

rank 从 1 开始。缺席通道不贡献；同对象去重；融合分相同按规范对象 ID 排序。
不归一化或混合 BM25/cosine 原始分值。

Embedding 故障时：

- 当前授权同版本 BM25 可用：降级为 BM25-only，Trace 标记
  `embedding_degraded`；
- 无同版本 BM25 或版本不一致：结构化内部失败；
- 不使用旧向量，不调用更宽权限范围索引。

## 可解释 Rerank

第一版不用 LLM/cross-encoder。集合级稳定排序依次考虑：

1. 保留连接两个直接正分候选所必需的 bridge；
2. 问题直接命中字段数；
3. 已批准 alias 命中数；
4. 相关 JOIN 连通性与路径长度；
5. RRF 分数；
6. 规范对象 ID。

断开且没有直接证据的候选排在连通候选之后。每次排序保存实际生效的理由码：

- `required_bridge`
- `field_coverage`
- `approved_alias`
- `join_connectivity`
- `shorter_join_path`
- `fusion_rank`
- `disconnected_penalty`
- `canonical_tie_break`

Rerank 不能新增候选、恢复已过滤对象或删除最终候选间唯一必需 bridge。内部异常
降级为稳定 RRF 顺序并留证。

## 上下文裁剪

完整授权 Snapshot 继续交给 Validator；只有 Prompt 数据包被裁剪。

字段保留顺序：

1. 问题直接命中字段；
2. 最终 JOIN Path 的 PK/FK 字段；
3. 聚合、过滤、时间和粒度证据字段；
4. 其余按字段检索证据、表 rank 和规范 ID。

模型路由配置声明 `max_input_tokens` 和 `max_output_tokens`。不增加 tokenizer
依赖，阶段 1 使用保守估算：

```text
estimated_tokens = ceil(len(prompt_utf8_bytes) / 3)
usable_input = floor(max_input_tokens * 0.8) - max_output_tokens
```

选择器逐字段增加内容并在加入前验证预算。必要表、PK/FK 或 JOIN 字段不能装入
时返回结构化澄清/资源风险，不静默删除安全或关系证据。

## 多模型路由

WorkflowContext 从单一 Provider 扩展为服务端 `provider_registry` 和版本化
`model_route_table`。请求不能提供模型名。

初始映射：

- `simple` → `simple_route`
- `medium` → `standard_route`
- `complex` → `complex_route`

每个 route 配置 Provider key、模型配置摘要、输入/输出预算、超时和数据处理
边界 ID。不同 route 可以暂时指向同一真实模型，但此时不能标记多模型真实环境
验证完成。

只在连接、限流、容量或 Provider timeout 时允许一次 fallback；fallback 必须：

- 预先列入同一 route 配置；
- 具有相同数据处理边界 ID；
- 支持相同结构化输出契约和上下文大小；
- 写入 Trace；
- 不增加 `repair_count`。

无效 SQL、权限、安全、结构化输出错误和业务歧义不得通过换模型绕过。
可回退的生成错误码封闭为 `LLM_TIMEOUT`、`LLM_CONNECTION_ERROR`、
`LLM_RATE_LIMITED`（HTTP 429）和 `LLM_CAPACITY_ERROR`
（HTTP 502/503/504）。其他 HTTP 状态、响应格式、结构化输出和 SQL 校验错误
不得回退；Provider 不保存或暴露响应正文。

## 错误、超时、取消和降级

| 失败 | 行为 |
|---|---|
| Complexity 证据不一致 | `FAILED_INTERNAL`，不生成/执行 |
| Snapshot 在探测与物化间不一致 | 拒绝本轮，重新探测或 `FAILED_INTERNAL` |
| Embedding timeout/连接/限流 | 同版本 BM25-only；无安全词法路径则失败 |
| Embedding 响应非法/维数变化 | 不发布索引；同版本 BM25-only |
| RRF 输入 rank 非法 | `FAILED_INTERNAL` |
| Rerank 内部异常 | 稳定 RRF 顺序，记录降级 |
| Context 必要字段超预算 | `RESOURCE_RISK` 澄清/失败，不调用模型 |
| 主模型基础设施失败 | 同数据边界 fallback 一次 |
| fallback 失败 | 现有脱敏模型错误终态 |

所有外部调用使用 Workflow 剩余 deadline 与自身较小 timeout；取消不得发布部分
索引、部分候选或部分模型结果。

## 授权、版本和隔离

- 授权过滤永远在所有文档统计、Embedding、rank、融合和解释之前；
- 未授权名称、注释、alias、字段和 FK 变化不得改变授权范围的检索版本或结果；
- `authorization_scope_sha256` 只由规范授权 Schema/表 ID 计算，不写入对象原文
  Trace；
- Snapshot、索引、复杂度策略、融合、Rerank、裁剪和模型路由版本共同进入
  baseline；
- Session、Memory 和缓存尚未实现，不能作为本阶段绕过版本校验的捷径。

## Gold 与非 Gold

建立两个与 Pagila Gold 隔离的数据集：

- development：用于编写测试、调规则和调 Rerank；
- calibration holdout：只用于选择一个候选配置和冻结基线。

两者不得包含 18 条 Gold 的 question、SQL、tables、fields、join、result、
fixture、label、失败原因或可逆改写。

Pagila 18 条只在代码、依赖、模型、数据库、索引和配置全部冻结后运行。Gold
question 只作为当前 E2E user payload；其余 Gold 内容不进入 Prompt、索引、
Few-shot、RAG、训练或调参。

## Trace 与指标

Trace 新增：

- complexity level、K、reason codes、policy version；
- probe/final 候选数和同一 schema/retrieval version；
- BM25/Embedding 通道版本、数量、耗时和降级；
- RRF 配置摘要；
- Rerank 前后 rank 摘要及理由码；
- 裁剪前后表/字段数、估算 token 和预算；
- model route、实际 Provider 配置 hash、fallback 和数据边界摘要。

Trace 继续禁止 question、SQL、Prompt、表/字段原名、结果行、DSN、API key 和
原始异常。

评测聚合：

- 按 complexity 分桶的 Table/Field Recall@5/10/20、Precision 和平均候选；
- BM25、Embedding、RRF、Rerank 各阶段 recall；
- route 分布、降级率、上下文缩减率、输入/output token；
- 检索、Embedding、Rerank、生成和端到端 p50/p95；
- 安全 Case、未授权命中和真实执行证据。

## 配置

阶段 1 使用以下固定行为默认值：

```yaml
schema_linking:
  probe_top_k: 20
  simple_top_k: 5
  medium_top_k: 10
  complex_top_k: 20
  per_channel_candidates: 20
  rrf_k: 60
  index_max_entries: 32

complexity:
  policy_version: complexity-v1

embedding:
  protocol: openai_compatible
  base_url: ${EMBEDDING_BASE_URL}
  api_key: ${EMBEDDING_API_KEY}
  model: ${EMBEDDING_MODEL}
  dimension: ${EMBEDDING_DIMENSION}
  timeout_seconds: 10
  max_batch_documents: 64
  max_response_bytes: 4194304

context:
  estimator_version: utf8-bytes-v1
  input_budget_ratio: 0.8

model_routes:
  version: model-routes-v1
  simple: simple_route
  medium: standard_route
  complex: complex_route
```

具体真实 endpoint、模型名和维数从环境注入并进入配置摘要；缺失时生产启动
fail-closed。确定性单元测试使用固定 Provider，不读取开发者凭据。

## 测试设计

### 单元

- complexity-v1 所有理由、边界、重复和稳定顺序；
- 5/10/20、FK bridge、无命中、非法预算；
- Embedding 请求、响应、维数、非有限值、零向量、顺序和错误；
- index key、并发单构建、失败不发布和有界淘汰；
- cosine、双路排名、RRF 公式、去重和 tie-break；
- Rerank 理由、bridge、断开惩罚和降级；
- 字段保护、token 估算和超预算；
- model route、相同数据边界 fallback 和禁止回退。

### Workflow/集成

- 十种节点和完整边；
- 探测—路由—物化只读取一次 metadata；
- simple/medium/complex 三条真实路径；
- Schema repair 重新三步，syntax/dialect repair 不重新检索；
- Stub Embedding + 多 Provider Stub + API + Trace；
- 本地 HTTP `/embeddings` 和 `/chat/completions` 协议；
- 真实 Pagila metadata、Validator、执行与安全回归。

### 安全

- 每个检索通道、融合、Rerank、裁剪和 Trace 的未授权影响为 0；
- API 不能设置 complexity、K、模型或预算；
- 旧/错权限/错模型索引拒绝；
- Gold 不成为语料或配置输入；
- metadata/问题中的 Prompt 注入保持不可信 JSON；
- 所有 SQL 路径重新校验，安全 Case 零执行、零修复、零 fallback；
- secret、文档原文和 Provider 原始错误不进入日志/Trace。

### 非 Gold 质量门

- development 集和 calibration holdout 有独立摘要；
- holdout 冻结后不再调参；
- 组合检索的 Table/Field Recall@K 不低于冻结 BM25 基线；
- 至少一个主要召回指标高于 BM25；
- 未授权命中绝对为 0；
- 缺失任何版本或 Trace 字段的 Case 直接失败。

### 真实环境门

- 真实 Embedding 模型与维数固定并完成索引重建验证；
- 至少两个真实生成模型按不同 route 运行；
- 真实 Pagila 完成新的冻结候选；
- 18 条 Gold 的最终状态和发布资格按测试规格独立审核；
- 当前 Stage 10 的 `12/18`、`verified=0`、`not_passed` 只作为历史基线。

## 迁移

- 现有 API 请求保持兼容，不增加客户端路由字段；
- `SchemaLinkingResult` 增加实际 `top_k` 和检索版本；所有构造点显式迁移；
- Prompt 校验从固定 10 改为结果携带的实际预算；
- Workflow 图从九种到十种节点，正常序列和步骤断言更新；
- Trace/report/provider/prompt/complexity/index/fusion/rerank/context/model-route
  契约版本分别升级；
- Stage 10 code freeze 失效，真实评测前创建新 baseline；
- 不修改历史 Stage 4/8/10 设计、计划或正式报告。

## 风险与控制

| 风险 | 控制 |
|---|---|
| 向量索引泄露未授权对象 | 授权后建文档；权限摘要进入版本键；安全差分测试 |
| 探测/物化跨版本 | 同一 Snapshot 对象和版本不变量；失配 fail-closed |
| 所有问题因 fallback JOIN 被判复杂 | 只使用正分候选之间的相关路径 |
| Top-K=20 放大 Prompt | 字段级裁剪、80% 输入预算和必要字段超限终止 |
| Embedding 延迟/故障 | 10 秒上限、取消、同版本 BM25-only 降级 |
| Rerank 过拟合 | 白名单确定性特征、非 Gold development/holdout 分离 |
| 多模型边界不一致 | data-boundary ID、一致输出契约、一次受限 fallback |
| Gold 污染 | 数据集摘要、来源白名单、冻结后单次正式运行 |
| 修改后沿用旧正式报告 | code-freeze 强制新 baseline |

## 完成标准

- 阶段 1 全部能力真实可达，不存在只为未来准备的空接口；
- 三层完成状态逐项有证据；
- 授权、版本、Gold、安全和全部 SQL 重新校验边界通过；
- 错误、超时、取消和降级测试通过；
- 配置、Trace、指标、迁移和文档与代码一致；
- 当前可运行的单元、安全、集成、compileall、依赖和 diff 验证通过；
- 真实服务缺失时明确保持 `real_environment_validated=false`；
- 独立审查无 blocking/high；
- 只在 `main` 上形成阶段聚焦提交，推送前核对 origin；
- `docs/Text-to-SQL原项目参考信息.md` 不进入提交。
