# 本地模型设置阶段 5 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把现有模型演示配置迁移为可测试、增删改查并选择当前项的真实 `ModelProfile` 设置闭环，浏览器不再持久化模型 Secret。

**Architecture:** 浏览器只调用同源 Next.js Route Handlers；BFF 固定代理到 FastAPI 的 `/api/v1/local/models`，注入应用鉴权并保留脱敏状态。前端用一个严格白名单的 Profile 客户端管理后端数据，用独立 selection 模块只持久化当前 `model_profile_id`。

**Tech Stack:** Next.js 16.2 App Router、React 19、TypeScript 5、Vitest 4、现有 Tailwind CSS 4 和 FastAPI Profile API。

## Global Constraints

- 只修改本地工具阶段 5 的模型设置切片，不修改 Workflow、State、Schema Linking、生成、校验、执行、反思、Comparator 或 Gold。
- 不新增 npm 或 Python 依赖。
- 普通 UI 只配置一个生成模型；不展示 simple、standard、complex、fallback 或新 Provider 类型。
- localStorage 只保存非敏感的当前 `model_profile_id`；API Key 不进入 localStorage、日志、Toast、URL 或查询历史。
- `AGENTS.md` 是用户现有未提交修改；任何提交都不得包含它。
- 仓库只使用 `main`，不创建分支、worktree 或 PR。
- 当前前端 lint 基线是 15 errors / 5 warnings；本计划不做无关 lint 重构，但触达文件必须无新增 lint 问题。

---

### Task 1: 同步阶段 5 规格与测试门禁

**Files:**
- Modify: `docs/Text-to-SQL项目复现规格.md`
- Modify: `docs/Text-to-SQL测试与验收规格.md`

**Interfaces:**
- Consumes: `docs/superpowers/specs/2026-08-03-local-model-settings-phase5-design.md`
- Produces: 阶段 5 当前编码入口与模型设置前端门禁，供后续任务逐项验收。

- [ ] **Step 1: 更新主规格编码入口**

把“当前编码任务”改为本地工具阶段 5，并明确本批只包含：模型 Profile 列表、保存前测试、CRUD、当前模型 ID、旧模型 localStorage Secret 清理；数据源与 Workbench Profile 查询仍是后续切片。

- [ ] **Step 2: 写入测试规格门禁**

新增“本地工具阶段 5：模型设置前端闭环门禁”，逐条写明：

```text
- 浏览器只通过 BFF 调用模型 Profile API；BFF 不接受上游 URL/Header。
- ModelProfile CRUD 和 /test 全部可达并保留脱敏 HTTP 语义。
- API Key 只存在写请求和组件瞬时状态，Profile 响应/localStorage/历史均不包含。
- 编辑时省略 Key 表示保留，null 表示清除。
- 当前选择只保存合法 model_profile_id，失效或删除后清理。
- 旧 text-to-sql-model-config 被删除且不上传。
- 普通设置 UI 不显示多路模型和 fallback。
```

- [ ] **Step 3: 验证规格没有冲突或占位内容**

Run:

```bash
rg -n "当前编码任务|本地工具阶段 5|text-to-sql-model-config|fallback" docs/Text-to-SQL项目复现规格.md docs/Text-to-SQL测试与验收规格.md
rg -n "TBD|TODO|待定" docs/Text-to-SQL项目复现规格.md docs/Text-to-SQL测试与验收规格.md
git diff --check -- docs/Text-to-SQL项目复现规格.md docs/Text-to-SQL测试与验收规格.md
```

Expected: 第一条能定位新的阶段 5 入口和门禁；第二条无新增匹配；diff check 通过。

- [ ] **Step 4: Commit**

```bash
git add docs/Text-to-SQL项目复现规格.md docs/Text-to-SQL测试与验收规格.md
git commit -m "docs: define phase 5 model settings gate"
```

### Task 2: 建立模型 Profile 浏览器契约

**Files:**
- Create: `frontend/lib/model-profiles.ts`
- Create: `frontend/lib/model-profiles.test.ts`

**Interfaces:**
- Consumes: FastAPI `ModelProfileCreate`、`ModelProfileResponse`、`ModelConnectionTestRequest` 和 `ModelConnectionTestResponse`。
- Produces: `ModelProfileResponse`、`ModelProfileFormValue`、`buildModelWriteRequest()`、`buildModelTestRequest()`、`parseModelProfileResponse()` 和五个 API 调用函数。

- [ ] **Step 1: 写请求构造与响应解析失败测试**

创建测试，至少包含以下断言：

```typescript
it("omits blank credentials while editing", () => {
  const request = buildModelWriteRequest(editValue, { mode: "edit" });
  expect(request).not.toHaveProperty("api_key");
  expect(request).not.toHaveProperty("embedding_api_key");
});

it("sends null only for explicit credential clearing", () => {
  const request = buildModelWriteRequest(
    { ...editValue, clearApiKey: true },
    { mode: "edit" },
  );
  expect(request.api_key).toBeNull();
});

it("clears the full embedding group when editing disables it", () => {
  const request = buildModelWriteRequest(
    { ...editValue, embeddingEnabled: false },
    { mode: "edit", hadEmbedding: true },
  );
  expect(request).toMatchObject({
    embedding_base_url: null,
    embedding_model: null,
    embedding_dimension: null,
    embedding_api_key: null,
  });
});

it("whitelists response fields", () => {
  const parsed = parseModelProfileResponse({ ...validResponse, api_key: "sentinel" });
  expect(parsed).toEqual(validResponse);
  expect(parsed).not.toHaveProperty("api_key");
});
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `npm test -- model-profiles.test.ts`

Expected: FAIL because `model-profiles.ts` and its exports do not exist.

- [ ] **Step 3: 实现最小严格契约**

定义以下核心类型：

```typescript
export interface ModelProfileResponse {
  id: string;
  name: string;
  provider_type: "openai_compatible";
  base_url: string;
  model_name: string;
  embedding_base_url: string | null;
  embedding_model: string | null;
  embedding_dimension: number | null;
  generation_credential_status: "configured" | "missing";
  embedding_credential_status: "configured" | "missing" | "not_applicable";
}

export interface ModelProfileWriteRequest {
  id: string;
  name: string;
  provider_type: "openai_compatible";
  base_url: string;
  model_name: string;
  embedding_base_url?: string | null;
  embedding_model?: string | null;
  embedding_dimension?: number | null;
  api_key?: string | null;
  embedding_api_key?: string | null;
}
```

`parseModelProfileResponse()` 必须逐字段验证并重建对象，不能用类型断言直接接受任意 JSON。`requestProfileApi()` 解析 `detail.code/message`，非 JSON 或非法成功响应抛出固定 `ProfileApiError`，不拼接响应正文。

- [ ] **Step 4: 实现 API 调用函数**

```typescript
export const listModelProfiles = () =>
  requestProfileApi<ModelProfileResponse[]>("/api/v1/local/models", { method: "GET" });

export const createModelProfile = (body: ModelProfileWriteRequest) =>
  requestProfileApi<ModelProfileResponse>("/api/v1/local/models", json("POST", body));

export const replaceModelProfile = (id: string, body: ModelProfileWriteRequest) =>
  requestProfileApi<ModelProfileResponse>(
    `/api/v1/local/models/${encodeURIComponent(id)}`,
    json("PUT", body),
  );
```

同时实现 delete 与 test；delete 接受 204 空响应。

- [ ] **Step 5: 运行定向测试**

Run: `npm test -- model-profiles.test.ts`

Expected: PASS，且测试中使用 sentinel Secret 证明解析结果和错误均不包含它。

- [ ] **Step 6: Commit**

```bash
git add frontend/lib/model-profiles.ts frontend/lib/model-profiles.test.ts
git commit -m "feat: add model profile client contract"
```

### Task 3: 只持久化当前模型 ID并清理旧 Secret

**Files:**
- Create: `frontend/lib/profile-selection.ts`
- Create: `frontend/lib/profile-selection.test.ts`

**Interfaces:**
- Consumes: 后端相同的 Profile ID 正则 `^[a-z0-9](?:[a-z0-9_-]{0,62}[a-z0-9])?$`。
- Produces: `getSelectedModelProfileId()`、`setSelectedModelProfileId()`、`clearSelectedModelProfileId()`、`reconcileSelectedModelProfileId()` 和 `removeLegacyModelConfig()`。

- [ ] **Step 1: 写 selection 与迁移失败测试**

```typescript
it("stores only a valid profile id", () => {
  setSelectedModelProfileId("local-model");
  expect(localStorage.getItem(SELECTED_MODEL_PROFILE_KEY)).toBe("local-model");
  expect(() => setSelectedModelProfileId("../secret")).toThrow();
});

it("clears a selection missing from the server list", () => {
  localStorage.setItem(SELECTED_MODEL_PROFILE_KEY, "gone");
  expect(reconcileSelectedModelProfileId(["kept"])).toBeNull();
  expect(localStorage.getItem(SELECTED_MODEL_PROFILE_KEY)).toBeNull();
});

it("deletes legacy model secrets without parsing them", () => {
  localStorage.setItem(LEGACY_MODEL_CONFIG_KEY, "sentinel-secret-not-json");
  removeLegacyModelConfig();
  expect(localStorage.getItem(LEGACY_MODEL_CONFIG_KEY)).toBeNull();
});
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `npm test -- profile-selection.test.ts`

Expected: FAIL because the module does not exist.

- [ ] **Step 3: 实现最小 storage 模块**

SSR 时 getter 返回 `null`，setter/clear/migration 安全 no-op。`removeLegacyModelConfig()` 只能调用 `removeItem("text-to-sql-model-config")`，不能读取或 JSON.parse 旧内容。

- [ ] **Step 4: 运行定向测试**

Run: `npm test -- profile-selection.test.ts`

Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add frontend/lib/profile-selection.ts frontend/lib/profile-selection.test.ts
git commit -m "feat: store selected model profile id"
```

### Task 4: 增加受限的 Next.js 模型 Profile BFF

**Files:**
- Create: `frontend/lib/server/backend-json.ts`
- Create: `frontend/lib/server/backend-json.test.ts`
- Create: `frontend/app/api/v1/local/models/route.ts`
- Create: `frontend/app/api/v1/local/models/test/route.ts`
- Create: `frontend/app/api/v1/local/models/[profileId]/route.ts`

**Interfaces:**
- Consumes: `TEXT_TO_SQL_API_URL`、可选 `TEXT_TO_SQL_API_KEY`、浏览器同源 JSON 请求。
- Produces: `forwardBackendJson(path, request, options)`；固定路径 Route Handlers。

- [ ] **Step 1: 写 BFF helper 失败测试**

用注入的 fake fetch 验证：

```typescript
it("injects configured auth without accepting browser headers", async () => {
  await forwardBackendJson("/api/v1/local/models", incoming, {
    method: "POST",
    backendUrl: "http://127.0.0.1:8000",
    apiKey: "server-key",
    fetchImpl,
  });
  expect(fetchImpl).toHaveBeenCalledWith(
    "http://127.0.0.1:8000/api/v1/local/models",
    expect.objectContaining({
      headers: { "Content-Type": "application/json", Authorization: "Bearer server-key" },
    }),
  );
});

it("returns a stable error for a non-json upstream response", async () => {
  const response = await forwardBackendJson("/api/v1/local/models", incoming, options);
  await expect(response.json()).resolves.toEqual({
    detail: { code: "UPSTREAM_RESPONSE_INVALID", message: "后端响应格式无效。" },
  });
});
```

还要覆盖：backend URL 缺失、请求 JSON 无效、204 DELETE、上游状态透传、fetch 抛错时不包含异常字符串。

- [ ] **Step 2: 运行测试并确认失败**

Run: `npm test -- backend-json.test.ts`

Expected: FAIL because the helper does not exist.

- [ ] **Step 3: 实现固定边界 helper**

helper 只接受由 Route Handler 源码提供的相对 `path` 和 `method`。拒绝不以 `/api/v1/local/` 开头或包含 `://` 的 path。GET 使用 `cache: "no-store"`；POST/PUT 先解析浏览器 JSON 再重新序列化；DELETE 不转发浏览器正文。

- [ ] **Step 4: 实现三个 Route Handler**

动态路由遵循 Next.js 16 签名：

```typescript
type RouteContext = { params: Promise<{ profileId: string }> };

export async function PUT(request: Request, context: RouteContext) {
  const { profileId } = await context.params;
  return forwardBackendJson(
    `/api/v1/local/models/${encodeURIComponent(profileId)}`,
    request,
    { method: "PUT" },
  );
}
```

实现 GET/POST、POST test、GET/PUT/DELETE item，不实现 PATCH、任意 catch-all 或浏览器指定上游。

- [ ] **Step 5: 运行定向测试、类型检查**

Run:

```bash
npm test -- backend-json.test.ts
npm run typecheck
```

Expected: PASS。

- [ ] **Step 6: Commit**

```bash
git add frontend/lib/server/backend-json.ts frontend/lib/server/backend-json.test.ts frontend/app/api/v1/local/models
git commit -m "feat: proxy local model profile APIs"
```

### Task 5: 实现 Profile 列表、当前选择和删除

**Files:**
- Create: `frontend/components/settings/ModelProfileSection.tsx`
- Create: `frontend/components/settings/ModelProfileList.tsx`
- Create: `frontend/components/settings/ModelProfileDeleteDialog.tsx`
- Modify: `frontend/components/settings/SettingsLayout.tsx`

**Interfaces:**
- Consumes: Task 2 Profile API、Task 3 selection/migration API、现有 `Button` 和 Toast callback。
- Produces: 加载/空/成功/错误状态，当前模型选择，编辑入口和确认删除。

- [ ] **Step 1: 实现列表展示组件**

每项只展示：Profile 名称、`model_name`、生成凭据状态、Embedding 是否配置及凭据状态。
操作为“设为当前”“编辑”“删除”。当前项显示“当前模型”，不能使用“连接成功”描述凭据状态。

- [ ] **Step 2: 实现确认删除组件**

Dialog 使用现有页面内受控展示，不新增 modal 依赖。确认按钮调用传入异步 handler；提交中禁用取消和重复确认。文案只包含 Profile 名称，不显示 endpoint。

- [ ] **Step 3: 实现 Section 数据协调**

挂载时按顺序执行：

```typescript
removeLegacyModelConfig();
const profiles = await listModelProfiles();
const selectedId = reconcileSelectedModelProfileId(profiles.map((profile) => profile.id));
```

404 删除冲突后刷新列表；删除当前项后清理 selection。列表加载失败显示固定错误卡和“重试”。不要把异常对象写入 console。

- [ ] **Step 4: 接入 SettingsLayout**

把模型 section import 替换为 `ModelProfileSection`。侧栏状态由 Section 回调的后端 Profile 数量决定，不再同步读取旧模型 localStorage。移动端和桌面端共享相同 section 实例语义，避免在同一页面同时发两次列表请求。

具体结构改为“一份 section 内容 + 两套纯导航”：桌面侧栏和移动端顶部导航都只修改
`activeSection`，实际 `{renderSection(activeSection)}` 只在共同内容容器中调用一次。移动端
不再为每个折叠项各自挂载完整 section。

- [ ] **Step 5: 验证触达文件**

Run:

```bash
npm run typecheck
npx eslint components/settings/ModelProfileSection.tsx components/settings/ModelProfileList.tsx components/settings/ModelProfileDeleteDialog.tsx components/settings/SettingsLayout.tsx
```

Expected: PASS，无新增 warning。

- [ ] **Step 6: Commit**

```bash
git add frontend/components/settings/ModelProfileSection.tsx frontend/components/settings/ModelProfileList.tsx frontend/components/settings/ModelProfileDeleteDialog.tsx frontend/components/settings/SettingsLayout.tsx
git commit -m "feat: list and select model profiles"
```

### Task 6: 实现模型 Profile 表单、测试和保存

**Files:**
- Create: `frontend/components/settings/ModelProfileForm.tsx`
- Modify: `frontend/components/settings/ModelProfileSection.tsx`
- Modify: `frontend/components/settings/PasswordInput.tsx`

**Interfaces:**
- Consumes: `ModelProfileFormValue` 和 Task 2 的 write/test builders；`createModelProfile()`、`replaceModelProfile()`、`testModelConnection()`。
- Produces: 创建与编辑表单、可选 Embedding 区、临时测试状态、显式凭据清除语义。

- [ ] **Step 1: 扩展 PasswordInput 的浏览器语义**

新增可选 `autoComplete`，默认仍为 `"off"`；模型 Key 表单显式传 `"new-password"`。不把输入值复制到 DOM 属性、aria-label 或错误文案。

- [ ] **Step 2: 实现基础表单与校验**

Profile ID 仅创建时可编辑；编辑时只读。`provider_type` 固定为 `openai_compatible`。
校验 exact ID regex、name/model 非空、URL 可解析；HTTP endpoint 的最终 loopback 规则仍交给后端，前端只显示后端稳定错误。

- [ ] **Step 3: 实现可选 Embedding**

默认折叠。开启后要求 base URL、model、1～1,000,000 整数 dimension；关闭已有 Embedding 时显示“保存后会清除 Embedding 配置和凭据”。

- [ ] **Step 4: 实现编辑凭据动作**

编辑态空 Key 显示“留空则保留当前凭据”。“清除已保存凭据”是显式 checkbox/button，并在输入新 Key 时自动取消 clear 标记。不得从响应构造假的掩码 Key。

- [ ] **Step 5: 实现测试状态**

测试按钮只使用当前表单值。编辑态不得暗中复用已保存 Key；需要鉴权的 endpoint 若
Key 留空，在按钮附近提示用户重新输入测试 Key，无鉴权 loopback 允许留空。结果映射：

```text
connected + not_configured → 生成模型可用，BM25-only 可用
connected + connected → 生成模型与 Embedding 均可用
connected + unavailable → 生成模型可用，Embedding 当前不可用
ProfileApiError → 使用稳定 message，允许重试
```

任何字段改变后把先前测试状态重置为“未测试”，避免陈旧成功状态。

- [ ] **Step 6: 实现创建/替换保存**

保存成功后调用 `onSaved(profile)` 并关闭表单；失败保留用户输入，页面只显示脱敏错误。
测试不是保存前置条件。按钮提交中禁用，防止重复请求。

- [ ] **Step 7: 验证触达文件**

Run:

```bash
npm test -- model-profiles.test.ts
npm run typecheck
npx eslint components/settings/ModelProfileForm.tsx components/settings/ModelProfileSection.tsx components/settings/PasswordInput.tsx
```

Expected: PASS。

- [ ] **Step 8: Commit**

```bash
git add frontend/components/settings/ModelProfileForm.tsx frontend/components/settings/ModelProfileSection.tsx frontend/components/settings/PasswordInput.tsx
git commit -m "feat: manage and test model profiles"
```

### Task 7: 移除旧模型 Secret 与 deprecated Override 前端路径

**Files:**
- Delete: `frontend/components/settings/ModelConfigSection.tsx`
- Delete: `frontend/components/settings/ToggleSwitch.tsx`
- Delete: `frontend/lib/model-config.ts`
- Delete: `frontend/lib/model-config.test.ts`
- Modify: `frontend/components/workbench/Workbench.tsx`
- Modify: `frontend/components/settings/AboutSection.tsx`
- Modify: `frontend/lib/types.ts`

**Interfaces:**
- Consumes: 新 Profile 设置已完全替换旧模型配置。
- Produces: 浏览器不再读取、写入或查询时发送模型 API Key；关于页准确描述存储边界。

- [ ] **Step 1: 写旧路径不存在的回归检查**

Run before deletion:

```bash
rg -n "getModelConfig|setModelConfig|StoredModelConfig|ModelTier|model_overrides|text-to-sql-model-config" frontend --glob '!package-lock.json'
```

Expected: 能定位旧设置、Workbench、类型和测试引用。

- [ ] **Step 2: 删除旧模块与组件**

删除四模型 localStorage 模块、测试、卡片和仅由它使用的 ToggleSwitch。

- [ ] **Step 3: 从 Workbench 删除模型 Override**

删除 `getModelConfig()`、`isModelConfigured()`、`ModelEndpointOverride` 和
`model_overrides` 构造；本批仍保留 datasource override，直到数据源阶段 5 切片。

- [ ] **Step 4: 修正 AboutSection**

不再声称模型配置和 API Key 存在 localStorage；说明模型 Profile 保存在本地后端，
Key 只在当前后端进程内存，浏览器只保存当前 Profile ID。现有“清除所有配置”在本批
只清理前端选择和旧数据源演示配置，不删除后端 Profile，并把按钮文案改成“清除浏览器偏好”。

- [ ] **Step 5: 清理旧类型**

从 `types.ts` 删除 `ModelEndpoint`、`ModelTier`、`StoredModelConfig`。deprecated 后端
`ModelEndpointOverride` 类型和 sanitizer 暂时保留给旧 BFF 请求兼容测试，但
Workbench 不再产生它。

- [ ] **Step 6: 验证 Secret 路径已消失**

Run:

```bash
rg -n "getModelConfig|setModelConfig|StoredModelConfig|ModelTier" frontend --glob '!package-lock.json'
rg -n "model_overrides" frontend/components frontend/app --glob '*.ts' --glob '*.tsx'
npm test
npm run typecheck
```

Expected: 前两条无匹配；测试和类型检查通过。

- [ ] **Step 7: Commit**

```bash
git add frontend
git commit -m "refactor: remove browser model credentials"
```

### Task 8: 完整验证与阶段记录

**Files:**
- Modify only if required by observed failures: files touched in Tasks 1～7
- Modify: `docs/Text-to-SQL测试与验收规格.md` only to record evidence if the repository uses inline status records

**Interfaces:**
- Consumes: Tasks 1～7 完整实现。
- Produces: 可复现的测试、类型、lint、生产构建和安全扫描证据。

- [ ] **Step 1: 运行前端测试与类型检查**

Run:

```bash
cd frontend
npm test
npm run typecheck
```

Expected: 全部 PASS，测试数不少于基线 49，且新增 Profile、selection、BFF 测试均被执行。

- [ ] **Step 2: 运行本批 lint 和全量 lint**

Run:

```bash
npx eslint app/api/v1/local/models lib/model-profiles.ts lib/model-profiles.test.ts lib/profile-selection.ts lib/profile-selection.test.ts lib/server/backend-json.ts lib/server/backend-json.test.ts components/settings/ModelProfileSection.tsx components/settings/ModelProfileList.tsx components/settings/ModelProfileDeleteDialog.tsx components/settings/ModelProfileForm.tsx components/settings/PasswordInput.tsx components/settings/SettingsLayout.tsx components/settings/AboutSection.tsx
npm run lint
```

Expected: 第一条 PASS；第二条不得比基线 15 errors / 5 warnings 更差。既有未触达 lint 错误单独记录，不顺手重构。

- [ ] **Step 3: 运行生产构建**

Run: `npm run build`

Expected: PASS。若受限沙箱再次因 Turbopack 内部端口权限失败，在批准的非沙箱构建中复验，不能把该权限错误当成代码失败或跳过构建。

- [ ] **Step 4: 运行 Secret 与旧路径扫描**

Run:

```bash
rg -n "text-to-sql-model-config|api_key.*localStorage|localStorage.*api_key|getModelConfig|setModelConfig" frontend --glob '!*.test.ts' --glob '!package-lock.json'
rg -n "simple|standard|complex|fallback" frontend/components/settings --glob '*.tsx'
git diff --check
git status --short
```

Expected: 第一、二条在运行时代码无匹配；diff check 通过；status 只包含本任务文件和用户原有 `AGENTS.md` 修改。

- [ ] **Step 5: 检查提交边界**

```bash
git status --short
git log -8 --oneline
```

Expected: Tasks 1～7 的实现分别已有提交，工作区只剩用户原有的 `AGENTS.md` 修改。
如验证发现失败，回到引入失败的 Task 修正、重跑该 Task 验证并使用该 Task 已列明的文件
创建 `test: verify phase 5 model settings` 提交；绝不暂存 `AGENTS.md`。

- [ ] **Step 6: 推送 main**

```bash
git remote get-url origin
git push origin main
```

Expected: origin 是 `https://github.com/lingyunjie321/text-to-sql-lite.git`，推送成功。
