# ADR 0004：确定性授权内 Schema Linking

## 状态

已验证，2026-07-28。

## 决策

第四开发阶段采用纯 Python 的 Unicode 词法/BM25 检索和授权 FK 图，不引入
Embedding、向量数据库、RRF、Rerank 或新的生产依赖。每次调用直接从第二阶段
不可变快照建立授权视图和小型内存索引，固定最多返回 10 张表。

该方案优先保证授权边界、确定性和可测试性。它不尝试从问题或 Gold Case 推断
业务词典；跨语言业务表达必须来自受信元数据中的显式 aliases 或 comments。

## 授权边界

`allowed_schemas` 和 `allowed_tables` 必须来自服务端可信授权上下文。Linker 在
分词、文档数、词频、平均文档长度、BM25、字段聚合和 FK 建图之前过滤快照：

- 表和字段只保留精确授权对象；
- PK、unique constraint/index 只有引用列仍可见时保留；
- FK 只有源表、目标表和全部引用列都可见时保留；
- 授权视图使用第二阶段规范指纹算法重新计算 `schema_version`。

因此未授权名称、字段、alias、comment、FK 和对象变化不会影响分数、证据、
路径或版本。畸形权限输入只暴露统一错误
`schema linking context is invalid`，不返回对象名。

## 分词与评分

输入和元数据文本先进行 Unicode NFKC，再做 `casefold()`。标识符保留规范完整
token，并按下划线、非字母数字边界和 camelCase 边界拆分。表文档包含表名、
表 alias/comment 以及所属字段的名称、alias/comment；字段文档包含所属表名和
字段自身证据。

BM25 固定使用 `k1=1.5`、`b=0.75` 和标准正 IDF 公式。表最终分数为表文档分数
加最高三个字段分数之和的 `0.35` 倍。正分候选按分数排序；零分但与正分候选
可达的表按最短 FK 距离排在无关零分表之前；同组使用规范对象 ID 稳定打破
平局。分数保留 12 位小数，匹配 token 去重排序。

有命中时按相同固定排名选表；无命中时，窄授权范围返回全部表，宽授权范围返回
规范名称前 10，并绕过 FK 扩展以保持 fallback 顺序。两者都不会扩大授权。
候选字段包含最终候选表的全部字段，避免漏掉投影、过滤或 JOIN 所需列。

## FK 路径

FK 图仅包含授权端点，并允许双向遍历。确定性 BFS 按邻接表名和约束名排序，
选择最短路径；返回的 `JoinEdge` 始终保留数据库定义的源/目标方向和复合列
顺序。

按排名加入候选时，如果下一张表与已选表之间需要中间表，且路径节点并集不超过
固定 `TOP_K=10`，中间表会一起加入。超出预算时不扩大候选。最终只在已选节点
子图中输出真实可达路径，不伪造 JOIN 条件。

## 版本与缓存

MVP 不缓存索引。每次调用都从传入快照重建授权视图；授权元数据语义变化会生成
新版本，未授权对象变化不会改变版本。后续 Workflow 必须保证候选结果与使用的
元数据快照版本一致。

## 验证证据

- Stage 1–4 单元测试：220 项通过；
- P0 安全测试：32 项通过；
- 真实 PostgreSQL/Pagila 集成测试：49 项通过，其中 15 项为 Stage 4；
- PG-MVP-001～014 和 PG-MVP-018 必需表字段全部召回；
- Pagila Gold JOIN 边只要存在于授权快照，就必须由返回路径覆盖；
- 固定 Top-K、未授权元数据隔离、复合 FK、中间表、不可达路径和版本变化测试
  通过；
- `compileall`、`pip check`、Docker Compose 配置、受保护文件哈希和
  diff 检查纳入阶段门禁。

Pagila 3.1.0 的 `payment` 分区父表没有 `customer_id` 物理 FK；该约束只存在于
部分月分区子表，而 MVP 授权快照只包含获授权的父表。因此 PG-MVP-011 的
`customer.customer_id = payment.customer_id` 不能作为真实 FK Path 返回。
集成测试把这一条精确记录为已知物理元数据缺口，任何其他 Gold JOIN 边缺失
仍会失败；Linker 不为通过测试伪造约束。

## 延后到第五阶段及以后

LLM 调用、结构化 SQL 生成、Prompt、Few-shot、业务 RAG、动态 Top-K、重排、
缓存、Workflow、FastAPI、Comparator 和评测 runner 不在本阶段实现。
