# 第二开发阶段：PostgreSQL Schema Introspection 与版本指纹设计

## 目标

在第一阶段 PostgreSQL Connector 基础上，读取授权范围内可用于后续
Schema Linking 和 SQL 安全校验的稳定元数据快照。

本阶段完成后，项目应能：

- 通过 PostgreSQL 系统目录读取 Schema、表、字段、类型、nullable 和注释；
- 读取复合 PK、复合 FK、unique constraint 和独立 unique index；
- 严格限制在调用方传入的授权 Schema/表范围；
- 返回与 psycopg 解耦的不可变元数据模型；
- 对规范化快照计算确定性的 `schema_version` SHA-256 指纹；
- 在固定 Pagila 上通过 Connector Metadata Contract 集成测试。

## 范围

### 包含

- 元数据领域模型；
- 授权范围的规范化和参数化传递；
- `pg_catalog` 表、字段、约束、索引和注释查询；
- 一次只读事务中的一致性快照读取；
- 稳定排序、规范化序列化和版本指纹；
- 空授权范围、未知表、跨 Schema 同名表和复合键行为；
- 单元测试和真实 PostgreSQL/Pagila 集成测试；
- 第二阶段技术决策和使用说明。

### 不包含

- 词法/BM25 Schema Linking、Top-K、字段打分或 JOIN Path 搜索；
- SQLGlot AST 和 SQL 对象校验；
- LLM、Prompt、SQL 生成、Workflow 或 API；
- 元数据缓存、后台刷新、变更通知或多数据源注册中心；
- 从业务知识库或配置文件补充业务别名。

表名和字段名本身是本阶段可搜索的规范标识。主规格提到的业务别名没有
批准的数据来源，因此本阶段模型保留 `aliases` 字段但默认空元组，不根据
命名习惯猜测业务含义。后续若增加显式别名来源，必须另行设计。

## 方案选择

### 方案 A：直接查询 `pg_catalog`（采用）

使用 `pg_namespace`、`pg_class`、`pg_attribute`、`pg_type`、
`pg_constraint`、`pg_index` 和 `pg_description`。优点是可以完整读取
PostgreSQL 特有的注释、复合键、约束和索引语义，且无需增加依赖。缺点是
查询与 PostgreSQL 方言绑定；这符合 MVP 单 PostgreSQL 数据源范围。

### 方案 B：只使用 `information_schema`

标准化程度较高，但注释、独立 unique index、部分 PostgreSQL 类型细节和
索引定义不完整，需要额外查询补洞，最终反而形成两套来源，不采用。

### 方案 C：使用 SQLAlchemy Inspector

能减少部分手写 SQL，但会引入新依赖，仍需 PostgreSQL 专用查询补充注释和
索引细节。第一阶段已经直接使用 psycopg，本阶段没有引入 ORM 的必要，不采用。

## 组件设计

### 元数据模型

新增 `app/connectors/metadata.py`，定义以下不可变模型：

- `ColumnMetadata`
  - `schema_name`
  - `table_name`
  - `column_name`
  - `ordinal_position`
  - `data_type`
  - `formatted_type`
  - `nullable`
  - `comment`
  - `aliases`
- `TableMetadata`
  - `schema_name`
  - `table_name`
  - `relation_kind`
  - `comment`
  - `aliases`
  - `columns`
- `PrimaryKeyMetadata`
  - `constraint_name`
  - `schema_name`
  - `table_name`
  - 按约束顺序排列的 `columns`
- `ForeignKeyMetadata`
  - `constraint_name`
  - source schema/table/columns
  - target schema/table/columns
- `UniqueConstraintMetadata`
  - `constraint_name`
  - schema/table/columns
- `UniqueIndexMetadata`
  - `index_name`
  - schema/table/columns
  - `definition`
  - `predicate`
- `SchemaSnapshot`
  - `schemas`
  - `tables`
  - `primary_keys`
  - `foreign_keys`
  - `unique_constraints`
  - `unique_indexes`
  - `schema_version`

所有集合使用 tuple，所有模型使用 frozen dataclass，防止下游节点修改共享快照。
独立 unique index 不重复包含已经支撑 PK/unique constraint 的索引。

`data_type` 保存 PostgreSQL 内部稳定类型名，如 `int4`、`varchar`；
`formatted_type` 保存 `format_type()` 的可读表示，如
`integer`、`character varying(255)`。后续生成和校验可以按需要选择。

### 授权范围

Connector 新增：

```python
def read_metadata(
    self,
    allowed_schemas: tuple[str, ...],
    allowed_tables: tuple[str, ...],
) -> SchemaSnapshot:
    ...
```

`allowed_tables` 使用规范的 `schema.table` 字符串，不接受未限定表名。
输入先去重和排序，但不会大小写折叠；PostgreSQL 标识符按系统目录中实际名称
精确匹配。

规则：

- Schema 或表范围为空时返回空快照，不执行全库扫描；
- 每张表必须同时命中 `allowed_schemas` 和 `allowed_tables`；
- 范围通过查询参数传入，不拼接 SQL 标识符或 `IN (...)` 文本；
- 不返回未授权对象的名称、数量、约束或关系端点；
- FK 只有两端都在授权范围内时才返回，避免通过关系枚举未授权表；
- 未知或不可见对象被当作无结果，不报出对象是否真实存在。

### 系统目录查询

一次 `read_metadata()` 调用从连接池获取一个连接，开启 `READ ONLY`
事务并设置第一阶段的 `statement_timeout`。全部查询在同一事务快照内完成。

查询分为五组：

1. 表与字段：`pg_namespace`、`pg_class`、`pg_attribute`、`pg_type`；
2. PK 与 unique constraint：`pg_constraint`；
3. FK：`pg_constraint`，用成对 `unnest(conkey, confkey) WITH ORDINALITY`
   保留复合键列对应关系；
4. 独立 unique index：`pg_index`、索引 `pg_class` 和
   `pg_get_indexdef()`；
5. 注释：表使用 `obj_description()`，字段使用 `col_description()`。

仅包含普通表和分区表 `relkind IN ('r', 'p')`。视图和物化视图不进入
MVP，避免把可执行对象和底层权限语义扩展到未定义范围。

删除字段 `attisdropped` 必须过滤；系统字段 `attnum <= 0` 必须过滤。
字段顺序使用 `attnum`。约束列顺序使用数组 ordinality，不按名称重新排序。

### 快照组装

原始行先转换为模型，再按以下键稳定排序：

- 表：`(schema_name, table_name)`；
- 字段：`ordinal_position`；
- 约束和索引：`(schema_name, table_name, name)`；
- FK：source schema/table/name。

若系统目录返回的约束列指向未进入快照的字段或表，调用以
`SCHEMA_ERROR` 的公开安全异常失败，不输出残缺关系。

### `schema_version` 指纹

指纹输入是 `SchemaSnapshot` 除 `schema_version` 外的规范 JSON：

- UTF-8；
- JSON key 排序；
- 紧凑分隔符；
- tuple 转数组；
- `None` 保留为 JSON null；
- 模型和集合均使用上述稳定排序；
- 包含标识符、类型、nullable、注释、别名、约束、索引定义和 predicate；
- 不包含查询时间、数据库 OID、连接信息或执行耗时。

对规范字节计算 SHA-256，小写十六进制结果作为 `schema_version`。
相同授权快照必须得到相同指纹；任何影响后续 Linking/校验的结构或注释变化
必须改变指纹。

空授权范围返回内容为空但仍有确定性的空快照指纹。

## 错误与连接安全

- 连接、超时、权限、资源和未知错误继续使用第一阶段错误归一化；
- 系统目录 SQL 固定在源码中，授权范围只作为参数；
- `read_metadata()` 调用 `_read_metadata_once()`；只有 class `08`
  连接错误会按第一阶段配置重试整个快照读取，SQL 和授权范围保持不变，
  且不产生 SQL attempt 或修复计数；
- 事务异常后必须回滚，连接健康策略与普通查询一致；
- 错误不包含 DSN、查询参数、未授权对象名或原始数据库消息。

## 测试设计

### 单元测试

- 元数据模型不可变；
- 授权范围规范化、去重、稳定排序；
- 未限定表名、空名称和 Schema 外表被拒绝或过滤；
- 空范围不执行目录查询；
- 复合 PK/FK 列顺序保持；
- 独立 unique index 与 constraint-backed index 去重；
- 输入行顺序变化不影响 `schema_version`；
- 类型、nullable、注释、关系或索引变化会改变指纹；
- 空快照指纹固定；
- 不完整关系组装为公开安全 `SCHEMA_ERROR`。

### PostgreSQL 16 + Pagila 集成测试

- 只返回 `public` 和明确授权表；
- `film` 字段顺序、类型、nullable 和注释与锁定快照一致；
- `film.film_id` PK；
- `film.language_id → language.language_id` FK；
- `film_actor` 复合 PK；
- Pagila 已知 unique constraint/index；
- FK 任一端未授权时不返回该 FK；
- 未授权 `staff` 不出现在任何模型或公开错误；
- 同一快照连续读取的 `schema_version` 一致；
- 普通查询 Connector Contract 仍然通过。

本阶段完成后只宣称 Connector Metadata Contract 通过，不宣称 Schema Linking、
SQL 安全校验或完整 Text-to-SQL MVP 已完成。

## 完成标准

- 所有元数据模型和 `read_metadata()` 已实现；
- 授权过滤在数据库查询和组装两处成立；
- Pagila 表、字段、注释、PK、FK、unique constraint/index 读取通过；
- `schema_version` 确定性和变化敏感性测试通过；
- 第一阶段单元与集成测试继续通过；
- 没有实现 Schema Linking、SQLGlot、LLM、Workflow 或 API；
- 三份受保护规格/Case 文件未修改；
- 第二阶段实现必须在用户后续明确指令后才能开始。
