# 本地模型设置阶段 5 设计

## 1. 目标与边界

本批次把现有模型设置页从“浏览器 localStorage 保存四路模型覆写”迁移为真实的
`ModelProfile` 管理界面。用户可以在 `/settings` 中完成模型测试、创建、查看、修改、
删除和当前模型选择；API Key 只在表单提交时经过 Next.js BFF 发送到 FastAPI，并由
后端现有的进程内 Credential Store 管理。

本批次是本地工具阶段 5 的第一个纵向切片，只处理模型设置。数据源 Profile、Schema
树和 Workbench 的 Profile-ID 查询分别留给后续两个切片。这里可以保存“当前选中的
`model_profile_id`”，但 Workbench 暂不读取它。

不修改 LangGraph、Workflow State、Schema Linking、生成路由、SQL 校验、执行、
反思、Comparator、Gold Case 或后端 Profile 语义；不新增依赖，不增加多模型高级
路由 UI，不新增 Provider 类型，也不持久化 Secret。

## 2. 规格冲突处理

主规格的 MVP 编码入口仍标记“本地工具阶段 4”，测试规格也没有独立的本地工具阶段
5 门禁；`AGENTS.md` 和主规格的本地工具阶段表已经要求进入阶段 5。实现前先做两项
规格同步：

1. 把主规格编码入口切换为阶段 5，并明确首批是模型 Profile 设置闭环。
2. 在测试规格中新增阶段 5 前端门禁，覆盖 Profile API、Secret、选择状态和旧配置
   迁移；不改动原有阶段 2～4 门禁。

## 3. 方案选择

采用现有设置页内的纵向替换：保留 `/settings`、整体导航和视觉变量，增加小型
Profile API 客户端与 Next.js Route Handlers，将四模型卡片替换为“Profile 列表 +
单模型表单”。

不采用浏览器直连 FastAPI，因为这会引入 CORS、后端地址暴露和浏览器鉴权配置；不先
建立通用 CRUD 框架，因为模型与数据源表单、测试结果和生命周期差异尚未经过前端
验证。Next.js 16.2 Route Handlers 原生支持本批需要的 GET、POST、PUT 和 DELETE，
动态路由参数在 handler 中异步读取，且 Route Handlers 默认不缓存，因此无需新增
框架或缓存配置。

## 4. 前端边界与文件职责

### 4.1 BFF 路由

新增同路径代理：

```text
GET/POST  /api/v1/local/models
POST      /api/v1/local/models/test
GET/PUT/DELETE /api/v1/local/models/{profile_id}
```

Route Handler 只负责：

- 检查 `TEXT_TO_SQL_API_URL`；
- 读取并转发 JSON；
- 使用现有 `TEXT_TO_SQL_API_KEY` 注入后端 Bearer Header；
- 保留后端 HTTP 状态与已脱敏 JSON；
- 将无效 JSON、非 JSON 响应和网络失败转换为稳定的前端错误结构。

动态 `profile_id` 必须用 `encodeURIComponent` 构造上游路径。浏览器不能传入任意上游
URL、Header 或方法。GET 列表显式使用 `cache: "no-store"`，即使当前 Route Handler
默认不缓存，也让 Profile 列表的实时语义清晰可见。

### 4.2 类型和 API 客户端

`frontend/lib/model-profiles.ts` 只包含模型 Profile 的浏览器契约与调用函数：

```text
ModelProfile
ModelProfileResponse
ModelProfileWriteRequest
ModelConnectionTestRequest
ModelConnectionTestResponse
ProfileApiError

listModelProfiles()
createModelProfile()
replaceModelProfile()
deleteModelProfile()
testModelConnection()
parseModelProfileResponse()
```

类型与现有 Pydantic 模型逐字段对齐：一个 `openai_compatible` 生成模型，加一组可选的
Embedding endpoint、model、dimension。客户端不定义 simple、standard、complex 或
fallback，也不接收后端未声明的字段。

API Key 和 Embedding API Key 只存在于写请求类型，绝不出现在响应类型、Profile
列表、选择状态、错误对象或查询历史中。响应先经过字段白名单解析；未知字段被丢弃，
缺少必需字段则作为响应格式错误处理，不能直接把任意上游对象写入 React 状态。

### 4.3 当前选择

`frontend/lib/profile-selection.ts` 只管理允许写入 localStorage 的两个非敏感 ID。
本批实现模型 ID：

```text
key: text-to-sql-selected-model-profile-id
value: 经过 Profile ID 基础格式检查的字符串
```

“设为当前模型”只更新这个 ID，不修改后端 Profile。删除当前 Profile 后同步清除该
ID。页面加载时如果本地 ID 已不存在于后端列表，也立即清除；不自动猜选第一个
Profile，避免用户无意识切换模型。

### 4.4 设置组件

保留 `SettingsLayout`，把 `ModelConfigSection` 替换为以下清晰职责：

- `ModelProfileSection`：加载、空态、选中 Profile、打开创建/编辑表单和协调提示；
- `ModelProfileList`：展示名称、模型名、生成凭据状态、Embedding 状态和当前选择；
- `ModelProfileForm`：创建/编辑字段、测试状态、保存和取消；
- `ModelProfileDeleteDialog`：确认删除，避免误操作。

首屏显示 Profile 列表和“添加模型”。列表项可执行“设为当前”“编辑”“删除”。普通
用户只看到一个生成模型配置；Embedding 放在默认折叠的“可选增强”区域。现有四路
模型卡片、启用开关和 fallback 入口全部移除。

## 5. 表单与凭据语义

### 5.1 创建

创建表单字段：

```text
id
name
provider_type = openai_compatible（固定，不提供可变选择）
base_url
model_name
api_key（可空，支持无鉴权 loopback 服务）
embedding_enabled
embedding_base_url
embedding_model
embedding_dimension
embedding_api_key（可空）
```

Embedding 开启后，地址、模型和维数全部必填；创建时关闭 Embedding 就省略整组字段，
不能形成半配置。前端只提供即时友好校验，后端仍是最终校验边界。

### 5.2 编辑

编辑时响应不会返回 Secret。生成 Key 和 Embedding Key 输入框默认空白，并明确标注
“留空则保留当前凭据”。只有用户实际输入 Key 时才在 PUT 中包含对应字段。

如需清除凭据，用户必须点击独立的“清除已保存凭据”动作；该动作把对应字段显式设为
`null`。这与后端“字段省略=保留，显式 null=清除”的语义一致，避免空输入误删
凭据。修改 endpoint、模型或 Embedding 身份字段时，后端已有规则可能清除旧 Secret；
表单在保存前给出需要重新输入 Key 的提示，但不复制或恢复旧 Key。

编辑已有 Profile 时关闭 Embedding，PUT 必须同时把 `embedding_base_url`、
`embedding_model`、`embedding_dimension` 和 `embedding_api_key` 设为 `null`，既清除
非敏感配置也清除进程内 Embedding Key；不能只隐藏表单而保留后台配置。

### 5.3 测试和保存

“测试连接”使用当前表单值调用 `/test`，不要求 Profile 已保存。测试状态只保存在
React 页面状态中：`未测试 / 测试中 / 生成连接成功 / Embedding 不可用 / 失败`。

生成成功、Embedding 未配置时显示“生成模型可用，当前使用 BM25-only”；生成成功但
Embedding 不可用时显示降级提示，仍允许保存；生成测试失败时显示后端稳定错误文案。
保存不强制依赖一次测试成功，避免临时网络故障阻止用户保存配置，但界面明确标注未
测试状态。

列表刷新后只展示“凭据已配置/缺失”和“Embedding 未配置/凭据状态”，不把凭据状态
冒充实时连接状态。

## 6. 数据流

```text
浏览器设置页
  → 同源 Next.js /api/v1/local/models...
  → Next.js 注入本地应用鉴权并限制上游路径
  → FastAPI ModelProfileService / ModelRuntimeService
  → SQLite 非敏感 Profile + 进程内 Credential Store
  → 脱敏 Profile/测试响应
  → 设置页刷新列表与临时测试状态
```

创建成功后刷新列表并保持表单关闭；编辑成功后用响应替换列表项；删除成功后移除列表
项并清理失效选择。所有写操作期间禁用对应按钮，避免重复提交。不同 Profile 的操作
互不锁死整个页面。

## 7. 旧 localStorage 迁移

旧键 `text-to-sql-model-config` 含 API Key，违反阶段 5 安全边界。新页面首次加载时
无条件删除该键，不把其中内容导入 Profile，也不把旧 Key 自动发送到后端。用户需要
重新创建 Profile 并重新输入 Key。

移除旧 `model-config.ts` 及其测试，并从 `Workbench`、`SettingsLayout` 和“关于”页的
清理逻辑中删除旧模型配置依赖。数据源旧键在第二个阶段 5 切片处理；本批不改变它。

## 8. 错误与安全

- 422 显示字段校验失败，不显示 Pydantic 输入、URL、Key 或原始响应。
- 404 在编辑/删除期间出现时刷新列表并提示 Profile 已不存在。
- 409 显示 ID 冲突或不可变 ID 提示。
- 503/504 显示服务不可用或测试超时，可由用户重试。
- BFF 无法解析上游响应时返回固定消息，不拼接异常文本。
- 客户端日志、Toast、React key、URL 查询参数和 localStorage 都不得包含 Secret。
- Profile 响应只信任后端声明字段；未知字段不进入状态或持久化。
- 旧 localStorage Secret 删除后不可由应用恢复，设置页会明确提示用户重新配置。

## 9. 测试与验收

新增前端测试覆盖：

1. Profile 响应和写请求构造不混入 Secret 或未知字段；
2. 编辑时省略空白 Key、显式清除时发送 `null`；
3. Embedding 三字段全有或全无；
4. 当前模型 ID 的保存、读取、非法值拒绝、失效清理和删除联动；
5. 旧 `text-to-sql-model-config` 在迁移时被删除且不被解析或上传；
6. BFF 支持列表、创建、测试、替换和删除，并透传后端状态；
7. BFF 的后端未配置、无效 JSON、非 JSON 上游和网络失败均返回稳定脱敏错误；
8. 现有查询请求测试保持通过，本批不让 Workbench 发送 Profile ID。

本批验收命令：

```text
npm test
npm run typecheck
npm run lint
npm run build
```

当前 lint 基线已有 15 个错误和 5 个警告。实现只修复本批触达文件中的问题；完整历史
lint 清理不作为模型设置切片的隐含重构。验收时必须证明本批没有新增 lint 问题，并
单独记录仍存在的既有问题。生产构建在受限沙箱中可能因 Turbopack 绑定内部端口失败，
需要在允许该行为的环境中复验。

## 10. 完成定义

满足以下条件后，本批模型设置闭环完成：

- 用户可通过界面测试、创建、查看、修改和删除 `ModelProfile`；
- 用户可明确选择当前模型，localStorage 只保存 Profile ID；
- 普通设置页不再展示多路模型或 fallback；
- 浏览器不再保存或读取模型 API Key；
- 旧模型 localStorage Secret 被清理且不会自动上传；
- 后端 Profile 和测试 API 契约保持不变；
- 前端测试、类型检查和生产构建通过，本批不新增 lint 回归；
- 主规格、测试规格和实现状态一致。
