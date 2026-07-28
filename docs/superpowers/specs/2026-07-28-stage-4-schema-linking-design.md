# 第四开发阶段：确定性 Schema Linking 设计

## 目标

在第二阶段不可变元数据快照和第三阶段授权校验基础上，实现固定
Top-K=10 的本地 Schema Linking。输入是规范化问题、服务端授权范围和快照，
输出是候选表、候选字段、FK JOIN Path 与授权视图的 `schema_version`。

本阶段完成后，项目应能：

- 在授权对象上执行确定性词法/BM25 检索；
- 从表名、字段名、注释和显式 aliases 产生匹配证据；
- 把字段命中聚合到表；
- 用授权 FK 图补充必要中间表和 JOIN Path；
- 最多返回 10 张表，并提供这些表的完整字段上下文；
- 对空授权范围、无词法命中、同名字段和 Schema 版本变化稳定处理；
- 在 Pagila Gold Case 的授权范围内召回全部必需表和字段。

## 范围

### 包含

- 纯 Python Unicode/identifier 分词；
- 表文档和字段文档；
- 标准 BM25 评分；
- 字段分数向表分数聚合；
- 固定 Top-K=10；
- 授权前置过滤；
- 无命中时的窄授权 fallback；
- 授权 FK 图的确定性最短路径；
- 不可变候选和 JOIN Path 模型；
- 单元、权限安全和真实 Pagila 元数据集成测试；
- Stage 4 ADR、README 和持续执行台账。

### 不包含

- Embedding、向量数据库、RRF、Rerank；
- 动态 Top-K、复杂度路由和查询改写；
- Few-shot、业务 RAG、指标知识库或 Gold Case 泄漏；
- LLM、Prompt、SQL 生成和反思；
- 缓存、持久化索引或后台刷新；
- 多数据源、多方言或跨数据源 JOIN；
- LangGraph、FastAPI、Trace sink 和 Comparator。

## 方案比较

### 方案 A：本地 BM25 + FK 图（采用）

对授权快照建立小型内存文档，使用确定性 BM25 评分，字段分数聚合到表，再用
FK 图补必要中间表。无需新增依赖，结果可复现、可测试，并覆盖主规格要求。

### 方案 B：substring/前缀排序

实现更短，但对字段、注释、重复词和噪声表区分不足，无法稳定表达“字段命中
聚合到表”。不采用。

### 方案 C：Embedding + Rerank

跨语言召回更强，但需要模型或向量依赖，并属于主规格明确暂不实现的范围。
不采用。

## 公共接口

新增 `app/schema_linking/`：

```text
app/schema_linking/
├── __init__.py
├── models.py
└── linker.py
```

公共函数：

```python
def link_schema(
    question: str,
    *,
    allowed_schemas: tuple[str, ...],
    allowed_tables: tuple[str, ...],
    snapshot: SchemaSnapshot,
) -> SchemaLinkingResult:
    ...
```

结果模型使用 frozen/slotted dataclass：

```python
class CandidateTable:
    object_id: str
    schema_name: str
    table_name: str
    relation_kind: str
    comment: str | None
    score: float
    matched_tokens: tuple[str, ...]


class CandidateField:
    object_id: str
    schema_name: str
    table_name: str
    column_name: str
    formatted_type: str
    nullable: bool
    comment: str | None
    score: float
    matched_tokens: tuple[str, ...]


class JoinEdge:
    constraint_name: str
    source_table: str
    source_columns: tuple[str, ...]
    target_table: str
    target_columns: tuple[str, ...]


class JoinPath:
    tables: tuple[str, ...]
    edges: tuple[JoinEdge, ...]


class SchemaLinkingResult:
    candidate_tables: tuple[CandidateTable, ...]
    candidate_fields: tuple[CandidateField, ...]
    join_paths: tuple[JoinPath, ...]
    schema_version: str
```

对象 ID 使用规范 `schema.table` 和 `schema.table.column`。结果集合去重、顺序
稳定，不携带驱动对象或可变 SQLGlot AST。

## 授权视图

调用方的 `allowed_schemas` 和 `allowed_tables` 先经过第二阶段
`normalize_metadata_scope()`。索引构建前只保留授权表：

- 表、字段、PK、unique constraint/index 只保留授权端点；
- FK 只有源表和目标表都授权时保留；
- 未授权对象不进入词频、文档数、平均文档长度、评分或匹配证据；
- 返回的 `schema_version` 对过滤后的授权快照重新计算，未授权对象变化不会
  形成旁路信号。

非法授权格式抛出公开安全的 `ValueError("schema linking context is invalid")`，
不包含对象名。空授权范围返回固定空快照版本和空候选。

## 分词和文档

文本先做 Unicode NFKC 和 `casefold()`。标识符按下划线、非字母数字边界和
camelCase 边界拆分，同时保留规范完整 token。中文连续文本作为 Unicode token
保留，显式中文 alias/comment 可直接命中。

表文档包含：

- Schema 与表名 token；
- 表 aliases 和注释；
- 所有字段名、字段 aliases 和字段注释。

字段文档包含：

- 所属表名；
- 字段名；
- 字段 aliases 和注释。

名称和 aliases 重复加入文档以形成稳定权重，注释只加入一次。不会从 Gold SQL、
Gold tables/fields、问题标签或命名习惯推断业务 aliases。

## BM25 和表聚合

表文档和字段文档分别计算标准 BM25：

```text
idf(t) = log(1 + (N - df(t) + 0.5) / (df(t) + 0.5))
score = Σ idf(t) * tf*(k1+1) / (tf + k1*(1-b+b*dl/avgdl))
```

固定 `k1=1.5`、`b=0.75`。表最终分数为表文档分数加最高三个字段分数之和的
`0.35` 倍。只使用问题中实际出现的 token；匹配 token 去重排序后作为证据。

排序键：

1. 正 BM25 分数候选优先，并按分数降序；
2. 零分但与任一正分候选 FK 可达的表按最短关系距离升序；
3. 其余零分表；
4. 同组使用 `schema_name`、`table_name` 稳定打破平局。

浮点分数只用于内存排序和 Trace 证据，不作为安全决策。

## Top-K 与无命中

`TOP_K=10` 是代码常量，不开放调用方参数，也不根据问题动态变化。

- 有正分候选时按排名选择，并在预算内补 FK 中间表；
- 没有正分且授权可见表不超过 10 时，返回全部授权表，分数为 0；
- 没有正分且授权表超过 10 时，按规范名称稳定返回前 10；
- 没有正分时不执行 FK 扩展，避免关系图改变明确的 fallback 顺序；
- 任何路径扩展后候选总数仍不得超过 10。

窄授权 fallback 不扩大权限。它允许上游权限已经把范围压缩到少量表时，为生成
节点提供完整可用 Schema；若权限范围很大且问题无法匹配，后续 Workflow 可按
候选质量决定澄清。

候选字段返回最终候选表的全部字段，字段按表排名、字段 BM25 分数降序和字段名
排序。Top-K 约束只作用于表；字段不使用动态截断，避免漏掉 select/filter/join
所需字段。

## FK 图与 JOIN Path

图节点是授权 `schema.table`，边来自授权快照 FK。遍历双向进行，但 `JoinEdge`
保留数据库定义的源/目标方向和复合列顺序。

按表排名增量构建候选：

1. 选择最高排名表；
2. 对下一候选寻找通向已选表的最短路径；
3. 路径新增节点与候选总数不超过 10 时一并加入；
4. 超预算时跳过路径扩展，继续稳定填充剩余高分表；
5. 对最终候选中的可达表对输出确定性最短 JOIN Path。

最短路径按路径长度、表名序列和约束名序列稳定打破平局。无 FK 路径不伪造
JOIN 条件。

## Schema 版本

每次调用都从传入快照构建授权视图和内存索引，不实现缓存。因此新快照必然产生
新索引；授权视图语义变化时，第二阶段指纹算法产生新的 `schema_version`。
旧结果携带旧版本，后续节点不得与新快照混用。

## 测试设计

### 单元

- 直接表名、字段名、comment 和 aliases 命中；
- 字段命中聚合到正确表；
- 同名字段依靠表证据稳定排序；
- FK 中间表和复合 JOIN edge；
- 无路径不伪造；
- 无命中窄授权 fallback；
- 超过 10 张表固定截断；
- Schema 变化产生新版本；
- 所有模型不可变且顺序稳定。

### 安全

- 未授权表、字段、aliases、comment 不影响任何评分；
- 未授权 FK 端点不进入路径；
- 未授权对象变化不改变授权结果版本；
- 空权限不扫描或返回对象；
- Top-K 不可由调用方扩大。

### Pagila 集成

使用每条 Case 的 `allowed_tables` 读取真实授权快照，不把 `gold_tables` 或
`gold_fields` 送入 linker。PG-MVP-001～014 和 PG-MVP-018 必须召回 Case
所需表和字段；每个候选均在授权范围，候选表不超过 10，JOIN Path 只使用授权
FK。

## 完成标准

- 无新增生产依赖；
- 固定 Top-K=10；
- 未授权对象命中数为 0；
- 表、字段、注释和 aliases 检索可测试；
- 字段命中正确聚合到表；
- FK 中间表和 JOIN Path 稳定；
- Pagila 允许 Case 表/字段召回通过；
- Stage 1–3 回归、安全和真实集成继续通过；
- 三份受保护规格与 Gold Case 未修改；
- 未实现任何 Stage 5+ 功能。
