# 本地动态数据源阶段 3 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将阶段 2 的 DatasourceProfile 接入可测试、可发现 metadata、可复用且严格受 allowlist 限制的 PostgreSQL/MySQL 动态运行时。

**Architecture:** `DatasourceRuntimeService` 负责临时连接、catalog 发现和 allowlist 在线校验；metadata 使用独立临时原始 Connector，以便 allowlist 漂移后仍能重新发现结构。`RuntimeRegistry` 只为查询懒加载并缓存原始 Connector 与仅供 Workflow 使用的 `ProfileScopedConnector` Context。受限 Connector 允许既有权限节点选择 Profile 内的非空 Schema 子集，但绝不允许扩大到 Profile 外。Profile Resolver 保留静态精确匹配兼容，其他 Profile 只能进入动态 Registry，任何失败都不得回退默认资源。

**Tech Stack:** Python 3.12、FastAPI 0.139.2、Pydantic 2、sqlite3、psycopg 3、PyMySQL 1.2.0、SQLGlot 30.13.0、pytest 9.1.1、Docker Compose、MySQL 8.4、Sakila。

## Global Constraints

- 只在 `main` 工作；不创建 worktree、额外分支或 PR。
- 保留并排除用户的 `AGENTS.md` 修改。
- 不修改 Workflow 图、节点、State、三次修复和 32 步限制。
- 不修改 Schema Linking 算法、Comparator、Gold 或 PostgreSQL/Pagila 安全行为。
- 不实现动态模型、Embedding 可选化、前端闭环、凭据持久化或 StarRocks 动态 Profile。
- 每个生产行为先写会失败的测试，再写最小实现。
- 所有公开错误、日志和 Trace 不包含 Host、用户名、密码、API Key、DSN、原始 SQL 或驱动错误。
- metadata 超时 30 秒，最多 500 个表/视图、10,000 个字段、5,000 个外键。
- metadata 发现范围不等于 Workflow allowlist；二者不得共享宽松回退。

---

### Task 1: Catalog 发现与 Workflow 授权包装

**Files:**
- Create: `app/connectors/catalog.py`
- Create: `app/connectors/scoped.py`
- Modify: `app/connectors/__init__.py`
- Test: `tests/unit/test_connector_catalog.py`
- Test: `tests/unit/test_profile_scoped_connector.py`
- Test: `tests/security/test_dynamic_datasource_security.py`

**Interfaces:**
- Consumes: `DatabaseConnector.execute()`、`DatabaseConnector.read_metadata()`、`DatasourceProfile.allowed_schemas/allowed_tables`。
- Produces:
  - `MetadataLimits(timeout_seconds=30.0, max_relations=500, max_columns=10000, max_foreign_keys=5000)`
  - `RelationIdentity(schema_name: str, relation_name: str, relation_kind: Literal["table", "view"])`
  - `DiscoveredMetadata(snapshot: SchemaSnapshot, relations: tuple[RelationIdentity, ...], truncated: bool)`
  - `discover_metadata(connector, *, dialect, limits) -> DiscoveredMetadata`
  - `validate_allowlist(connector, *, database_type, allowed_schemas, allowed_tables, timeout_seconds) -> SchemaSnapshot`
  - `ProfileScopedConnector(delegate, allowed_schemas, allowed_tables)`

- [ ] **Step 1: 写 catalog RED 测试**

```python
def test_postgresql_discovery_excludes_system_schemas_and_sorts_relations():
    connector = CatalogConnectorFake(rows=(
        ("public", "z_view", "VIEW"),
        ("pg_catalog", "pg_class", "BASE TABLE"),
        ("public", "actor", "BASE TABLE"),
    ))

    result = discover_metadata(
        connector,
        dialect="postgres",
        limits=MetadataLimits(),
    )

    assert result.relations == (
        RelationIdentity("public", "actor", "table"),
        RelationIdentity("public", "z_view", "view"),
    )
```

分别增加 MySQL 系统 Schema、501 个关系、10,001 个字段、5,001 个外键、完整关系边界截断和 30 秒 timeout 参数测试。期望全部因模块不存在而失败。

- [ ] **Step 2: 运行并确认 catalog RED**

Run: `.venv/bin/python -m pytest -q tests/unit/test_connector_catalog.py`

Expected: collection/import failure，明确缺少 `app.connectors.catalog`。

- [ ] **Step 3: 写最小 catalog 实现**

```python
@dataclass(frozen=True, slots=True)
class MetadataLimits:
    timeout_seconds: float = 30.0
    max_relations: int = 500
    max_columns: int = 10_000
    max_foreign_keys: int = 5_000


def discover_metadata(
    connector: DatabaseConnector,
    *,
    dialect: str,
    limits: MetadataLimits = MetadataLimits(),
) -> DiscoveredMetadata:
    relation_rows = connector.execute(
        _catalog_sql(dialect, limits.max_relations + 1),
        timeout_seconds=limits.timeout_seconds,
    )
    # 过滤系统 Schema、排序、限定关系，再用 read_metadata 读取结构；
    # 字段在完整 relation 边界截断，外键按完整对象截断。
```

发现 SQL 必须是模块内固定常量，不能拼接客户端标识符；只允许拼接受代码常量控制的整数 LIMIT。

- [ ] **Step 4: 运行 catalog GREEN**

Run: `.venv/bin/python -m pytest -q tests/unit/test_connector_catalog.py`

Expected: PASS。

- [ ] **Step 5: 写 Scoped Connector RED 测试**

```python
def test_scoped_connector_rejects_scope_mismatch_before_delegate_read():
    delegate = MetadataConnectorFake()
    connector = ProfileScopedConnector(
        delegate=delegate,
        allowed_schemas=("public",),
        allowed_tables=("public.actor",),
    )

    with pytest.raises(DatabaseConnectorError) as captured:
        connector.read_metadata(("public",), ("public.actor", "public.staff"))

    assert captured.value.details.code == "DB_ALLOWLIST_MISMATCH"
    assert delegate.read_count == 0
```

再覆盖空范围、数据库返回关系缺失、数据库返回额外关系、执行/事务代理和异常脱敏。

- [ ] **Step 6: 运行并确认 Scoped Connector RED**

Run: `.venv/bin/python -m pytest -q tests/unit/test_profile_scoped_connector.py tests/security/test_dynamic_datasource_security.py`

Expected: 缺少 `ProfileScopedConnector`。

- [ ] **Step 7: 写最小 Scoped Connector 实现并回归**

```python
class ProfileScopedConnector:
    def __init__(self, *, delegate, allowed_schemas, allowed_tables):
        self._delegate = delegate
        self._allowed_schemas = tuple(allowed_schemas)
        self._allowed_tables = tuple(allowed_tables)

    @property
    def dialect_name(self) -> str:
        return self._delegate.dialect_name

    def read_metadata(self, allowed_schemas, allowed_tables, *, timeout_seconds=None):
        if not _is_authorized_profile_subset(
            allowed_schemas,
            allowed_tables,
            self._allowed_schemas,
            self._allowed_tables,
        ):
            raise _allowlist_mismatch()
        snapshot = self._delegate.read_metadata(
            allowed_schemas,
            allowed_tables,
            timeout_seconds=timeout_seconds,
        )
        if _snapshot_relation_ids(snapshot) != set(allowed_tables):
            raise _allowlist_mismatch()
        return snapshot
```

Run: `.venv/bin/python -m pytest -q tests/unit/test_connector_catalog.py tests/unit/test_profile_scoped_connector.py tests/security/test_dynamic_datasource_security.py`

Expected: PASS。

- [ ] **Step 8: 提交批次 1**

```bash
git add app/connectors/catalog.py app/connectors/scoped.py app/connectors/__init__.py tests/unit/test_connector_catalog.py tests/unit/test_profile_scoped_connector.py tests/security/test_dynamic_datasource_security.py
git commit -m "阶段三：建立元数据发现与授权隔离"
```

---

### Task 2: 数据源运行时服务与 RuntimeRegistry

**Files:**
- Create: `app/local/datasource_runtime.py`
- Create: `app/local/runtime_registry.py`
- Modify: `app/local/__init__.py`
- Test: `tests/unit/test_datasource_runtime.py`
- Test: `tests/unit/test_runtime_registry.py`
- Test: `tests/security/test_dynamic_datasource_security.py`

**Interfaces:**
- Consumes: `ConnectorFactory.create(DatabaseSettings)`、`WorkflowContextFactory.create(...)`、`InMemoryCredentialStore`、Task 1 catalog/scoped 接口。
- Produces:
  - `DatasourceConnectionConfig(database_type, host, port, database, username)`
  - `DatasourceRuntimeError(code, public_message, status_code)`
  - `DatasourceRuntime(profile, connector, context)`
  - `DatasourceRuntimeService.test_connection(config, password) -> DiscoveredMetadata`
  - `DatasourceRuntimeService.validate_profile(profile, password) -> SchemaSnapshot`
  - `RuntimeRegistry.get_or_create(profile) -> DatasourceRuntime`
  - `RuntimeRegistry.invalidate(profile_id) -> None`
  - `RuntimeRegistry.close_all() -> None`

- [ ] **Step 1: 写连接配置和临时资源 RED 测试**

```python
def test_temporary_connector_is_closed_when_open_fails():
    connector = ConnectorFake(open_error=RuntimeError("password=secret"))
    service = DatasourceRuntimeService(connector_factory=FactoryFake(connector))

    with pytest.raises(DatasourceRuntimeError) as captured:
        service.test_connection(connection_config(), SecretStr("secret"))

    assert connector.events == ["open", "close"]
    assert "secret" not in str(captured.value)
```

增加 PostgreSQL DSN 转义、IPv6、MySQL host 配置、凭据缺失、连接错误、metadata timeout、allowlist 精确子集和系统 Schema 拒绝测试。

- [ ] **Step 2: 运行并确认 RED**

Run: `.venv/bin/python -m pytest -q tests/unit/test_datasource_runtime.py tests/security/test_dynamic_datasource_security.py`

Expected: 缺少 `DatasourceRuntimeService`。

- [ ] **Step 3: 实现最小运行时服务**

```python
class DatasourceRuntimeService:
    def test_connection(self, config, password):
        connector = self._create_connector(config, password)
        try:
            connector.open()
            return discover_metadata(connector, dialect=connector.dialect_name)
        except DatabaseConnectorError as error:
            raise _public_runtime_error(error) from None
        finally:
            self._close_temporary(connector)

    def validate_profile(self, profile, password):
        connector = self._create_connector(
            DatasourceConnectionConfig.from_profile(profile), password
        )
        try:
            connector.open()
            return validate_allowlist(
                connector,
                database_type=profile.database_type,
                allowed_schemas=profile.allowed_schemas,
                allowed_tables=profile.allowed_tables,
                timeout_seconds=30.0,
            )
        finally:
            self._close_temporary(connector)
```

- [ ] **Step 4: 运行运行时服务 GREEN**

Run: `.venv/bin/python -m pytest -q tests/unit/test_datasource_runtime.py tests/security/test_dynamic_datasource_security.py`

Expected: PASS。

- [ ] **Step 5: 写 Registry 生命周期 RED 测试**

```python
def test_failed_open_is_closed_and_not_cached_for_next_attempt():
    first = ConnectorFake(open_error=RuntimeError("private"))
    second = ConnectorFake()
    registry = runtime_registry(connectors=[first, second])

    with pytest.raises(DatasourceRuntimeError):
        registry.get_or_create(profile())
    runtime = registry.get_or_create(profile())

    assert first.events == ["open", "close"]
    assert runtime.connector is second
```

增加并发单次创建、Context 创建失败、相同配置复用、配置不匹配重建、失效关闭、失败 close 仍移除、逆序 close_all 和多个关闭失败继续测试。

- [ ] **Step 6: 运行并确认 Registry RED**

Run: `.venv/bin/python -m pytest -q tests/unit/test_runtime_registry.py`

Expected: 缺少 `RuntimeRegistry`。

- [ ] **Step 7: 实现最小 Registry 并回归**

```python
@dataclass(frozen=True, slots=True)
class DatasourceRuntime:
    profile: DatasourceProfile
    connector: DatabaseConnector
    context: WorkflowContext


class RuntimeRegistry:
    def get_or_create(self, profile: DatasourceProfile) -> DatasourceRuntime:
        with self._lock:
            cached = self._runtimes.get(profile.id)
            if cached is not None and cached.profile == profile:
                return cached
            if cached is not None:
                self._remove_and_close(profile.id)
            runtime = self._build(profile)
            self._runtimes[profile.id] = runtime
            return runtime
```

Run: `.venv/bin/python -m pytest -q tests/unit/test_datasource_runtime.py tests/unit/test_runtime_registry.py tests/security/test_dynamic_datasource_security.py`

Expected: PASS。

- [ ] **Step 8: 提交批次 2**

```bash
git add app/local/datasource_runtime.py app/local/runtime_registry.py app/local/__init__.py tests/unit/test_datasource_runtime.py tests/unit/test_runtime_registry.py tests/security/test_dynamic_datasource_security.py
git commit -m "阶段三：实现动态数据源运行时注册表"
```

---

### Task 3: CRUD、API、Resolver 与 Bootstrap 闭环

**Files:**
- Create: `app/api/datasource_models.py`
- Modify: `app/local/datasource_service.py`
- Modify: `app/local/profile_resolver.py`
- Modify: `app/api/routes/datasources.py`
- Modify: `app/api/routes/query.py`
- Modify: `app/api/bootstrap.py`
- Modify: `app/api/routes/system.py`
- Modify: `app/config/database.py`
- Modify: `app/config/__init__.py`
- Test: `tests/unit/test_profile_services.py`
- Test: `tests/unit/test_profile_routes.py`
- Test: `tests/unit/test_profile_query.py`
- Test: `tests/unit/test_profile_resolver.py`
- Test: `tests/unit/test_bootstrap_lifecycle.py`
- Test: `tests/unit/test_config.py`

**Interfaces:**
- Consumes: Task 2 `DatasourceRuntimeService`、`RuntimeRegistry`，阶段 2 Profile Store/credentials。
- Produces: 两个新 HTTP 端点、动态 Profile 解析、可选静态数据库启动、查询方言注入。

- [ ] **Step 1: 写 CRUD 在线校验 RED 测试**

```python
def test_create_does_not_persist_profile_when_allowlist_is_invalid(tmp_path):
    store = LocalProfileStore(tmp_path / "config.db")
    runtime_service = RuntimeServiceFake(
        error=DatasourceRuntimeError(
            code="DATASOURCE_ALLOWLIST_INVALID",
            public_message="The datasource allowlist is invalid.",
            status_code=409,
        )
    )
    service = DatasourceProfileService(
        store, InMemoryCredentialStore(), runtime_service=runtime_service
    )

    with pytest.raises(DatasourceRuntimeError):
        service.create(profile(), password=SecretStr("secret"))

    assert store.get_datasource("orders") is None
```

覆盖创建缺密码、名称-only PUT、连接/allowlist/password PUT 先验证、失败保留旧状态、显式 null 清密并失效、删除先失效。

- [ ] **Step 2: 运行并确认 CRUD RED**

Run: `.venv/bin/python -m pytest -q tests/unit/test_profile_services.py`

Expected: 构造参数或行为断言失败。

- [ ] **Step 3: 最小修改 DatasourceProfileService 并 GREEN**

Run: `.venv/bin/python -m pytest -q tests/unit/test_profile_services.py tests/unit/test_credential_store.py tests/unit/test_profile_store.py`

Expected: PASS。

- [ ] **Step 4: 写新 API RED 测试**

```python
def test_metadata_response_contains_structure_without_credentials(client):
    response = client.get("/api/v1/local/datasources/orders/metadata")

    assert response.status_code == 200
    assert response.json() == {
        "datasource_id": "orders",
        "schemas": [{
            "name": "public",
            "relations": [{
                "name": "orders",
                "kind": "table",
                "columns": [{"name": "id", "data_type": "integer", "nullable": False}],
                "primary_key": ["id"],
            }],
        }],
        "foreign_keys": [],
        "truncated": False,
        "limits": {"timeout_seconds": 30, "max_relations": 500, "max_columns": 10000, "max_foreign_keys": 5000},
    }
```

覆盖 POST test、404/409/503/504、OpenAPI writeOnly、原始错误和 Secret 不回显。

- [ ] **Step 5: 运行并确认 API RED**

Run: `.venv/bin/python -m pytest -q tests/unit/test_profile_routes.py tests/security/test_profile_credentials.py`

Expected: 404 或缺少 DTO。

- [ ] **Step 6: 实现 DTO、路由和错误映射并 GREEN**

```python
class DatasourceConnectionTestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    database_type: Literal["postgresql", "mysql"]
    host: StrictStr
    port: StrictInt
    database: StrictStr
    username: StrictStr
    password: SecretStr = Field(json_schema_extra={"writeOnly": True}, repr=False)
```

Run: `.venv/bin/python -m pytest -q tests/unit/test_profile_routes.py tests/security/test_profile_credentials.py tests/security/test_dynamic_datasource_security.py`

Expected: PASS。

- [ ] **Step 7: 写 Resolver、Bootstrap 和 dialect RED 测试**

覆盖静态精确匹配、动态 Registry、动态失败不回退、无静态 DB 启动、配置接口仍有模型摘要、查询 State 使用 Connector `dialect_name`。

Run: `.venv/bin/python -m pytest -q tests/unit/test_profile_resolver.py tests/unit/test_profile_query.py tests/unit/test_bootstrap_lifecycle.py tests/unit/test_config.py tests/unit/test_api_application.py`

Expected: 动态 Profile 409、空 contexts 构造失败或 dialect 仍为 postgres。

- [ ] **Step 8: 实现 Resolver/Bootstrap 闭环并 GREEN**

```python
runtime = self._runtime_registry.get_or_create(datasource)
return runtime.context
```

查询创建 State 时只使用现有参数：

```python
initial_state = new_task_state(
    request_id=request_id,
    trace_id=trace_id,
    question=query.question,
    datasource_id=context.datasource_id,
    requested_schemas=query.schemas,
    dialect=context.connector.dialect_name,
)
```

Run: `.venv/bin/python -m pytest -q tests/unit/test_profile_resolver.py tests/unit/test_profile_query.py tests/unit/test_bootstrap_lifecycle.py tests/unit/test_config.py tests/unit/test_api_application.py tests/unit/test_profile_routes.py`

Expected: PASS。

- [ ] **Step 9: 提交批次 3**

```bash
git add app/api/datasource_models.py app/api/routes/datasources.py app/api/routes/query.py app/api/routes/system.py app/api/bootstrap.py app/config/database.py app/config/__init__.py app/local/datasource_service.py app/local/profile_resolver.py tests/unit/test_profile_services.py tests/unit/test_profile_routes.py tests/unit/test_profile_query.py tests/unit/test_profile_resolver.py tests/unit/test_bootstrap_lifecycle.py tests/unit/test_config.py tests/unit/test_api_application.py tests/security/test_profile_credentials.py tests/security/test_dynamic_datasource_security.py
git commit -m "阶段三：打通动态数据源 API 查询闭环"
```

---

### Task 4: MySQL fail-closed、metadata 与生成方言

**Files:**
- Modify: `app/connectors/mysql.py`
- Modify: `app/connectors/metadata_queries_mysql.py`
- Modify: `app/connectors/metadata_queries_mysql_family.py`
- Modify: `app/connectors/metadata_queries_starrocks.py`
- Modify: `app/generation/models.py`
- Modify: `app/generation/prompt.py`
- Create: `tests/unit/test_mysql_connector.py`
- Modify: `tests/unit/test_connector_metadata.py`
- Modify: `tests/unit/test_generation_prompt.py`
- Test: `tests/security/test_dynamic_datasource_security.py`

**Interfaces:**
- Consumes: 现有 MySQL Connector、SQLGlot 方言入口和 `GenerationContext.dialect`。
- Produces: 原子 MySQL 只读事务、多表 metadata、独立 MySQL Prompt；PostgreSQL Prompt 保持不变。

- [ ] **Step 1: 写 MySQL 只读 RED 测试**

```python
def test_read_only_start_failure_executes_no_user_sql_and_discards_connection():
    connection = MySQLConnectionFake(
        start_error=RuntimeError("driver password=secret")
    )
    connector = mysql_connector(connection)

    with pytest.raises(DatabaseConnectorError):
        connector.execute("SELECT film_id FROM film")

    assert connection.user_sql_count == 0
    assert connection.closed is True
```

覆盖 snapshot 和普通 execute、回滚失败废弃、错误脱敏。

- [ ] **Step 2: 运行并确认只读 RED**

Run: `.venv/bin/python -m pytest -q tests/unit/test_mysql_connector.py tests/security/test_dynamic_datasource_security.py`

Expected: 当前实现吞掉 READ ONLY 错误或继续执行用户 SQL。

- [ ] **Step 3: 实现 `START TRANSACTION READ ONLY` 和池废弃**

```python
def _start_mysql_read_only_transaction(conn: pymysql.Connection) -> None:
    with conn.cursor() as cursor:
        cursor.execute("START TRANSACTION READ ONLY")
```

所有设置失败直接传播；连接状态无法确认时调用 pool discard，不再 putback。

- [ ] **Step 4: 运行只读 GREEN**

Run: `.venv/bin/python -m pytest -q tests/unit/test_mysql_connector.py tests/security/test_dynamic_datasource_security.py`

Expected: PASS。

- [ ] **Step 5: 写多表 metadata 与 Prompt RED 测试**

```python
def test_mysql_metadata_uses_exact_schema_and_table_placeholder_counts():
    queries = build_metadata_queries(schema_count=1, table_count=3)
    assert queries["table_columns"].count("%s") == 4


def test_mysql_prompt_names_mysql_and_keeps_postgresql_prompt_unchanged():
    mysql_messages = build_generation_messages(mysql_context())
    postgres_messages = build_generation_messages(postgres_context())
    assert "MySQL" in mysql_messages[0].content
    assert postgres_messages[0].content == SYSTEM_PROMPT
```

覆盖表/视图区分、MySQL 通用安全函数集、MySQL prompt version 和 StarRocks 共享查询兼容。

- [ ] **Step 6: 运行并确认 RED**

Run: `.venv/bin/python -m pytest -q tests/unit/test_connector_metadata.py tests/unit/test_generation_prompt.py`

Expected: 构造签名或 MySQL context 校验失败。

- [ ] **Step 7: 实现最小 metadata/Prompt 方言支持并回归**

Run: `.venv/bin/python -m pytest -q tests/unit/test_mysql_connector.py tests/unit/test_connector_metadata.py tests/unit/test_generation_prompt.py tests/unit/test_sql_validator_functions.py tests/unit/test_profile_query.py tests/security/test_dynamic_datasource_security.py`

Expected: PASS，且未修改任何 `app/workflow/` 文件。

- [ ] **Step 8: 提交批次 4**

```bash
git add app/connectors/mysql.py app/connectors/metadata_queries_mysql.py app/connectors/metadata_queries_mysql_family.py app/connectors/metadata_queries_starrocks.py app/generation/models.py app/generation/prompt.py tests/unit/test_mysql_connector.py tests/unit/test_connector_metadata.py tests/unit/test_generation_prompt.py tests/security/test_dynamic_datasource_security.py
git commit -m "阶段三：修复 MySQL 只读与方言支持"
```

---

### Task 5: 锁定 Sakila、真实集成、文档与全量交付

**Files:**
- Create: `infrastructure/mysql/manifest.json`
- Create: `infrastructure/mysql/init/03-restrict-reader.sh`
- Create: `tools/fetch_sakila.py`
- Modify: `infrastructure/mysql/compose.yaml`
- Modify: `.gitignore`
- Modify: `.env.example`
- Modify: `tests/integration/test_mysql_contract.py`
- Create: `tests/integration/test_api_mysql_sakila.py`
- Create: `tests/unit/test_sakila_fixture.py`
- Modify: `docs/Text-to-SQL项目复现规格.md`
- Modify: `docs/Text-to-SQL测试与验收规格.md`
- Modify: `docs/current-architecture.md`
- Modify: `docs/refactor-scope.md`
- Modify: `README.md`
- Modify: `RELEASE.md`
- Modify: `evaluation/stage1_calibration_freeze.json`

**Interfaces:**
- Consumes: MySQL 官方 `sakila-db.tar.gz`、锁定 MySQL 8.4 镜像、阶段三全部运行时接口。
- Produces: 可复现 MySQL/Sakila 环境、真实 Connector/API 证据、同步文档。

- [ ] **Step 1: 写 Sakila fixture RED 测试**

```python
def test_sakila_archive_rejects_wrong_hash(tmp_path):
    archive = tmp_path / "sakila-db.tar.gz"
    archive.write_bytes(b"invalid")
    with pytest.raises(ValueError, match="Sakila archive verification failed"):
        extract_verified_archive(archive, tmp_path / "output", manifest())
```

覆盖 manifest 缺字段、路径穿越、成员 Hash、已有文件复用和临时文件清理。

- [ ] **Step 2: 运行并确认 fixture RED**

Run: `.venv/bin/python -m pytest -q tests/unit/test_sakila_fixture.py`

Expected: 缺少 `tools.fetch_sakila`。

- [ ] **Step 3: 实现锁定下载与 Compose**

下载工具只接受 manifest 中的固定 URL 和 Hash；fixture 写入
`tests/fixtures/mysql/sakila/upstream/` 并被 Git 忽略。Compose 挂载
`sakila-schema.sql`、`sakila-data.sql` 和只读授权脚本，镜像使用精确 tag 与 digest。
本机测试凭据写入 Git 忽略的 `.env.mysql.local`；命令只加载该文件，不在命令行、
文档或日志中展开密码。

Run: `.venv/bin/python -m pytest -q tests/unit/test_sakila_fixture.py`

Expected: PASS。

- [ ] **Step 4: 启动真实 MySQL/Sakila 并先跑 Connector contract**

Run:

```bash
.venv/bin/python tools/fetch_sakila.py --manifest infrastructure/mysql/manifest.json --output tests/fixtures/mysql/sakila/upstream
docker compose --env-file .env.mysql.local -f infrastructure/mysql/compose.yaml up -d --wait
.venv/bin/python -m pytest -q tests/integration/test_mysql_contract.py
```

Expected: 连接、23 个表/视图发现、字段、主键、外键、多表 metadata、NULL/Decimal、1000 行截断、timeout 和写拒绝全部 PASS。

- [ ] **Step 5: 写并运行 MySQL API E2E**

测试使用真实 MySQL/Sakila、临时 Profile Store、进程内密码和固定 LLM/Embedding 替身；请求只提交 Profile ID，最终 SQL 经 MySQL SQLGlot 校验并真实执行。

Run: `.venv/bin/python -m pytest -q tests/integration/test_api_mysql_sakila.py`

Expected: PASS，且请求/响应、日志和 Trace 不含密码或 DSN。

- [ ] **Step 6: 更新规格和文档**

主规格当前编码任务改为本地工具阶段 3；测试规格增加独立阶段 3 门禁；README 记录动态 API、Sakila 启动和当前静态模型限制；RELEASE 只记录实际完成和实际测试数字。保留历史正文并追加阶段 3 状态，不改原项目参考文档。

- [ ] **Step 7: 运行阶段三重点回归**

Run:

```bash
.venv/bin/python -m pytest -q tests/unit/test_connector_catalog.py tests/unit/test_profile_scoped_connector.py tests/unit/test_datasource_runtime.py tests/unit/test_runtime_registry.py tests/unit/test_profile_services.py tests/unit/test_profile_routes.py tests/unit/test_profile_query.py tests/unit/test_profile_resolver.py tests/unit/test_bootstrap_lifecycle.py tests/unit/test_mysql_connector.py tests/unit/test_connector_metadata.py tests/unit/test_generation_prompt.py tests/security/test_dynamic_datasource_security.py tests/security/test_profile_credentials.py
```

Expected: 全部 PASS。

- [ ] **Step 8: 运行完整验收并重绑非 Gold freeze**

依次运行 unit、security、branch coverage、Pagila 91 项、MySQL/Sakila、Python 全量、前端 Vitest 49 项、typecheck、build、lint、compileall、pip check、三套 Compose config、干净 Python 3.12 安装/import、Gold diff 和 `git diff --check`。

使用 `evaluation.code_freeze.controlled_code_sha256()` 重新生成仅包含非 Gold 校准冻结的受控代码 Hash；不得修改 `evaluation/cases/pagila_mvp.jsonl` 或 `evaluation/pagila_baseline.json`。

- [ ] **Step 9: 最终审查与提交**

确认 staged 文件不包含 `AGENTS.md`、前端业务文件、任何 Gold、正式 baseline 或
`docs/Text-to-SQL原项目参考信息.md`。

最终提交前使用 `git status --short` 和 `git diff --name-only --cached` 生成实际清单，
再逐个显式暂存阶段三文件；不得使用 `git add .`。提交说明为
`实现阶段三动态数据库连接`，验证提交内容后执行 `git push origin main`。

Expected: `origin/main` 指向阶段三最终提交，工作区只保留用户的 `AGENTS.md` 修改。
