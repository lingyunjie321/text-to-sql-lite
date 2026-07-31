# 00 - 前端设计总览

## 1. 项目背景

Text-to-SQL Agent 是一个将自然语言问题转化为 SQL 查询并返回结果的智能应用。后端基于 FastAPI 构建，已完整实现核心接口 `POST /api/v1/text-to-sql`，能够接收自然语言问题，自动生成 SQL、执行查询、必要时自动修复，最终返回 SQL 语句与查询结果。

当前后端连接的是 **Pagila** 示例数据库（DVD 租赁业务场景），包含 13 张业务表：`actor`、`address`、`category`、`city`、`country`、`customer`、`film`、`film_actor`、`film_category`、`inventory`、`language`、`payment`、`rental`。

前端需要为这套后端构建一个用户友好的 Web 界面，让不写代码的业务人员也能用自然语言查询数据、查看结果。

## 2. 设计目标

| 目标 | 说明 |
|------|------|
| **降低使用门槛** | 业务人员无需懂 SQL，用自然语言提问即可获取数据 |
| **结果优先** | 页面视觉焦点始终在查询结果上，SQL 等技术细节折叠弱化 |
| **状态透明** | 清晰传达查询状态（成功/修复/澄清/失败），让用户知道发生了什么 |
| **快速反馈** | 加载态、骨架屏、渐进式展示，避免长时间空白等待 |
| **可恢复** | 历史记录持久化到 localStorage，刷新不丢失对话上下文 |

## 3. 目标用户画像

### 核心用户：业务/数据分析师

```
┌─────────────────────────────────────────────────────┐
│  姓名：数据分析师小李                                  │
│  背景：熟悉业务逻辑，不写代码，偶尔用 Excel 做分析       │
│  痛点：想查数据但不会 SQL，每次都要找工程师帮忙          │
│  期望：像聊天一样问问题，马上看到表格和图表              │
│  关注点：                                              │
│    ✓ 用自然语言提问                                    │
│    ✓ 看到结果表格                                      │
│    ✓ 简单可视化（柱状图/折线图）                        │
│    ✓ 能看 SQL 但不关心细节（折叠展示即可）              │
│    ✓ 能理解并回应澄清请求                              │
│    ✓ 能看到执行是否成功、失败原因（友好提示）            │
└─────────────────────────────────────────────────────┘
```

### 核心使用场景

1. **日常数据查询**："上个月租金收入最高的 10 部电影是哪些？"
2. **趋势分析**："按月统计 2007 年的租赁数量趋势"
3. **明细查看**："列出目前所有未归还的租赁记录"
4. **对比分析**："各电影分类的平均租赁时长对比"

## 4. 技术选型说明

### 4.1 技术栈

| 层级 | 选型 | 版本 | 理由 |
|------|------|------|------|
| 框架 | Next.js | 16 (latest) | App Router、RSC、内置优化、EdgeOne Makers 原生支持 |
| UI 库 | React | 19+ | Next.js 16 默认搭配，生态成熟 |
| 样式 | Tailwind CSS | 4.x | 原子化 CSS、快速迭代、与 Next.js 深度集成 |
| 图标 | lucide-react | latest | 轻量、现代、Tree-shaking 友好 |
| 图表 | Recharts | 2.x | React 原生、API 简洁、柱状图/折线图/饼图全覆盖 |
| 代码高亮 | Shiki / Prism | - | SQL 语法高亮展示 |
| 语言 | TypeScript | 5.x | 类型安全，与后端 Pydantic 模型对齐 |

### 4.2 选型理由

**为什么选 Next.js 而非纯 Vite + React？**

- **API 路由代理**：Next.js Route Handlers 可做 BFF 代理层，前端不直接暴露后端地址，也便于注入 API Key
- **EdgeOne Makers 原生支持**：EdgeOne CLI 自动检测 Next.js 项目，零配置部署
- **SSR/SSG 能力**：首页可静态预渲染，首屏加载快
- **中间件能力**：Next.js `middleware.ts` 可做请求预处理（如注入认证头）

**为什么选 Tailwind CSS？**

- 设计系统通过配置文件集中管理（颜色、间距、字号），天然支持设计规范落地
- 与 Next.js create-next-app 深度集成，零配置启动
- 响应式工具类（`sm:`/`md:`/`lg:`）直接覆盖响应式需求

**为什么选 Recharts？**

- 纯 React 组件式 API，与函数组件范式一致
- 内置响应式容器 `<ResponsiveContainer>`，图表自动适应容器宽度
- 柱状图、折线图、饼图、面积图全部支持，覆盖分析师常见需求

### 4.3 关键配置约束

```js
// next.config.ts — 必须包含以下配置
const nextConfig = {
  allowedDevOrigins: ["127.0.0.1"],  // 沙箱预览用 127.0.0.1 访问，纯 host 不带 http://
  // 注意：不要加 output: 'export'，会废掉 API 路由
};
```

> **约束说明**：Next.js 15+ 默认只信任 `localhost`，沙箱环境通过 `127.0.0.1` 预览时，不加 `allowedDevOrigins` 会导致 HMR 被拦截、hydration 失败、页面交互全部无响应。值是纯 host，不带 `http://` 前缀。

## 5. 设计原则

### 原则一：结果优先（Result-First）

页面视觉焦点始终在查询结果上。SQL 语句、元信息（request_id、trace_id）等技术细节默认折叠或弱化展示，需要时才展开。

```
视觉优先级（从高到低）：
结果表格/图表 > 状态提示 > 澄清/错误信息 > SQL（折叠）> 元信息（弱化）
```

### 原则二：克制简约（Restrained Simplicity）

- 配色克制：以中性色为主，语义色仅用于状态传达
- 留白充足：内容区不拥挤，呼吸感强
- 阴影柔和：不使用强阴影，保持扁平质感
- 圆角适中：统一使用 `rounded-lg`（8px）为主圆角

### 原则三：信息分层（Progressive Disclosure）

- 第一层：状态卡片（成功/失败/澄清）— 一眼看到结果
- 第二层：结果表格 + 可视化 — 核心数据
- 第三层：SQL 折叠区 — 点击展开查看
- 第四层：元信息折叠区 — request_id / trace_id / attempts 等

### 原则四：状态透明（Status Transparency）

后端返回 10 种 status，前端需为每种状态提供清晰的视觉反馈和友好文案，让用户始终知道"发生了什么"以及"接下来可以做什么"。

### 原则五：渐进式加载（Progressive Loading）

- 提交后立即显示加载骨架屏，不等待空白
- 加载过程中展示进度提示（"正在理解你的问题..."）
- 响应到达后渐进式渲染各区块

## 6. 后端 API 契约摘要

前端对接的唯一业务接口：

```
POST /api/v1/text-to-sql
```

### 请求体 QueryRequest

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `question` | string | 是 | - | 自然语言问题，去首尾空白后 1-2000 字符 |
| `datasource_id` | string | 否 | `"pagila"` | 数据源 ID，生产环境只接受 pagila |
| `schemas` | string[] | 否 | `[]` | 缩小授权 Schema 范围，不能扩大权限 |
| `debug` | boolean | 否 | `false` | 调试模式，当前固定身份无 debug 权限 |

### 响应体 QueryResponse

| 字段 | 类型 | 说明 |
|------|------|------|
| `request_id` | string | 请求唯一标识 |
| `trace_id` | string | 链路追踪标识 |
| `status` | enum | 终态状态（见下表） |
| `sql` | string \| null | 生成的 SQL，成功时有值 |
| `columns` | `[{name, type_oid}]` | 列定义 |
| `rows` | `[[JsonValue]]` | 数据行，二维数组 |
| `returned_row_count` | int | 返回行数（0-1000） |
| `truncated` | boolean | 是否被截断（实际超过 1000 行） |
| `attempts` | int | 总尝试次数（0-4） |
| `repair_count` | int | 修复次数（0-3） |
| `clarification` | `{code, question}` \| null | 澄清请求 |
| `error` | `{error_type, code, message}` \| null | 错误信息 |

### Status 枚举与 HTTP 状态码

| status | HTTP | 含义 | 前端处理 |
|--------|------|------|----------|
| `SUCCEEDED_FIRST_PASS` | 200 | 一次通过 | 展示结果 + 绿色状态 |
| `SUCCEEDED_REPAIRED` | 200 | 修复后通过 | 展示结果 + 弱化提示"经修复成功" |
| `CLARIFICATION_REQUIRED` | 200 | 需要澄清 | 展示澄清问题，等待用户补充 |
| `REJECTED_SECURITY` | 200/403 | 安全拒绝 | 红色错误，不可重试 |
| `FAILED_DUPLICATE_LOOP` | 200 | 重复 SQL 循环 | 红色错误，建议改写问题 |
| `FAILED_TIMEOUT` | 200 | 超时 | 橙色错误，可重试 |
| `FAILED_CONNECTION` | 200 | 连接错误 | 橙色错误，可重试 |
| `FAILED_RESOURCE_RISK` | 200 | 资源风险 | 橙色错误，建议缩小范围 |
| `FAILED_REPAIR_EXHAUSTED` | 200 | 修复耗尽 | 红色错误，建议改写问题 |
| `FAILED_INTERNAL` | 200/500 | 内部错误 | 红色错误，可重试 |

> **注意**：业务成功、澄清和业务失败通常都以 HTTP 200 返回，由响应内的 `status` 字段区分。前端不应依赖 HTTP 状态码判断业务结果，而应解析 `status` 字段。403（未授权 debug）和 500（未处理异常）是例外。

### ErrorType 枚举

`error.error_type` 的可能值：`SYNTAX_ERROR`、`SCHEMA_ERROR`、`DIALECT_ERROR`、`BUSINESS_KNOWLEDGE_MISSING`、`AMBIGUOUS_SEMANTICS`、`PERMISSION_DENIED`、`CONNECTION_ERROR`、`TIMEOUT`、`RESOURCE_RISK`、`DUPLICATE_SQL`、`UNKNOWN`

## 7. 文档导航索引

| 文档 | 内容 | 面向角色 |
|------|------|----------|
| [00-overview.md](./00-overview.md) | 项目背景、设计目标、技术选型、设计原则 | 全员 |
| [01-page-structure.md](./01-page-structure.md) | 页面结构树、导航关系、路由设计 | 前端开发 |
| [02-page-layouts.md](./02-page-layouts.md) | 各页面布局详述、线框图、交互元素、状态处理 | 前端开发 |
| [03-visual-style.md](./03-visual-style.md) | 配色、字体、间距、圆角、阴影、组件规范 | 前端开发 + 设计 |
| [04-responsive-design.md](./04-responsive-design.md) | 断点定义、桌面/平板/移动端布局策略 | 前端开发 |
| [05-interaction-flows.md](./05-interaction-flows.md) | 主查询流程、澄清、修复、可视化切换等状态机 | 前端开发 |
