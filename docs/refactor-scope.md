# 阶段 1：代码可读性整理范围与文件级计划

> **实施状态：已实施。** 本文主体保留为实施前的可追溯计划与阶段 0 发现；其中
> 64/10 冲突、行号和“待裁决”文字是历史记录，不应覆盖以下实施结论。
>
> 前置基线：见 `docs/current-architecture.md`
>
> 原则：只整理结构和错误边界，不增加 Profile、动态连接或新业务能力

## 实施后记（2026-08-01）

### 用户裁决

1. Embedding 批量上限以当前实现、测试和冻结配置的 **10** 为准，模板、README、
   主规格与相关 Stage 1 设计/计划同步为 10；不改 Embedding 运行行为。
2. `model_overrides` 与 `datasource_override` 保留为阶段 1 过渡兼容，尚不是
   Profile ID-only 的最终接口；内联数据源连接仍未接线。
3. Comparator v3 的字符串规则为先 `rstrip()`，并将 PostgreSQL
   `text`/`varchar`/`bpchar` 归为同一字符串类型族；未修改 Comparator 或 Gold。
4. 路由按现有端点拆为 `query.py` 与 `system.py`；不创建无行为的
   `models.py`、`datasources.py` 空壳。
5. MySQL 只读事务失败的 fail-closed 行为变化未纳入本阶段，现有 P0 风险保留；
   MySQL 只能标为部分接入，StarRocks 继续标为实验。

### 四个批次结果

- 批次 1：配置拆分并保持公共导入、环境变量和 Override 契约；定向回归 132 项
  通过。
- 批次 2：工厂、Bootstrap 与资源生命周期整理；全量 unit 1042 项、security
  162 项通过。
- 批次 3：API 路由/依赖拆分及 Provider 公开摘要；主代理复验全量 unit 1053 项、
  security 162 项通过，锁定 DSN 下 Pagila API 4 项通过。
- 批次 4：补齐 PyMySQL 直接依赖、integration marker 与文档同步；干净 venv
  安装、三项 import、PyMySQL `1.2.0`、`pip check` 及 unit+security 1215 项均
  通过，目录与 `-m integration` 均收集 100 项。受控代码变化后只重新绑定非
  Gold 合成校准冻结；正式 Pagila baseline 与 Gold 均未修改。

### 阶段 1 验收结论

阶段 1 的结构整理范围已实施，未改变核心 Workflow、Gold、HTTP 公开契约或前端
业务代码。旧正式冻结因受控代码和依赖元数据已改变，不能作为当前资格证据；本次
非 Gold 校准冻结重新绑定不构成正式评测重建。新的资格需要独立重新冻结和真实
环境验证。阶段 2 的 Profile、动态 Connector、可选 Embedding 与前端闭环仍未开始。

最终实测结果：unit `1053 passed`、security `162 passed`、unit+security 分支覆盖
`83%`；锁定 Pagila integration `91 passed, 9 skipped`，Python 全量
`1306 passed, 9 skipped`。9 项 skip 与阶段 0 相同，只来自未配置真实 MySQL/
StarRocks DSN。前端 Vitest `49 passed`、typecheck 与 production build 通过；
lint 保持阶段 0 的 `15 errors / 5 warnings`，未增加。`compileall`、`pip check`、
Compose config、`git diff --check`、临时干净 venv 安装与导入均通过；干净 venv
中的 unit+security 为 `1215 passed`。integration 目录与 `-m integration` 均收集
100 项。Gold SHA-256 保持
`ef55c1f88e32934a65e0173374ac934a95b840ec1d1e0a73e5722cfb33c2afc1`，状态仍为
`16 verified / 2 draft`。

## 1. 本阶段目标

阶段 1 只解决“配置、API 和 Bootstrap 难读、难测、难交接”的问题，建立清晰调用关系：

```text
FastAPI Application
→ ApplicationBootstrap
→ ConnectorFactory / ModelProviderFactory
→ WorkflowContextFactory
→ 现有 Text-to-SQL Workflow
```

完成后，新开发者应能分别回答：

- 数据库、模型、Embedding 和本地应用配置分别在哪里定义、如何加载；
- Connector、Provider 和 WorkflowContext 分别在哪里创建；
- FastAPI application 只在哪里注册路由、管理生命周期和处理全局错误；
- 任一启动步骤失败时，已创建资源由谁关闭；
- 哪些 API 是当前兼容行为，哪些能力明确留到后续阶段。

阶段 1 不以“文件越多越好”为目标。只创建能够消除真实职责混杂、并能独立测试的模块。

## 2. 当前代码存在的问题

### P0：配置职责集中且有隐藏契约

- `app/config.py` 共 697 行，混合数据库、allowlist、鉴权、LLM、模型路由和 Embedding；
- `load_database_settings()` 重复定义；
- `datasources.json` 的允许范围通过动态 `_extra` 写入 Pydantic 对象，再由 Bootstrap 私下读取；
- Embedding 批量上限存在规格 64 与代码/测试 10 的冲突。

### P0：Bootstrap 同时做所有资源工作

- 配置加载、三种 Connector 构建、打开/注册、语义 manifest、模型路由、Embedding、索引和 Context 全部集中；
- 两处配置错误被静默吞掉；
- 模型或 Embedding 创建失败时，前面已打开的 Connector 可能没有关闭；
- 组件无法分别单元测试。

### P0：API application 职责过多

- 应用创建、lifespan、鉴权、依赖、路由、模型摘要和异常转换在同一文件；
- `_model_summary()` 读取 Provider 私有 `_settings`；
- 未预期异常对外虽然脱敏，但服务端没有足够的安全诊断记录。

### P0：安装元数据与导入路径不一致

`app/connectors/__init__.py` 无条件导入 MySQL/StarRocks，而正式依赖没有声明 PyMySQL。当前虚拟环境偶然安装了 PyMySQL 1.2.0，不能证明 README 的干净安装步骤可靠。

`[待核查]` 实施时应在临时干净环境确认项目正式支持版本与 PyMySQL 固定版本的组合，而不是仅复制当前虚拟环境状态。

### P1：宽泛异常的意图不清晰

需要区分三类情况：

1. 配置损坏或安全前置条件失败：必须明确失败，不能继续；
2. 资源清理失败：保留原始业务异常，但必须安全记录；
3. 明确设计的降级路径，如 Embedding→BM25 或 Trace sink 隔离：保留，但要有状态、warning 和测试。

阶段 1 不会机械替换所有 `except Exception`，只处理静默、泄漏或缺乏诊断的路径。

## 3. 修改范围

### 必须修改

- 把 `app/config.py` 拆为类型清晰的配置包，并保留旧公共导入兼容；
- 删除重复 loader，把允许范围改为显式字段；
- 提取最小 `ConnectorFactory`、`ModelProviderFactory`、`WorkflowContextFactory`；
- 让 `ApplicationBootstrap` 只负责按顺序协调，并统一资源清理；
- 拆分查询路由和系统只读路由，保持所有路径和响应不变；
- 为 LLM Provider 增加公开、只读、脱敏的展示属性；
- 消除配置、Bootstrap 和资源清理中的静默 `except Exception: pass`；MySQL 只读失败是否 fail closed 单独裁决；
- 修复正式依赖声明与实际 import 的不一致；
- 增加配置、工厂、生命周期和 API 契约回归测试；
- 同步当前架构与发布基线文档，不改写业务规格。

### 明确不修改

- LangGraph 节点数量、边、State、32 步限制和 3 次修复规则；
- Schema Linking、BM25、Embedding、RRF、Rerank 算法；
- Prompt、模型选择策略、SQLGlot 策略、执行二次校验；
- PostgreSQL 事务、超时、结果行数和错误分类；
- QueryRequest 字段、HTTP 路径、状态码或响应 JSON；
- 前端设置、工作台、历史或 BFF 行为；
- Profile、SQLite、RuntimeRegistry、CRUD、动态 Connector；
- Embedding 可选化；
- MySQL 方言贯穿或 StarRocks 能力扩展；
- Electron、Tauri、微服务、消息队列或新数据库。

## 4. 涉及文件与文件级修改计划

### 4.1 配置包

| 文件 | 动作 | 准备如何修改 | 收益 | 主要风险 |
|---|---|---|---|---|
| `app/config.py` | 删除并迁移 | 内容迁入 `app/config/`；最终不能同时保留同名文件和包 | 消除单文件职责热点 | 模块变包后 import 解析变化 |
| `app/config/__init__.py` | 新增 | 只 re-export 现有公共类和 loader，维持 `from app.config import ...` | 调用方无需一次性改写 | 漏导出会造成启动/测试失败 |
| `app/config/database.py` | 新增 | 放 `DatabaseSettings`、显式 datasource allowlist 配置、唯一数据库 loader 和 `datasources.json` loader | 去掉重复定义和 `_extra` | env prefix、Pydantic 校验必须完全等价 |
| `app/config/model.py` | 新增 | 放 LLM 设置、route override、路由加载与校验 | 模型配置可独立阅读和测试 | 私有 `_LLMRouteOverrideSettings` 现被 override 层导入，需兼容过渡 |
| `app/config/embedding.py` | 新增 | 放 Embedding 设置与 loader；阶段 1 保持当前“启动必需”行为 | 为阶段 4 可选化准备明确边界 | 64/10 冲突未裁决前不能改变默认值 |
| `app/config/local_app.py` | 新增 | 放鉴权和本地应用级路径/开关；不新增 Profile 配置 | 区分应用策略与模型/数据库 | 不得提前引入后续阶段字段 |

实现约束：

- 允许范围使用明确 dataclass/Pydantic 字段，不允许 `object.__setattr__` 或 `_extra`；
- `datasources.json` 不存在可视为没有额外配置，文件存在但格式错误必须返回清晰、脱敏的启动错误；
- 环境变量名、默认值和校验保持不变；
- `app.config` 的现有公共名称保持可导入，私有名称只做最短兼容并在调用方改成公共类型。

### 4.2 显式工厂和 Bootstrap

| 文件 | 动作 | 准备如何修改 | 收益 | 主要风险 |
|---|---|---|---|---|
| `app/connectors/factory.py` | 新增 | 以明确 `database_type` 分支创建 PostgreSQL/MySQL/StarRocks Connector；不打开连接、不做缓存 | Connector 创建可独立测试 | 错误类型和默认参数必须与当前一致 |
| `app/generation/factory.py` | 新增 | 从已校验的 LLM route settings 创建 Provider Registry 和路由 runtime | 模型构建从 Bootstrap 解耦 | fallback/data-boundary 校验不能丢失 |
| `app/api/context_factory.py` | 新增 | 作为装配层接收已创建 Connector、允许范围、模型 runtime、可选 retrieval runtime，构造 `WorkflowContext` | Context 组装可独立测试且核心 Workflow 不反向依赖配置 | 不得改变现有索引隔离或 data boundary |
| `app/api/bootstrap.py` | 重写为小型协调器 | 保留 `ApplicationServices`，新增简单 `ApplicationBootstrap`；按“配置→连接→模型→Embedding→Context”调用工厂；显式资源栈在 Connector 构造后、open 前即接管，任一步失败逆序关闭 | 生命周期和失败位置清晰 | 重复关闭、漏关闭、启动顺序变化 |
| `app/connectors/registry.py` | 小改 | 保持现有 API；重复 ID 明确失败，`close_all()` 不把驱动异常原文放入公开消息；不实现阶段 3 RuntimeRegistry | 避免静默覆盖和凭据泄漏 | 可能暴露现有重复 ID 配置错误 |

`ApplicationBootstrap` 不引入 DI 容器、插件注册表或抽象基类。工厂都只做一件事，优先使用普通类方法或函数。`WorkflowContextFactory` 放在 API 装配层而不是 `app/workflow/`，避免核心 Workflow 反向依赖配置、Connector 创建或索引生命周期。

资源所有权从 raw Connector 构造完成后、调用 open 前就进入显式资源栈，而不是等到 Registry 注册后才开始。`FrozenSemanticConnector` 只是非拥有包装器，关闭责任仍归 raw Connector。这样即使 open 部分失败、register 失败、重复 ID、语义 manifest 包装或 Context 创建失败，未注册资源也能被回收。

生命周期测试至少覆盖：

- 主数据源创建失败；
- Connector open 过程中部分初始化后失败；
- 第二个数据源打开失败；
- Connector open 成功后 register 失败；
- 重复 datasource ID；
- 语义 manifest 包装失败；
- LLM 配置或 Provider 创建失败；
- Embedding 创建失败；
- WorkflowContext 创建失败；
- 正常退出；
- 多个 close 中有一个失败时仍继续关闭其余资源，公开错误不含 DSN、密码或驱动原文。

### 4.3 API 路由和依赖

| 文件 | 动作 | 准备如何修改 | 收益 | 主要风险 |
|---|---|---|---|---|
| `app/api/application.py` | 缩减 | 只保留 FastAPI 创建、lifespan、路由注册和全局异常处理 | 入口可以顺序阅读 | 路由顺序、异常 handler、OpenAPI 可能变化 |
| `app/api/dependencies.py` | 新增 | 放 API Key、debug 权限和 `ApplicationServices` 获取依赖 | 鉴权边界集中 | 401/403 行为必须保持 |
| `app/api/routes/__init__.py` | 新增 | 导出本阶段 router | 明确路由入口 | 无 |
| `app/api/routes/query.py` | 新增 | 原样迁移 `POST /api/v1/text-to-sql` 的请求校验、context 解析、runner 调用和响应映射 | 查询主链从应用装配分离 | HTTP 200/400/401/403/422/500 契约回归 |
| `app/api/routes/system.py` | 新增 | 原样迁移 `GET /health` 和 `GET /api/v1/config` | 系统只读接口集中 | 配置摘要不得泄露凭据 |
| `app/api/models.py` | 保留 | 阶段 1 不改字段和 JSON Schema；必要时只调整 import | 保持外部接口 | 不能顺手删除 override |
| `app/api/overrides.py` | 小改 | 改用公开配置类型和新工厂；保持未接线数据源 override 的现有拒绝行为 | 消除私有类型依赖 | 请求级模型行为必须等价 |
| `app/api/response.py` | 保留 | 不修改响应字段或映射语义 | 控制回归面 | 当前扩展字段准确性问题继续存在，需记录 |

推荐方案有意创建 `routes/system.py`，而不是提前创建空的 `routes/models.py` 和 `routes/datasources.py`。后两者在阶段 2～4 真正有 Profile/测试/CRUD 接口时创建，能避免目标目录出现空壳；但这与用户给出的目标目录不同，必须随整体计划明确确认，不能视为已经裁决。

### 4.4 Provider 公开信息

| 文件 | 动作 | 准备如何修改 | 收益 | 主要风险 |
|---|---|---|---|---|
| `app/generation/provider.py` | 小改 | 为 `OpenAICompatibleLLMProvider` 增加 `model_id` 和 `endpoint_summary` 只读属性 | API 不再读取 `_settings` | URL 脱敏必须去掉 userinfo、query、fragment 和凭据 |
| `app/api/routes/system.py` | 使用公开属性 | 生成模型摘要；不以宽泛异常悄悄返回 unknown | 契约清晰、可测 | 对不实现摘要协议的测试 stub 需明确兼容策略 |

`endpoint_summary` 只返回经过解析和脱敏的 scheme/host/port/path 摘要，不返回 API Key、URL userinfo、query 或 fragment。

### 4.5 错误处理与安全关闭

| 文件 | 动作 | 准备如何修改 | 收益 | 主要风险 |
|---|---|---|---|---|
| `app/api/bootstrap.py` | 修改 | 配置错误显式失败；统一资源清理；日志只用错误类别和 datasource ID | 启动问题可诊断 | 错误配置会从“悄悄忽略”变成 fail closed |
| `app/api/application.py` / `routes/query.py` | 修改 | 未预期异常保留通用 500，但增加不含问题、SQL、Prompt、结果和凭据的服务端日志 | 可排障且不改变公开响应 | 日志字段必须白名单化 |
| `app/connectors/mysql.py` | 待明确批准的小改 | 清理失败安全记录；若用户明确批准独立安全修复，则设置只读事务失败改为 fail closed，不再继续执行 | 消除安全静默失败 | 属于错误路径行为变化，不能仅凭“结构重构”默认实施；真实 MySQL 兼容性仍需阶段 3 验证 |
| `app/connectors/starrocks.py` | 小改 | 清理失败安全记录；保留实验标签，不声称数据库级只读事务 | 可诊断 | 日志不得包含连接参数 |

Embedding→BM25、Trace sink 隔离、Rerank 预定义降级等已有故障隔离不在本轮机械改写；只补足缺失测试或日志证据。阶段 1 默认只消除配置、Bootstrap 和资源清理中的静默 `pass`；MySQL 只读失败改成 fail closed 需在确认时单独授权。

### 4.6 依赖、测试和文档

| 文件 | 动作 | 准备如何修改 | 收益 | 主要风险 |
|---|---|---|---|---|
| `pyproject.toml` | 修改 | 声明代码已经直接 import 的 PyMySQL 固定兼容版本；不增加其他依赖 | README 干净安装可复现 | 需重新建临时干净环境验证 |
| `pyproject.toml` | 小改 | 把 `integration` 重新描述为“跨组件集成测试，具体外部依赖由 fixture/测试说明决定”，不再等同于真实 Pagila | marker 与现有回环 HTTP、进程内、Pagila、MySQL/StarRocks混合集合一致 | 历史统计说明需同步 |
| `tests/integration/test_multi_model_workflow.py` | 小改 | 为该文件现有 Case 补 integration marker，不改测试内容 | `-m integration` 不再漏测 | 不能把 marker 结果表述为真实数据库证据 |
| `tests/integration/test_stage1_synthetic_runner.py` | 小改 | 为缺失的 freeze mismatch Case 补 integration marker，不改测试内容 | 目录和 marker 收集一致 | 不能把 synthetic Case 表述为真实环境证据 |
| `tests/unit/test_config.py` | 拆分/保留兼容测试 | 验证旧导入、env prefix、数据库校验和显式 allowlist | 防止配置迁移漂移 | 测试不能只断言内部实现 |
| `tests/unit/test_llm_config.py` | 调整 | 指向新模块并保留路由覆盖/data-boundary 契约 | 模型配置回归 | 冻结值不能被误改 |
| `tests/unit/test_embedding_provider.py` | 调整 | 保持当前默认值直到 64/10 裁决；验证独立 loader | 配置拆分有证据 | 规格冲突仍需明确决定 |
| `tests/unit/test_api_application.py` | 调整/扩充 | 路由、鉴权、lifespan、错误和 OpenAPI 契约 | 保证拆路由不改接口 | 测试应比较公开契约，不绑文件位置 |
| `tests/unit/test_request_overrides.py` | 调整 | 验证新工厂接线后模型 override 等价、并发请求局部隔离，内联数据库仍明确拒绝 | 保留兼容行为且不共享凭据 | 不得把未完成分支误写成成功测试 |
| `tests/unit/test_connector_factory.py` | 新增 | 三种类型映射、未知类型、参数透传、不自动 open | 工厂可独立验证 | 当前 PyMySQL import 问题需先解决 |
| `tests/unit/test_bootstrap.py` | 新增 | 覆盖部分创建失败和资源释放矩阵 | 证明无连接泄漏 | mock 应验证生命周期而非内部调用次数细节 |
| `tests/unit/test_api_context_factory.py` | 新增 | 验证 datasource、允许范围、模型和索引隔离 | Context 组装清晰 | 不重测整个 Workflow |
| `README.md` | 最小同步 | 更新真实端点、前端存在、当前测试基线和已知限制；不宣称 Profile/动态连接已完成 | 减少交接漂移 | 不得把目标路线写成已实现 |
| `RELEASE.md` | 最小同步 | 更新 1181/1272/82%、LICENSE 和当前本地工具闭环限制 | 发布证据准确 | 不改历史报告内容 |
| `docs/前后端接口对齐报告.md`、`docs/前后端对齐长期方案.md` | 仅加状态标记 | 在顶部标记为历史/已被本地工具方案取代，不重写历史正文 | 防止继续误用 | 保留历史可追溯性 |

## 5. 是否改变对外接口

默认方案：**不改变。**

必须保持：

- `GET /health`、`GET /api/v1/config`、`POST /api/v1/text-to-sql` 路径；
- QueryRequest 当前接受的字段，包括临时 override；
- HTTP 400/401/403/422/500 的边界；
- Workflow 业务终态通常以 HTTP 200 + `status/error` 表达；
- QueryResponse JSON 字段、默认值和空值行为；
- 现有环境变量名和 `datasources.json` 兼容读取；
- PostgreSQL/Pagila 的启动和查询行为。

MySQL 无法建立数据库级只读保障时 fail closed 是正确的安全方向，但它会改变错误路径行为，不属于默认的纯结构重构。只有用户在确认阶段 1 时单独批准该项，才纳入实施并在提交说明中单列；否则保留为阻断 MySQL“正式支持”声明的 P0 安全缺陷。

阶段 1 不删除 override，也不把普通查询改成 Profile ID；这属于阶段 2。

## 6. 数据迁移与兼容方案

阶段 1 不新增数据库表、SQLite 文件、Profile 或本地配置目录，因此没有业务数据迁移。

兼容策略：

1. `app/config.py` 迁为 `app/config/` 后，由 `app/config/__init__.py` re-export 原公共名称；
2. 所有现有环境变量名、默认值和校验先保持；
3. `datasources.json` 仍可读取，但解析为显式 allowlist 字段，不再依赖 `_extra`；
4. 请求/响应 schema 不变；
5. localStorage 暂不迁移，避免阶段 1 混入前端行为；
6. 阶段 1 会改变正式评测的受控代码摘要，旧正式 baseline/报告不能继续作为新代码资格证据；本阶段只做确定性与 Pagila 回归，不自动更新 Gold 状态；
7. 不创建分支、worktree 或 PR，按仓库单分支规则在确认和验证后处理 `main`。

阶段 2 先建立后端 Profile 和 Profile ID 查询路径，同时保留旧 override 兼容；阶段 5 再迁移设置页、Workbench 和 localStorage，并设计旧配置清理、兼容期限和 deprecation 提示。不能在阶段 1 预埋复杂迁移框架。

## 7. 风险与控制措施

| 风险 | 可能影响 | 控制措施 |
|---|---|---|
| `config.py` 变为 package | import 失败或 env 加载变化 | 兼容 re-export；逐组迁移；配置等价测试 |
| 工厂拆分改变启动顺序 | manifest、模型或索引初始化回归 | 固定当前顺序；用失败注入覆盖每个边界 |
| 资源统一关闭 | 重复 close、漏 close、次要清理错误遮盖主错误 | 幂等 close；保留首个主错误；继续关闭其余资源 |
| 路由迁移 | OpenAPI、依赖注入、状态码变化 | 快照公开 schema；逐端点契约测试 |
| Provider URL 摘要 | 泄露 userinfo/query 或破坏 stub | 白名单输出；专门的敏感信息测试 |
| PyMySQL 依赖声明 | 版本兼容或安装变化 | 固定已验证版本；临时干净 venv 安装/import 验证 |
| MySQL fail closed | 某些版本拒绝当前只读语句，查询由“继续”变为失败 | 需单独明确批准；单元测试 + 阶段 3 真实 MySQL 版本验证；未验证前不宣称正式支持 |
| 配置损坏不再静默 | 过去被忽略的错误会阻止启动 | 返回清楚、脱敏、可行动的错误；在 README 写明 |
| 规格与代码默认值冲突 | 阶段 1 无法同时满足“保持行为”和“规格 64” | 实施前由用户裁决 64/10；不静默选择 |
| 前端默认查询仍不可用 | 结构重构通过但产品仍不能闭环 | 保留为显式 P0 缺陷；不把它误报为阶段 1 完成能力 |
| 受控代码摘要改变 | 旧正式评测 baseline 自动失效 | 不修改 Gold；需要新正式候选时另走完整冻结、真实模型和审核流程 |
| 请求级 Provider 凭据被共享或缓存 | 并发请求之间泄露 API Key/endpoint | Factory 返回请求局部 Registry/Context；不写共享 Registry、不缓存配置、不记录 Secret；增加并发隔离测试 |

## 8. 测试方案

### 8.1 每个独立部分后的检查

1. 配置拆分后：配置、LLM、Embedding、override 相关 unit/security；
2. ConnectorFactory 后：factory、三类 Connector unit/contract；
3. ModelProviderFactory 后：LLM provider、routing、安全测试；
4. WorkflowContextFactory 后：context、permissions、workflow graph 测试；
5. Bootstrap 生命周期后：失败注入、资源关闭、API lifespan 测试；
6. 路由拆分后：API model/application/response/permissions 测试；
7. Evaluation/Gold：loader、Comparator、runner、status 和 Gold isolation/security，确认 JSONL 保持 16 verified / 2 draft 且内容未改；
8. 文档和依赖后：干净安装、compileall、pip check、diff check。

### 8.2 阶段完成回归

以阶段 0 基线为下限：

- unit：不少于 `1019 passed`；
- security：不少于 `162 passed`；
- unit + security 分支覆盖率不低于 82%；
- 使用锁定 Pagila 的 integration：原 91 项全部通过；
- Python 全量：原 1272 项全部通过，MySQL/StarRocks 9 个 skip 只能在缺少真实 DSN 时保留，不能增加新的无理由 skip；
- frontend Vitest 49 项、typecheck、production build 全部通过；
- lint 的 15 errors / 5 warnings 是阶段 0 已知基线，本阶段若不触碰前端，不得增加；是否单独修复需另行确认；
- `compileall`、`pip check`、Compose config、`git diff --check` 通过；
- 临时干净 venv 执行 `pip install -e '.[test]'`、`import app.main`、`import app.connectors`，并至少完成 unit/security；
- 目录式 `tests/integration` 与 `-m integration` 收集数量一致；文档明确 marker 只代表跨组件测试，不把其中 13 个进程内 Case包装成真实数据库证据；
- 在确认当前真实基线后设置不低于基线的分支覆盖门槛，或在验收记录中明确说明暂不落 CI 门槛的理由；
- 针对 URL、日志、异常和关闭错误执行敏感信息断言；
- Evaluation/Gold 回归通过，主 JSONL 内容与 `16 verified / 2 draft` 状态不变；本阶段仍不满足 18/18 verified 的正式发布门禁。

如果出现失败，先定位原因，不删除测试、不放宽安全校验、不把真实失败改成 skip。

## 9. 验收标准

阶段 1 只有同时满足以下条件才完成：

- `app/config.py` 已按职责拆分，原公共导入兼容；
- `load_database_settings()` 只有一个真实实现；
- 应用代码不再使用动态 `_extra`；
- API 不再读取 Provider 私有 `_settings`；
- Connector、Model Provider、WorkflowContext 可以分别创建和单测；
- `application.py` 只负责应用创建、路由注册、生命周期和全局异常处理；
- Bootstrap 只负责清楚的顺序协调，任一步失败都关闭此前资源；
- 配置、Bootstrap 和本轮触及的资源清理路径中不存在无状态、无日志的 `except Exception: pass`；MySQL 只读失败路径按用户单独裁决执行；
- 有意降级与资源清理错误都有明确、脱敏的状态或日志；
- 干净安装不会因缺少 PyMySQL 在 import/test collection 时失败；
- HTTP 路径、请求/响应 JSON 和 PostgreSQL/Pagila 行为不变；
- 核心 Workflow、State、校验、执行和修复代码没有结构性重写；
- 阶段 0 的 Python/前端测试基线无回归；
- README、RELEASE 和历史文档状态与真实实现一致；
- 修改文件清单、关键决策、测试结果和未完成事项均以中文记录；
- 不提前实现 Profile、RuntimeRegistry、动态连接、可选 Embedding 或前端闭环。

## 10. 实施前需要用户裁决的冲突

### 10.1 Embedding 批量上限：64 还是 10

- 主规格、README 和 `.env.example`：64；
- 当前代码、单测和冻结评测配置：10。

阶段 1 同时要求“代码服从主规格”和“不改变业务行为”，两者在这里冲突。建议在开始编码前明确：

- 若以权威规格为准，阶段 1 把代码和测试调整为 64，并把它列为显式兼容变化；
- 若以冻结行为为准，先把主规格和模板统一修正为 10，再只做结构迁移。

不能静默选择。

### 10.2 Override 是当前正式契约还是 deprecated 兼容路径

- 主规格和 README 说客户端不能指定模型或 allowlist；
- 当前后端 schema、前端 BFF 和 Workbench 已正式传输 override；
- 新本地工具目标又要求阶段 2 后普通查询只传 Profile ID。

阶段 1 建议保留现有字段和行为，避免先删后加；但需要用户确认它们只是过渡兼容路径，不代表后续 Profile API 的最终设计。默认不在阶段 1 修改 OpenAPI deprecation 标记，以免在没有迁移期限时制造半套承诺。

### 10.3 Comparator 文本尾空格规则

- 测试规格声明文本尾空格敏感；
- 当前 Comparator v3、单测和 RELEASE 采用 `rstrip()`，即忽略文本尾空格。

阶段 1 不修改 Comparator。建议将当前已冻结并有单测的 v3 行为作为现状保留，另行确认后更新测试规格；如果用户决定恢复严格比较，则应作为评测语义变更单独实施和重建 baseline，不能夹带在结构重构中。

### 10.4 路由目录：立即建空壳还是按现有端点拆分

- 用户目标目录列出 `routes/query.py/models.py/datasources.py`；
- 当前只有 query、health、config 三个真实后端端点，没有模型或数据源 CRUD；
- 推荐的最小方案是阶段 1 使用 `query.py + system.py`，阶段 2～4 有真实接口时再创建 `models.py/datasources.py`。

采用推荐方案需要用户随阶段 1 计划明确确认；若要求严格按目标目录落地，则必须先定义现有 `/api/v1/config` 应归属哪个 router，不能创建没有行为和测试的空文件充数。

### 10.5 MySQL 只读失败是否在阶段 1 fail closed

- 当前代码静默忽略设置只读事务失败，存在安全风险；
- 改为 fail closed 符合安全原则，但确实改变错误路径行为；
- 真实 MySQL 兼容性要到阶段 3 才能完整验证。

默认不把该行为变化混入纯结构重构。若用户明确批准，应把它作为阶段 1 内独立、可审查的安全修复，小步实现并单独报告；否则保留缺陷和实验状态，不宣称 MySQL 正式可用。

## 11. 阶段 1 之外的已知高优先级事项

以下事项很重要，但不应夹带在阶段 1 结构整理中：

- 修复前端默认 Pagila 请求必然携带内联 override 的问题；
- 清除 localStorage 中的密码、API Key、DSN 和完整查询结果，并设计迁移；
- Profile ID-only Query API；
- ModelProfile、DatasourceProfile、SQLite Store 和内存凭据；
- 动态 Connector 与 RuntimeRegistry；
- MySQL 方言贯穿和真实只读 E2E；
- Embedding 可选化和 BM25-only 启动；
- 设置页测试连接、CRUD、Schema 树和工作台选择器；
- 前端 lint、组件测试和浏览器 E2E；
- 根 `.next/` 生成物清理、前端死代码和重复 ignore；
- 一键启动和本地交付文档。

阶段 1 完成后必须停下，报告结果并等待下一阶段确认，不自动进入阶段 2。
