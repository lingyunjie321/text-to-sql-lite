# 07 - 设置页面设计

> 本文档设计「设置」页面（`/settings`），包含**模型配置**（轻量/标准/高强度模型 + fallback）和**数据库连接配置**（数据源类型 + 连接参数 + 授权配置）两大功能模块。配置持久化到 localStorage，演示用，不涉及服务端持久化。

---

## 1. 设计目标与背景

### 1.1 现状

当前后端配置完全通过 `.env` 管理：

- 模型路由：`LLM_SIMPLE_*` / `STANDARD_*` / `COMPLEX_*` 环境变量
- 数据库：固定 Pagila + 13 张表，DSN 通过 `.env` 配置
- 后端明确「API 不接受 SQL、表 allowlist、复杂度、Top-K、模型、Prompt 或超时参数」

用户无法在前端调整模型或切换数据源。

### 1.2 增强目标

| 功能 | 用户价值 |
|------|----------|
| 模型配置 | 用户可自行配置轻量/标准/高强度模型的 base_url、api_key、model_name，适配不同 LLM 服务商 |
| 数据库连接配置 | 用户可配置连接自己的 PostgreSQL/MySQL/StarRocks 数据库，不再局限于 Pagila |
| Fallback 模型 | 主模型不可用时自动降级，提升容错能力 |
| 测试连接 | 配置后可一键验证连通性，避免配置错误导致查询失败 |

### 1.3 关键约束

> ⚠️ **需要后端扩展**：当前后端不接受 `model_config` 请求字段，也不支持动态数据源注册。前端配置存 localStorage 后，查询时通过请求头/请求体传给后端，**需要后端扩展才能生效**。在后端未扩展前，配置仅做前端存储和 UI 展示，不影响现有 Pagila 查询。

> ⚠️ **安全提示**：API Key 和数据库密码存储在 localStorage 中，存在 XSS 窃取风险。此方案仅适用于演示/开发环境，生产环境应使用后端加密存储或密钥管理服务。详见第 8 节安全提示。

> ⚠️ **后端架构约束**：当前后端「模型路由通过 .env 配置、数据库固定 Pagila」。支持前端动态配置模型和数据源属于架构性变更，需后端重构配置加载逻辑。

---

## 2. 设置页面整体布局

### 2.1 桌面端布局（≥ 1024px）

采用**左侧分类菜单 + 右侧配置表单**的经典设置页布局：

```
┌─────────────────────────────────────────────────────────────────────┐
│  TopNav  [Logo] Text-to-SQL    工作台 历史 帮助 设置 关于   [GitHub]  │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌──────────────┐  ┌──────────────────────────────────────────────┐ │
│  │              │  │                                              │ │
│  │  设置         │  │  模型配置                                     │ │
│  │              │  │  配置 Text-to-SQL Agent 使用的 LLM 模型        │ │
│  │ ▸ 模型配置    │  │                                              │ │
│  │   数据库配置   │  │  ┌──────────────────────────────────────┐   │ │
│  │   关于        │  │  │  轻量模型 (Simple)              [启用] │   │ │
│  │              │  │  │  适用于简单查询                         │   │ │
│  │              │  │  │  Base URL    [https://...]              │   │ │
│  │              │  │  │  API Key     [••••••••]          [👁]   │   │ │
│  │              │  │  │  Model Name  [gpt-4o-mini]              │   │ │
│  │              │  │  │                          [测试连接]      │   │ │
│  │              │  │  └──────────────────────────────────────┘   │ │
│  │              │  │                                              │ │
│  │              │  │  ┌──────────────────────────────────────┐   │ │
│  │              │  │  │  标准模型 (Standard)            [启用] │   │ │
│  │              │  │  │  ...                                   │   │ │
│  │              │  │  └──────────────────────────────────────┘   │ │
│  │              │  │                                              │ │
│  │              │  │  ┌──────────────────────────────────────┐   │ │
│  │              │  │  │  高强度模型 (Complex)           [启用] │   │ │
│  │              │  │  │  ...                                   │   │ │
│  │              │  └──────────────────────────────────────────────┘ │
│  │              │                                                   │
│  │              │  ┌──────────────────────────────────────────────┐ │
│  │              │  │  Fallback 模型（可选）                        │ │
│  │              │  │  ...                                         │ │
│  │              │  └──────────────────────────────────────────────┘ │
│  │              │                                                   │
│  │              │                          [重置默认]  [保存配置]     │
│  └──────────────┘                                                   │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### 2.2 平板端布局（768px - 1023px）

左侧菜单收窄为图标 + 文字，右侧表单占满剩余宽度：

```
┌─────────────────────────────────────────────────────────────┐
│  TopNav                                                      │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌────────┐  ┌──────────────────────────────────────────┐   │
│  │ 设置    │  │  模型配置                                 │   │
│  │        │  │  ...                                     │   │
│  │ ▸ 模型  │  │                                          │   │
│  │   数据库│  │                                          │   │
│  │   关于  │  │                                          │   │
│  └────────┘  └──────────────────────────────────────────┘   │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 2.3 移动端布局（< 768px）

改为**手风琴折叠布局**，每个分类为一个可展开的折叠面板：

```
┌─────────────────────────────────────┐
│  [Logo] Text-to-SQL          [☰]    │
├─────────────────────────────────────┤
│                                     │
│  设置                                │
│                                     │
│  ┌─────────────────────────────┐    │
│  │ ▾ 模型配置            [已配置]│    │  ← 默认展开第一个
│  ├─────────────────────────────┤    │
│  │ 轻量模型 (Simple)     [启用] │    │
│  │ Base URL  [https://...]      │    │
│  │ API Key   [••••••]     [👁]  │    │
│  │ Model     [gpt-4o-mini]      │    │
│  │             [测试连接]        │    │
│  │                              │    │
│  │ 标准模型 (Standard)   [启用] │    │
│  │ ...                          │    │
│  │                              │    │
│  │ 高强度模型 (Complex)  [启用] │    │
│  │ ...                          │    │
│  │                              │    │
│  │ Fallback 模型（可选）         │    │
│  │ ...                          │    │
│  │                              │    │
│  │        [重置默认] [保存配置]  │    │
│  └─────────────────────────────┘    │
│  ┌─────────────────────────────┐    │
│  │ ▸ 数据库配置          [未配置]│    │  ← 折叠
│  └─────────────────────────────┘    │
│  ┌─────────────────────────────┐    │
│  │ ▸ 关于                      │    │  ← 折叠
│  └─────────────────────────────┘    │
│                                     │
├─────────────────────────────────────┤
│  [台] [史] [助] [设] [于]            │  ← 底部 Tab（5 项）
└─────────────────────────────────────┘
```

### 2.4 左侧菜单项

| 菜单项 | 图标 | 说明 |
|--------|------|------|
| 模型配置 | `Cpu` | LLM 模型配置（轻量/标准/高强度 + fallback） |
| 数据库配置 | `Database` | 数据源连接配置 |
| 关于 | `Info` | 应用版本、配置存储说明、安全提示 |

### 2.5 样式规范

| 元素 | 样式 |
|------|------|
| 左侧菜单容器 | `w-56 shrink-0 border-r border-[var(--color-border)] bg-white`（桌面）|
| 菜单项 | `flex items-center gap-2 px-4 py-3 text-sm cursor-pointer transition-colors duration-150` |
| 菜单项激活 | `text-[var(--color-primary)] bg-[var(--color-primary-light)] border-l-2 border-[var(--color-primary)]` |
| 菜单项未激活 | `text-[var(--color-text-secondary)] hover:bg-[var(--color-bg-subtle)]` |
| 右侧表单区 | `flex-1 p-6 lg:p-8` |
| 表单区标题 | `text-xl font-semibold text-[var(--color-text-primary)]` |
| 表单区描述 | `text-sm text-[var(--color-text-tertiary)] mt-1` |

---

## 3. 模型配置区域设计

### 3.1 三种模型配置卡片

每种模型一个独立卡片，包含 `base_url`、`api_key`、`model_name` 三个字段 + 启用开关 + 测试连接按钮。

```
┌──────────────────────────────────────────────────────────────┐
│  模型配置                                                     │
│  配置 Text-to-SQL Agent 使用的 LLM 模型                        │
│                                                              │
│  ┌────────────────────────────────────────────────────────┐  │
│  │  ⚡ 轻量模型 (Simple)                        [启用 ●─]  │  │  ← 卡片标题 + 启用开关
│  │  适用于简单查询，快速响应                                │  │  ← 描述
│  │  ─────────────────────────────────────────────────────  │  │
│  │  Base URL                                               │  │
│  │  ┌──────────────────────────────────────────────────┐   │  │
│  │  │ https://api.openai.com/v1                        │   │  │
│  │  └──────────────────────────────────────────────────┘   │  │
│  │                                                        │  │
│  │  API Key                                               │  │
│  │  ┌──────────────────────────────────────┐  ┌────┐      │  │
│  │  │ •••••••••••••••••••••••••••••••••••  │  │ 👁 │      │  │  ← password + 眼睛切换
│  │  └──────────────────────────────────────┘  └────┘      │  │
│  │                                                        │  │
│  │  Model Name                                             │  │
│  │  ┌──────────────────────────────────────────────────┐   │  │
│  │  │ gpt-4o-mini                                      │   │  │
│  │  └──────────────────────────────────────────────────┘   │  │
│  │                                                        │  │
│  │                                       [⚡ 测试连接]      │  │
│  └────────────────────────────────────────────────────────┘  │
│                                                              │
│  ┌────────────────────────────────────────────────────────┐  │
│  │  📊 标准模型 (Standard)                      [启用 ●─]  │  │
│  │  适用于常规查询，平衡速度与质量                           │  │
│  │  ─────────────────────────────────────────────────────  │  │
│  │  Base URL        [https://api.openai.com/v1]            │  │
│  │  API Key         [••••••••]                    [👁]     │  │
│  │  Model Name      [gpt-4o]                               │  │
│  │                                       [⚡ 测试连接]      │  │
│  └────────────────────────────────────────────────────────┘  │
│                                                              │
│  ┌────────────────────────────────────────────────────────┐  │
│  │  🔥 高强度模型 (Complex)                     [启用 ●─]  │  │
│  │  适用于复杂查询，最强推理能力                             │  │
│  │  ─────────────────────────────────────────────────────  │  │
│  │  Base URL        [https://api.openai.com/v1]            │  │
│  │  API Key         [••••••••]                    [👁]     │  │
│  │  Model Name      [o1-preview]                           │  │
│  │                                       [⚡ 测试连接]      │  │
│  └────────────────────────────────────────────────────────┘  │
│                                                              │
│  ┌────────────────────────────────────────────────────────┐  │
│  │  🛟 Fallback 模型（可选）                     [启用 ─○]  │  │  ← 默认禁用
│  │  主模型不可用时自动降级使用                               │  │
│  │  ─────────────────────────────────────────────────────  │  │
│  │  Base URL        [https://api.openai.com/v1]            │  │
│  │  API Key         [••••••••]                    [👁]     │  │
│  │  Model Name      [gpt-4o-mini]                          │  │
│  │                                       [⚡ 测试连接]      │  │
│  └────────────────────────────────────────────────────────┘  │
│                                                              │
│                                    [↺ 重置默认]  [💾 保存配置] │
└──────────────────────────────────────────────────────────────┘
```

### 3.2 模型卡片字段说明

| 字段 | 类型 | 必填 | 校验 | 说明 |
|------|------|------|------|------|
| `enabled` | boolean | 是 | - | 是否启用该模型 |
| `base_url` | string | 是（启用时） | URL 格式校验 | LLM API 基础地址 |
| `api_key` | string | 是（启用时） | 非空 | API 密钥，password 类型 |
| `model_name` | string | 是（启用时） | 非空 | 模型名称 |

### 3.3 模型卡片样式

| 元素 | 样式 |
|------|------|
| 卡片容器 | `rounded-lg border border-[var(--color-border)] bg-white p-5 shadow-sm` |
| 卡片标题 | `flex items-center justify-between` |
| 模型图标 | 24px，不同模型不同图标（见 3.4） |
| 模型名称 | `text-base font-semibold text-[var(--color-text-primary)]` |
| 启用开关 | Toggle Switch，启用态 `bg-[var(--color-primary)]` |
| 卡片描述 | `text-sm text-[var(--color-text-tertiary)] mt-1` |
| 分隔线 | `border-t border-[var(--color-border)] my-4` |
| 字段标签 | `text-sm font-medium text-[var(--color-text-secondary)] mb-1.5` |
| 输入框 | 沿用 [03-visual-style.md](./03-visual-style.md) 输入框规范，`h-10 rounded-md` |
| API Key 输入框 | `flex` 布局，输入框 `flex-1` + 眼睛按钮 `w-10` |
| 测试连接按钮 | Secondary 按钮，`h-9 px-3 text-sm`，靠右 |
| 卡片间距 | `space-y-4` |
| 禁用卡片 | `opacity-60`，输入框 `disabled` |

### 3.4 模型图标

| 模型 | 图标 | 颜色 |
|------|------|------|
| 轻量模型 (Simple) | `Zap` | `text-[var(--color-success)]` |
| 标准模型 (Standard) | `Activity` | `text-[var(--color-info)]` |
| 高强度模型 (Complex) | `Flame` | `text-orange-600` |
| Fallback 模型 | `LifeBuoy` | `text-[var(--color-text-tertiary)]` |

### 3.5 启用开关（Toggle Switch）

```
启用态:  ●──────   ← bg-primary，圆点在右侧
禁用态:  ─────○    ← bg-gray-300，圆点在左侧
```

- 尺寸：宽 40px，高 22px，圆点 18px
- 启用：`bg-[var(--color-primary)]`，圆点 `translate-x-4`
- 禁用：`bg-gray-300`，圆点 `translate-x-0.5`
- 过渡：`transition-colors duration-200`
- 点击区域：整个开关可点击

### 3.6 API Key 掩码切换

```
默认掩码:  [•••••••••••••••]  [👁]   ← password 类型
点击眼睛:  [sk-xxxxxxxxxxxx]  [👁️]  ← text 类型，图标变为闭眼
```

- 输入框 `type` 在 `password` / `text` 间切换
- 眼睛图标：`Eye`（掩码态）↔ `EyeOff`（可见态）
- 图标按钮：`flex items-center justify-center w-10 h-10 text-[var(--color-text-tertiary)] hover:text-[var(--color-text-primary)]`

### 3.7 测试连接按钮

```
默认:     [⚡ 测试连接]           ← Secondary 按钮
测试中:   [◌ 测试中...]          ← Spinner + 禁用
成功:     [✓ 连接成功]           ← 绿色，2 秒后恢复
失败:     [✕ 连接失败]           ← 红色，显示错误提示
```

> ⚠️ **需要后端扩展**：测试连接功能需要后端新增 `POST /api/v1/models/test` 接口。在后端未实现前，点击测试连接显示提示「此功能需要后端支持，暂不可用」。

### 3.8 底部操作按钮

```
                                    [↺ 重置默认]  [💾 保存配置]
```

| 按钮 | 变体 | 说明 |
|------|------|------|
| 重置默认 | Secondary | 清空当前配置，恢复为默认值（不保存，需再点保存） |
| 保存配置 | Primary | 将配置写入 localStorage，显示 Toast「配置已保存」 |

- 按钮区：`flex justify-end gap-3 mt-6`
- 有未保存更改时，保存按钮高亮提示（可选：标题栏显示「未保存」标记）

---

## 4. 数据库连接配置区域设计

### 4.1 整体布局

```
┌──────────────────────────────────────────────────────────────┐
│  数据库配置                                                   │
│  配置 Text-to-SQL Agent 连接的数据库                           │
│                                                              │
│  数据源类型                                                   │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐            │
│  │ ● PostgreSQL │ │ ○ MySQL     │ │ ○ StarRocks │            │  ← 单选卡片
│  └─────────────┘ └─────────────┘ └─────────────┘            │
│                                                              │
│  连接配置                                       [高级模式 ▸]  │  ← DSN 切换
│  ┌────────────────────────────────────────────────────────┐  │
│  │  主机地址 (Host)        端口 (Port)                     │  │
│  │  ┌──────────────────┐  ┌──────────────┐                │  │
│  │  │ localhost        │  │ 5432         │                │  │
│  │  └──────────────────┘  └──────────────┘                │  │
│  │                                                        │  │
│  │  数据库名 (Database)                                    │  │
│  │  ┌──────────────────────────────────────────────────┐   │  │
│  │  │ pagila                                            │   │  │
│  │  └──────────────────────────────────────────────────┘   │  │
│  │                                                        │  │
│  │  用户名 (Username)                                      │  │
│  │  ┌──────────────────────────────────────────────────┐   │  │
│  │  │ postgres                                           │   │  │
│  │  └──────────────────────────────────────────────────┘   │  │
│  │                                                        │  │
│  │  密码 (Password)                                       │  │
│  │  ┌──────────────────────────────────────┐  ┌────┐      │  │
│  │  │ •••••••••••••••••••••••••••••••••••  │  │ 👁 │      │  │
│  │  └──────────────────────────────────────┘  └────┘      │  │
│  └────────────────────────────────────────────────────────┘  │
│                                                              │
│  授权配置                                                     │
│  ┌────────────────────────────────────────────────────────┐  │
│  │  Schema 列表（逗号分隔）                                 │  │
│  │  ┌──────────────────────────────────────────────────┐   │  │
│  │  │ public, sales                                     │   │  │
│  │  └──────────────────────────────────────────────────┘   │  │
│  │  限制 Agent 只能访问指定 Schema，留空表示全部             │  │
│  │                                                        │  │
│  │  授权表列表（可选，逗号分隔）                              │  │
│  │  ┌──────────────────────────────────────────────────┐   │  │
│  │  │ payment, rental, customer                         │   │  │
│  │  └──────────────────────────────────────────────────┘   │  │
│  │  限制 Agent 只能查询指定表，留空表示全部                  │  │
│  └────────────────────────────────────────────────────────┘  │
│                                                              │
│  数据源标识                                                   │
│  ┌────────────────────────────────────────────────────────┐  │
│  │  数据源 ID (Datasource ID)                              │  │
│  │  ┌──────────────────────────────────────────────────┐   │  │
│  │  │ my-postgres                                        │   │  │
│  │  └──────────────────────────────────────────────────┘   │  │
│  │  查询时通过此 ID 指定数据源（⚠️ 需要后端支持动态注册）      │  │
│  └────────────────────────────────────────────────────────┘  │
│                                                              │
│                                    [↺ 重置默认]  [💾 保存配置] │
└──────────────────────────────────────────────────────────────┘
```

### 4.2 数据源类型选择

单选卡片样式，3 个选项横向排列：

```
┌─────────────┐ ┌─────────────┐ ┌─────────────┐
│ ● PostgreSQL │ │ ○ MySQL     │ │ ○ StarRocks │
└─────────────┘ └─────────────┘ └─────────────┘
```

| 类型 | 默认端口 | 图标 | 说明 |
|------|----------|------|------|
| PostgreSQL | 5432 | `Database` | PostgreSQL 数据库 |
| MySQL | 3306 | `Database` | MySQL 数据库 |
| StarRocks | 9030 | `Database` | StarRocks OLAP 数据库 |

- 选中卡片：`border-[var(--color-primary)] bg-[var(--color-primary-light)]`
- 未选中卡片：`border-[var(--color-border)] bg-white hover:border-[var(--color-border-strong)]`
- 卡片样式：`rounded-md border p-3 cursor-pointer text-center text-sm font-medium`
- 选择类型后自动填充默认端口

### 4.3 高级模式（DSN 字符串）

点击「高级模式 ▸」切换为 DSN 字符串输入：

```
连接配置                                       [表单模式 ▸]

┌────────────────────────────────────────────────────────┐
│  DSN 连接字符串                                          │
│  ┌──────────────────────────────────────────────────┐   │
│  │ postgresql://postgres:password@localhost:5432/pa  │   │
│  │ gila                                              │   │
│  └──────────────────────────────────────────────────┘   │
│  直接填写完整 DSN，适用于复杂连接参数                     │
└────────────────────────────────────────────────────────┘
```

- DSN 输入框：`font-mono text-sm`，多行 `Textarea` 样式（min-h-20）
- 切换模式时，尝试解析 DSN 填充表单字段（表单 → DSN 时拼接，DSN → 表单 时解析）
- 解析失败时提示「无法解析 DSN，请检查格式」

### 4.4 连接配置字段

| 字段 | 类型 | 必填 | 校验 | 说明 |
|------|------|------|------|------|
| `host` | string | 是 | 非空 | 主机地址 |
| `port` | number | 是 | 1-65535 | 端口号，随数据源类型自动填充默认值 |
| `database` | string | 是 | 非空 | 数据库名 |
| `username` | string | 是 | 非空 | 用户名 |
| `password` | string | 是 | 非空 | 密码，password 类型 + 眼睛切换 |
| `dsn` | string | 否 | DSN 格式 | 高级模式下的完整连接字符串 |

> Host 和 Port 同行展示，使用 `grid grid-cols-3 gap-4`（Host 占 2 列，Port 占 1 列）。

### 4.5 授权配置字段

| 字段 | 类型 | 必填 | 校验 | 说明 |
|------|------|------|------|------|
| `schemas` | string | 否 | - | 逗号分隔的 Schema 列表，留空表示全部 |
| `allowed_tables` | string | 否 | - | 逗号分隔的表名列表，留空表示全部 |

> 前端存储为逗号分隔字符串，提交查询时转为 `string[]`。

### 4.6 数据源标识

| 字段 | 类型 | 必填 | 校验 | 说明 |
|------|------|------|------|------|
| `datasource_id` | string | 是 | `[a-z0-9_-]` | 数据源唯一标识，查询时传给后端 |

> ⚠️ **需要后端扩展**：当前后端只接受 `datasource_id = "pagila"`。支持自定义数据源需要后端新增动态数据源注册 API。

### 4.7 测试连接按钮

```
默认:     [🔌 测试连接]           ← Secondary 按钮
测试中:   [◌ 测试中...]          ← Spinner + 禁用
成功:     [✓ 连接成功]  13 张表   ← 绿色，显示表数量
失败:     [✕ 连接失败]            ← 红色，显示错误信息
```

> ⚠️ **需要后端扩展**：测试连接功能需要后端新增 `POST /api/v1/datasources/test` 接口。在后端未实现前，显示提示「此功能需要后端支持，暂不可用」。

### 4.8 移动端适配

移动端数据源类型卡片纵向排列，连接配置字段单列：

```
数据源类型
┌─────────────────┐
│ ● PostgreSQL     │
└─────────────────┘
┌─────────────────┐
│ ○ MySQL          │
└─────────────────┐
┌─────────────────┐
│ ○ StarRocks      │
└─────────────────┘

连接配置
┌─────────────────────────────┐
│ 主机地址                     │
│ ┌─────────────────────────┐ │
│ │ localhost               │ │
│ └─────────────────────────┘ │
│ 端口                        │
│ ┌─────────────────────────┐ │
│ │ 5432                    │ │
│ └─────────────────────────┘ │
│ ...                         │
└─────────────────────────────┘
```

---

## 5. 关于区域设计

设置页面内的「关于」区域展示应用信息、配置存储说明、安全提示：

```
┌──────────────────────────────────────────────────────────────┐
│  关于                                                         │
│                                                              │
│  应用信息                                                     │
│  ┌────────────────────────────────────────────────────────┐  │
│  │  应用名称    Text-to-SQL Agent                          │  │
│  │  版本        v1.0.0                                     │  │
│  │  技术栈      Next.js 16 + React 19 + Tailwind CSS 4     │  │
│  └────────────────────────────────────────────────────────┘  │
│                                                              │
│  配置存储                                                     │
│  ┌────────────────────────────────────────────────────────┐  │
│  │  ⚠️ 当前配置存储在浏览器 localStorage 中，仅适用于演示。   │  │
│  │  清除浏览器数据会导致配置丢失。                            │  │
│  │                                                        │  │
│  │  存储位置：                                              │  │
│  │  • 模型配置：localStorage["text-to-sql-model-config"]   │  │
│  │  • 数据库配置：localStorage["text-to-sql-db-config"]    │  │
│  │                                                        │  │
│  │  [🗑 清除所有配置]                                       │  │
│  └────────────────────────────────────────────────────────┘  │
│                                                              │
│  安全提示                                                     │
│  ┌────────────────────────────────────────────────────────┐  │
│  │  🔒 API Key 和数据库密码存储在 localStorage 中，          │  │
│  │  存在 XSS 窃取风险。生产环境请使用后端加密存储。           │  │
│  └────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────┘
```

- 安全提示卡片：`rounded-md border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800`
- 清除配置按钮：Danger 变体，点击后弹出确认对话框

---

## 6. localStorage 数据结构定义

### 6.1 模型配置

**Key**: `text-to-sql-model-config`

**Value Schema** (JSON):

```typescript
interface ModelConfig {
  version: 1;                          // schema 版本，便于未来迁移
  models: {
    simple: ModelEntry;
    standard: ModelEntry;
    complex: ModelEntry;
    fallback: ModelEntry;              // fallback 可 enabled=false
  };
  updatedAt: string;                   // ISO 8601 时间戳
}

interface ModelEntry {
  enabled: boolean;
  base_url: string;
  api_key: string;                     // 明文存储（演示用，见安全提示）
  model_name: string;
}
```

**示例值**:

```json
{
  "version": 1,
  "models": {
    "simple": {
      "enabled": true,
      "base_url": "https://api.openai.com/v1",
      "api_key": "sk-xxxxxxxxxxxx",
      "model_name": "gpt-4o-mini"
    },
    "standard": {
      "enabled": true,
      "base_url": "https://api.openai.com/v1",
      "api_key": "sk-xxxxxxxxxxxx",
      "model_name": "gpt-4o"
    },
    "complex": {
      "enabled": true,
      "base_url": "https://api.openai.com/v1",
      "api_key": "sk-xxxxxxxxxxxx",
      "model_name": "o1-preview"
    },
    "fallback": {
      "enabled": false,
      "base_url": "",
      "api_key": "",
      "model_name": ""
    }
  },
  "updatedAt": "2025-07-30T12:00:00.000Z"
}
```

### 6.2 数据库配置

**Key**: `text-to-sql-db-config`

**Value Schema** (JSON):

```typescript
interface DbConfig {
  version: 1;
  datasource_id: string;               // 数据源唯一标识
  type: "postgresql" | "mysql" | "starrocks";
  connection: {
    mode: "form" | "dsn";              // 表单模式 or DSN 模式
    host?: string;                     // form 模式
    port?: number;                     // form 模式
    database?: string;                 // form 模式
    username?: string;                 // form 模式
    password?: string;                 // form 模式，明文存储
    dsn?: string;                      // dsn 模式
  };
  auth: {
    schemas: string[];                 // 授权 Schema 列表，空数组表示全部
    allowed_tables: string[];          // 授权表列表，空数组表示全部
  };
  updatedAt: string;                   // ISO 8601 时间戳
}
```

**示例值**:

```json
{
  "version": 1,
  "datasource_id": "my-postgres",
  "type": "postgresql",
  "connection": {
    "mode": "form",
    "host": "localhost",
    "port": 5432,
    "database": "pagila",
    "username": "postgres",
    "password": "mypassword"
  },
  "auth": {
    "schemas": ["public", "sales"],
    "allowed_tables": ["payment", "rental", "customer"]
  },
  "updatedAt": "2025-07-30T12:00:00.000Z"
}
```

### 6.3 容量与清理

| 项目 | 说明 |
|------|------|
| localStorage 容量限制 | 单个域名约 5-10MB，模型配置 + 数据库配置远低于此限制 |
| 版本迁移 | 通过 `version` 字段检测旧版本配置，升级时做数据迁移 |
| 读取容错 | JSON 解析失败时返回默认配置，不阻塞页面 |
| 默认配置 | 未配置时，模型配置全部 `enabled=false`，数据库配置为 Pagila 默认值 |

### 6.4 默认数据库配置

```typescript
const DEFAULT_DB_CONFIG: DbConfig = {
  version: 1,
  datasource_id: "pagila",
  type: "postgresql",
  connection: {
    mode: "form",
    host: "localhost",
    port: 5432,
    database: "pagila",
    username: "postgres",
    password: "",
  },
  auth: {
    schemas: [],
    allowed_tables: [],
  },
  updatedAt: new Date().toISOString(),
};
```

---

## 7. 导航入口设计

### 7.1 顶部导航栏新增「设置」

在 TopNav 的 `navItems` 数组中新增设置项，插入在「帮助」和「关于」之间：

```
[Logo] Text-to-SQL    工作台  历史  帮助  设置  关于   [GitHub]
```

```typescript
// TopNav.tsx 修改
const navItems = [
  { href: "/", label: "工作台" },
  { href: "/history", label: "历史" },
  { href: "/help", label: "帮助" },
  { href: "/settings", label: "设置" },    // 新增
  { href: "/about", label: "关于" },
];
```

- 设置项图标（可选）：`Settings` (lucide-react)，导航栏文字旁不加图标，保持一致性
- 导航项数量从 4 增至 5，桌面端导航栏宽度足够容纳

### 7.2 底部 Tab Bar 新增「设置」

移动端底部 Tab Bar 从 4 项增至 5 项：

```
┌─────────────────────────────────────┐
│  [🏠]   [📜]   [❔]   [⚙️]   [ℹ]    │
│  工作台  历史   帮助   设置   关于    │
└─────────────────────────────────────┘
```

```typescript
// BottomTabBar.tsx 修改
const tabs = [
  { href: "/", label: "工作台", icon: Home },
  { href: "/history", label: "历史", icon: History },
  { href: "/help", label: "帮助", icon: HelpCircle },
  { href: "/settings", label: "设置", icon: Settings },  // 新增
  { href: "/about", label: "关于", icon: Info },
];
```

- `grid-cols-4` → `grid-cols-5`
- 设置图标：`Settings` (lucide-react)
- 5 项 Tab 在 375px 宽度下每项约 75px，仍满足最小触摸目标 44px 要求

### 7.3 导航项高亮

- 当前页为 `/settings` 时，TopNav 的设置项和 BottomTabBar 的设置项同时高亮
- 高亮逻辑沿用现有实现：`pathname.startsWith("/settings")`

---

## 8. 交互流程

### 8.1 读取配置（页面加载）

```
用户进入 /settings
    │
    ▼
从 localStorage 读取 text-to-sql-model-config 和 text-to-sql-db-config
    │
    ├─ 有配置 → 解析 JSON，填充表单
    ├─ JSON 解析失败 → 使用默认配置，Toast 提示「配置读取失败，已使用默认值」
    └─ 无配置 → 使用默认配置（模型全部禁用，数据库为 Pagila）
    │
    ▼
表单显示当前配置值
```

### 8.2 保存配置

```
用户填写/修改配置
    │
    ▼
点击 [保存配置]
    │
    ├─ 前端校验：
    │   ├─ 启用的模型：base_url / api_key / model_name 非空
    │   ├─ base_url 格式合法（http/https）
    │   ├─ 数据库：host / port / database / username 非空
    │   └─ datasource_id 符合 [a-z0-9_-] 格式
    │
    ├─ 校验失败 → 对应字段标红 + 错误提示，不保存
    └─ 校验通过
        │
        ▼
    构造 ModelConfig / DbConfig 对象（含 updatedAt 时间戳）
        │
        ▼
    JSON.stringify 写入 localStorage
        │
        ▼
    Toast 提示「配置已保存」（success，右上角，3 秒）
```

### 8.3 测试连接

```
用户点击某模型的 [测试连接]
    │
    ▼
按钮变为 [◌ 测试中...]，禁用
    │
    ▼
检查后端是否支持测试连接 API
    │
    ├─ 后端未实现 → Toast 提示「此功能需要后端支持，暂不可用」(info)，按钮恢复
    └─ 后端已实现
        │
        ▼
    POST /api/v1/models/test
    body: { base_url, api_key, model_name }
        │
        ├─ 成功 → 按钮变 [✓ 连接成功]（绿色），2 秒后恢复
        └─ 失败 → 按钮变 [✕ 连接失败]（红色），下方显示错误信息
```

### 8.4 重置默认

```
用户点击 [重置默认]
    │
    ▼
弹出确认对话框：「确定要重置为默认配置吗？当前未保存的修改将丢失。」
    │
    ├─ 取消 → 关闭对话框，不操作
    └─ 确认
        │
        ▼
    表单填充为默认值（不写入 localStorage，需再点保存）
    Toast 提示「已重置为默认值，请点击保存以生效」(info)
```

### 8.5 清除所有配置

```
用户在「关于」区域点击 [清除所有配置]
    │
    ▼
弹出确认对话框：「确定要清除所有配置吗？此操作不可撤销，将删除模型配置和数据库配置。」
    │
    ├─ 取消 → 关闭对话框
    └─ 确认
        │
        ▼
    localStorage.removeItem("text-to-sql-model-config")
    localStorage.removeItem("text-to-sql-db-config")
        │
        ▼
    表单重置为默认值
    Toast 提示「所有配置已清除」(success)
```

### 8.6 高级模式切换（DSN ↔ 表单）

```
用户在数据库配置区域点击 [高级模式 ▸]
    │
    ▼
尝试将当前表单字段拼接为 DSN 字符串
    │
    ├─ 拼接成功 → 切换为 DSN 输入框，填充拼接结果
    └─ 字段不完整 → 切换为 DSN 输入框，DSN 为空，提示「请填写 DSN」

用户在 DSN 模式点击 [表单模式 ▸]
    │
    ▼
尝试解析当前 DSN 字符串
    │
    ├─ 解析成功 → 切换为表单，填充解析结果（host/port/database/username/password）
    └─ 解析失败 → Toast 提示「无法解析 DSN，请检查格式」，保持 DSN 模式
```

### 8.7 查询时传递配置

```
用户在工作台提交查询
    │
    ▼
从 localStorage 读取 model-config 和 db-config
    │
    ├─ 模型配置已启用 → 构造 model_config 对象
    ├─ 数据库配置非默认 → 设置 datasource_id 和 schemas
    └─ 配置为默认/未启用 → 不传额外参数，沿用后端默认
    │
    ▼
发送查询请求（附加配置信息）
    │
    ▼
⚠️ 后端未扩展时：忽略附加配置，使用 .env 配置
    后端已扩展时：使用前端传入的模型和数据源配置
```

---

## 9. 安全提示

### 9.1 localStorage 存储风险

> 🔒 **风险说明**：API Key 和数据库密码以明文存储在 localStorage 中，存在以下风险：

| 风险 | 说明 | 影响 |
|------|------|------|
| XSS 攻击 | 恶意脚本可通过 `localStorage.getItem()` 读取密钥 | API Key 泄露，可被用于盗用 LLM 额度 |
| 浏览器扩展 | 恶意扩展可访问页面 localStorage | 同上 |
| 共享设备 | 多人使用同一浏览器时配置可见 | 数据库密码泄露 |
| 开发者工具 | F12 → Application → localStorage 可直接查看 | 任何人可查看明文密钥 |

### 9.2 缓解措施

| 措施 | 说明 |
|------|------|
| 明确提示 | 设置页面顶部和「关于」区域展示安全警告 |
| 默认不启用 | 模型配置默认全部 `enabled=false`，用户主动启用才生效 |
| 掩码显示 | API Key 和密码字段默认掩码，需手动切换可见 |
| 一键清除 | 提供「清除所有配置」按钮，方便退出时清理 |
| 版本标识 | 配置带 `version` 字段，便于未来迁移到后端存储 |

### 9.3 生产环境建议

> 生产环境应将模型配置和数据库配置改为**后端加密存储**，前端只做 UI 交互，密钥不经过前端：

```
生产环境架构（建议）：
前端 UI → POST /api/v1/config/models → 后端加密存储到数据库
前端 UI → POST /api/v1/config/datasources → 后端加密存储到数据库
查询时后端自行读取配置，前端不传密钥
```

---

## 10. 文件清单与组件结构

### 10.1 新增文件

```
frontend/
├── app/
│   └── settings/
│       └── page.tsx                       # 新增：设置页面
├── lib/
│   └── config-storage.ts                  # 新增：localStorage 配置读写工具
└── components/
    └── settings/
        ├── SettingsLayout.tsx             # 新增：设置页面布局（左侧菜单 + 右侧表单）
        ├── ModelConfigSection.tsx         # 新增：模型配置区域
        ├── ModelConfigCard.tsx            # 新增：单个模型配置卡片
        ├── DbConfigSection.tsx            # 新增：数据库配置区域
        ├── DatasourceTypeSelector.tsx     # 新增：数据源类型选择器
        ├── ConnectionForm.tsx             # 新增：连接配置表单（含 DSN 切换）
        ├── AuthConfigForm.tsx             # 新增：授权配置表单
        ├── AboutSection.tsx               # 新增：关于区域
        ├── ToggleSwitch.tsx               # 新增：启用开关组件
        └── PasswordInput.tsx              # 新增：密码输入框（带眼睛切换）
```

### 10.2 修改文件

```
frontend/
├── lib/types.ts                           # 新增 ModelConfig / DbConfig 等类型
├── lib/api.ts                             # 查询时附加 model_config / datasource_id
├── components/layout/TopNav.tsx           # navItems 新增「设置」
└── components/layout/BottomTabBar.tsx     # tabs 新增「设置」，grid-cols-4 → grid-cols-5
```

### 10.3 config-storage.ts 核心接口

```typescript
// lib/config-storage.ts

export function getModelConfig(): ModelConfig;
export function setModelConfig(config: ModelConfig): void;
export function getDbConfig(): DbConfig;
export function setDbConfig(config: DbConfig): void;
export function clearAllConfigs(): void;
```

---

## 11. ⚠️ 需要后端扩展的接口契约清单

### 11.1 QueryRequest 扩展：model_config 字段

后端需在 `QueryRequest` 中新增可选字段 `model_config`：

```python
# app/api/models.py 扩展

class ModelConfigEntry(BaseModel):
    enabled: bool
    base_url: str
    api_key: str
    model_name: str

class ModelConfig(BaseModel):
    simple: ModelConfigEntry
    standard: ModelConfigEntry
    complex: ModelConfigEntry
    fallback: Optional[ModelConfigEntry] = None

class QueryRequest(BaseModel):
    question: str
    datasource_id: str = "pagila"
    schemas: list[str] = []
    debug: bool = False
    # ⚠️ 新增
    model_config: Optional[ModelConfig] = None   # 前端传入的模型配置
```

> **安全考量**：当前后端明确「API 不接受模型参数，属于服务端可信上下文」。接受前端传入的 `model_config` 会打破此边界，需后端评估：是否对 `base_url` 做白名单、是否限制 `model_name` 可选范围。

### 11.2 动态数据源注册 API

后端需新增数据源管理接口：

```
POST /api/v1/datasources          # 注册数据源
GET  /api/v1/datasources          # 列出已注册数据源
GET  /api/v1/datasources/{id}     # 查看数据源详情
DELETE /api/v1/datasources/{id}   # 删除数据源
POST /api/v1/datasources/test     # 测试数据源连接
```

```python
# 建议的 Pydantic 模型

class DatasourceCreate(BaseModel):
    datasource_id: str                          # 用户自定义 ID
    type: Literal["postgresql", "mysql", "starrocks"]
    host: str
    port: int
    database: str
    username: str
    password: str
    schemas: list[str] = []                     # 授权 Schema
    allowed_tables: list[str] = []              # 授权表

class DatasourceTestRequest(BaseModel):
    type: Literal["postgresql", "mysql", "starrocks"]
    host: str
    port: int
    database: str
    username: str
    password: str

class DatasourceTestResponse(BaseModel):
    success: bool
    message: str
    table_count: Optional[int] = None           # 成功时返回可访问表数量
```

> **安全考量**：允许前端注册任意数据源意味着后端会连接用户指定的数据库，存在 SSRF 风险。需后端对 `host` 做内网地址过滤、对 `port` 做范围限制。

### 11.3 模型测试连接 API

后端需新增模型测试接口：

```
POST /api/v1/models/test         # 测试模型连接
```

```python
class ModelTestRequest(BaseModel):
    base_url: str
    api_key: str
    model_name: str

class ModelTestResponse(BaseModel):
    success: bool
    message: str
    latency_ms: Optional[int] = None            # 响应延迟
```

> **安全考量**：后端会用前端传入的 `api_key` 实际调用 LLM API，存在密钥泄露风险（后端日志可能记录）。需确保后端不记录 `api_key`，且 `base_url` 做白名单校验。

### 11.4 兼容性要求

| 扩展项 | 兼容性要求 |
|--------|-----------|
| `model_config` 请求字段 | 可选，后端未收到时使用 `.env` 配置 |
| 动态数据源 | `datasource_id = "pagila"` 时使用 `.env` 的 DSN，无需注册 |
| 模型测试 API | 独立接口，不影响查询接口 |
| 数据源测试 API | 独立接口，不影响查询接口 |

---

## 12. 设计决策记录

| 决策 | 选择 | 理由 |
|------|------|------|
| 配置存储方案 | **localStorage** | 用户已确认演示用，简单快速，无需后端 |
| 设置页面布局 | 左侧菜单 + 右侧表单 | 经典设置页布局，分类清晰，扩展性好 |
| 移动端设置布局 | 手风琴折叠 | 窄屏不适合左右分栏，折叠更自然 |
| 底部 Tab 数量 | 4 → 5 项 | 新增设置入口，5 项在 375px 下仍可用 |
| API Key 显示方式 | password 掩码 + 眼睛切换 | 平衡安全与易用 |
| 高级模式 DSN | 切换按钮，非默认 | 大多数用户用表单模式，DSN 供高级用户 |
| 测试连接按钮位置 | 每个卡片内独立 | 即时反馈单条配置是否可用 |
| 数据源类型选择 | 卡片单选 | 3 个选项视觉清晰，比下拉框更直观 |
| 配置版本字段 | `version: 1` | 未来迁移到后端存储时做数据迁移 |
| 默认模型配置 | 全部 `enabled=false` | 不强制用户配置，未配置时沿用后端 `.env` |
| 未保存提示 | 保存按钮可加高亮（可选） | 避免用户忘记保存，但不过度打扰 |
