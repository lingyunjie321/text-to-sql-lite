# ADR 0002：PostgreSQL 授权元数据快照

## 状态

已验证，2026-07-28。

## 决策

第二开发阶段直接查询 PostgreSQL `pg_catalog`，不使用
`information_schema` 或 SQLAlchemy Inspector。

`information_schema` 无法完整提供 PostgreSQL 注释、独立 unique index
和索引定义；SQLAlchemy 既会增加依赖，仍需要 PostgreSQL 专用查询补齐这些
信息。项目已经使用 psycopg，固定目录查询是当前 MVP 最小且完整的方案。

快照只包含普通表和分区表，即 `relkind IN ('r', 'p')`。视图、物化视图、
表达式 unique index、缓存、后台刷新和多数据源注册中心不在本阶段范围内。

## 授权边界

调用方必须同时传入：

- `allowed_schemas`；
- 使用 `schema.table` 形式的 `allowed_tables`。

范围会去重并稳定排序，但不会折叠大小写。空 Schema 或表范围直接返回空快照，
不会扫描所有可见对象。所有目录 SQL 只使用固定文本和绑定的两个文本数组，
不插值标识符。

目录查询和快照组装都会应用授权过滤。外键只有源表和目标表都获授权时才返回；
未知或不可见表产生空结果，不暴露对象是否真实存在。业务别名没有批准的数据
来源，因此表和字段 `aliases` 固定为空元组，不根据命名习惯猜测。

## 系统目录与事务

每次 `read_metadata()` 在一个只读事务快照中读取：

- `pg_namespace`、`pg_class`、`pg_attribute` 和 `pg_type`；
- `pg_description` 对应的表和字段注释；
- `pg_constraint` 中的 PK、FK 和 unique constraint；
- `pg_index` 中不由 PK/unique constraint 支撑的独立 unique index。

复合键使用数组 ordinality 保留列顺序；复合外键按同一位置配对源列和目标列。
元数据读取复用第一阶段的连接池、30 秒默认 `statement_timeout`、错误归一化
和 class `08` 连接错误有限重试。错误不包含 DSN、查询参数、原始数据库消息
或未授权对象名。

## 模型与指纹

元数据使用 frozen、slotted dataclass，集合统一使用 tuple，避免下游节点修改
共享快照。快照按 Schema、表、字段序号、约束和索引名称稳定排序。

`schema_version` 的输入是除指纹自身外的完整规范快照：

- UTF-8 JSON；
- key 排序和紧凑分隔符；
- tuple 按 JSON 数组序列化；
- `None` 保留为 `null`；
- 包含标识符、类型、nullable、注释、别名、关系、索引定义和 predicate；
- 不包含数据库 OID、连接信息、查询时间或执行耗时。

对规范字节计算 SHA-256，输出 64 位小写十六进制字符串。空授权范围通过同一
算法生成固定空快照指纹。

## 验证证据

- 113 项单元测试通过；
- 16 项真实 PostgreSQL/Pagila 集成测试通过，其中 5 项为元数据测试；
- `film` 字段顺序、类型和 nullable 读取通过；
- `film_pkey` 与 `film_actor_pkey(actor_id, film_id)` 读取通过；
- `film.language_id → language.language_id` 外键读取通过；
- `idx_unq_manager_staff_id` 和
  `idx_unq_rental_rental_date_inventory_id_customer_id` 读取通过；
- 单表授权不会返回未授权 FK 端点；
- 未知表返回空快照；
- 同一授权范围连续读取的快照和 `schema_version` 一致；
- 第一阶段只读、超时、截断、错误和连接恢复回归继续通过。

## 延后到第三阶段

SQLGlot PostgreSQL 解析、单语句/只读校验、授权对象校验、函数 allowlist、
危险语句拒绝和结构化校验结果属于第三开发阶段。本阶段不宣称 SQL 安全校验
或完整 Text-to-SQL MVP 已完成。
