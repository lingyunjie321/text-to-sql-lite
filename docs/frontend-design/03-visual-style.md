# 03 - 视觉风格规范

## 1. 设计理念

采用 **现代简约** 风格（Linear / Vercel 风格），核心特征：

- **克制配色**：中性色为主色调，语义色仅用于状态传达
- **清晰层级**：通过字号、字重、颜色建立信息层级
- **充足留白**：内容区呼吸感强，不拥挤
- **柔和质感**：圆角适中、阴影柔和、边框轻盈
- **浅色主题**：以白色/浅灰为底，本次只做浅色模式

## 2. 配色方案

### 2.1 设计 Token（CSS 变量）

所有颜色通过 CSS 变量定义，便于未来扩展暗色模式。在 `src/app/globals.css` 中定义：

```css
:root {
  /* 主色 */
  --color-primary: #6366f1;        /* Indigo-500 */
  --color-primary-hover: #4f46e5;  /* Indigo-600 */
  --color-primary-light: #eef2ff;  /* Indigo-50 */

  /* 语义色 */
  --color-success: #16a34a;        /* Green-600 */
  --color-success-light: #f0fdf4;  /* Green-50 */
  --color-warning: #d97706;        /* Amber-600 */
  --color-warning-light: #fffbeb;  /* Amber-50 */
  --color-error: #dc2626;          /* Red-600 */
  --color-error-light: #fef2f2;    /* Red-50 */
  --color-info: #2563eb;           /* Blue-600 */
  --color-info-light: #eff6ff;     /* Blue-50 */

  /* 中性色 */
  --color-bg: #ffffff;             /* 页面背景 */
  --color-bg-subtle: #f9fafb;      /* 次级背景 Gray-50 */
  --color-bg-muted: #f3f4f6;       /* 卡片/表头背景 Gray-100 */
  --color-border: #e5e7eb;         /* 边框 Gray-200 */
  --color-border-strong: #d1d5db;  /* 强边框 Gray-300 */
  --color-text-primary: #111827;   /* 主文字 Gray-900 */
  --color-text-secondary: #4b5563; /* 次文字 Gray-600 */
  --color-text-tertiary: #9ca3af;  /* 弱文字 Gray-400 */
  --color-text-inverse: #ffffff;   /* 反色文字 */
}
```

### 2.2 主色系（Indigo 蓝紫色调）

选择 **Indigo（靛蓝）** 作为主色，理由：
- 蓝紫色调传达专业、智能、可信赖的印象，契合 AI 数据分析工具定位
- 与 Linear/Vercel 的视觉调性一致
- 对比度足够，在浅色背景上可读性好

| Token | Hex | 用途 |
|-------|-----|------|
| `--color-primary` | `#6366f1` | 主按钮、链接、聚焦态、选中态 |
| `--color-primary-hover` | `#4f46e5` | 主按钮悬停 |
| `--color-primary-light` | `#eef2ff` | 选中项背景、Tag 背景 |

### 2.3 语义色

| 语义 | Token | Hex（文字） | Hex（背景） | 用途 |
|------|-------|------------|------------|------|
| 成功 | `--color-success` | `#16a34a` | `#f0fdf4` | SUCCEEDED 状态标签 |
| 警告 | `--color-warning` | `#d97706` | `#fffbeb` | CLARIFICATION 状态标签、截断提示 |
| 错误 | `--color-error` | `#dc2626` | `#fef2f2` | FAILED 状态标签、错误卡片 |
| 信息 | `--color-info` | `#2563eb` | `#eff6ff` | SUCCEEDED_REPAIRED 状态标签、提示信息 |

### 2.4 中性色阶

| Token | Hex | Tailwind 对应 | 用途 |
|-------|-----|--------------|------|
| `--color-bg` | `#ffffff` | white | 页面背景、卡片背景 |
| `--color-bg-subtle` | `#f9fafb` | gray-50 | 次级背景、悬停行 |
| `--color-bg-muted` | `#f3f4f6` | gray-100 | 表头背景、Skeleton |
| `--color-border` | `#e5e7eb` | gray-200 | 默认边框、分隔线 |
| `--color-border-strong` | `#d1d5db` | gray-300 | 输入框聚焦前边框 |
| `--color-text-primary` | `#111827` | gray-900 | 标题、主要文字 |
| `--color-text-secondary` | `#4b5563` | gray-600 | 正文、次要文字 |
| `--color-text-tertiary` | `#9ca3af` | gray-400 | 占位符、辅助文字 |

### 2.5 Tailwind 配置映射

在 `tailwind.config.ts` 中扩展自定义颜色：

```ts
const config = {
  theme: {
    extend: {
      colors: {
        primary: {
          DEFAULT: 'var(--color-primary)',
          hover: 'var(--color-primary-hover)',
          light: 'var(--color-primary-light)',
        },
        semantic: {
          success: 'var(--color-success)',
          'success-light': 'var(--color-success-light)',
          warning: 'var(--color-warning)',
          'warning-light': 'var(--color-warning-light)',
          error: 'var(--color-error)',
          'error-light': 'var(--color-error-light)',
          info: 'var(--color-info)',
          'info-light': 'var(--color-info-light)',
        },
      },
    },
  },
};
```

## 3. 字体规范

### 3.1 字体族

```css
:root {
  --font-sans: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI',
    'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei', sans-serif;
  --font-mono: 'JetBrains Mono', 'Fira Code', 'SF Mono', 'Consolas',
    'Liberation Mono', monospace;
}
```

- **正文字体**：Inter（首选）+ 系统字体栈降级
  - Inter 是专为 UI 设计的开源字体，在中小字号下可读性极佳
  - 降级到系统字体栈确保跨平台一致性和加载速度
  - 中文降级到苹方/微软雅黑
- **等宽字体**：JetBrains Mono（首选）+ 系统等宽字体降级
  - 用于 SQL 代码展示、ID/trace_id 等技术信息

### 3.2 字号阶梯

| 级别 | Token | 字号 | 行高 | 字重 | 用途 |
|------|-------|------|------|------|------|
| Display | `text-4xl` | 36px | 1.1 (40px) | 700 | 欢迎页主标题（空状态） |
| H1 | `text-3xl` | 30px | 1.2 (36px) | 700 | 页面标题 |
| H2 | `text-2xl` | 24px | 1.3 (31px) | 600 | 区块标题 |
| H3 | `text-xl` | 20px | 1.4 (28px) | 600 | 卡片标题 |
| H4 | `text-lg` | 18px | 1.4 (25px) | 600 | 子标题 |
| Body | `text-base` | 16px | 1.5 (24px) | 400 | 正文（默认） |
| Body-sm | `text-sm` | 14px | 1.5 (21px) | 400 | 次要正文、表格内容 |
| Small | `text-sm` | 14px | 1.4 (20px) | 400 | 辅助文字 |
| Caption | `text-xs` | 12px | 1.4 (17px) | 400 | 标签、时间戳、计数器 |
| Code | `text-sm` | 14px | 1.6 (22px) | 400 | SQL 代码（等宽） |
| Micro | `text-xs` | 12px | 1.3 (16px) | 500 | 状态标签文字、表头 |

### 3.3 字重规范

| 字重值 | 名称 | 用途 |
|--------|------|------|
| 400 | Regular | 正文、表格内容 |
| 500 | Medium | 次要标题、标签、导航项 |
| 600 | Semibold | 卡片标题、区块标题 |
| 700 | Bold | 页面主标题、欢迎标题 |

### 3.4 行高规范

- 标题（H1-H4）：`leading-tight`（1.1-1.4），紧凑
- 正文：`leading-normal`（1.5），舒适
- 代码：`leading-relaxed`（1.6），宽松，便于阅读
- 标签/微文字：`leading-tight`（1.3），紧凑

## 4. 间距系统

基于 **4px** 基础单元（与 Tailwind 默认一致），实际使用以 **8px** 为主节奏。

### 4.1 间距阶梯

| Token | 值 | Tailwind | 用途 |
|-------|----|----------|------|
| `space-0` | 0px | `p-0` / `m-0` | 无间距 |
| `space-1` | 4px | `p-1` / `m-1` | 微间距（图标与文字间距） |
| `space-2` | 8px | `p-2` / `m-2` | 小间距（标签内边距） |
| `space-3` | 12px | `p-3` / `m-3` | 中小间距（输入框内边距） |
| `space-4` | 16px | `p-4` / `m-4` | 标准间距（卡片内边距） |
| `space-6` | 24px | `p-6` / `m-6` | 大间距（区块间距、页面水平内边距） |
| `space-8` | 32px | `p-8` / `m-8` | 区块间距 |
| `space-12` | 48px | `p-12` / `m-12` | 大区块间距 |
| `space-16` | 64px | `p-16` / `m-16` | 页面顶部间距（欢迎区） |

### 4.2 间距使用规范

| 场景 | 推荐间距 |
|------|----------|
| 图标与相邻文字 | 8px (`gap-2`) |
| 按钮内边距（水平） | 16px (`px-4`) |
| 按钮内边距（垂直） | 8px (`py-2`) |
| 输入框内边距 | 12px (`p-3`) |
| 卡片内边距 | 16px-24px (`p-4` / `p-6`) |
| 卡片间距 | 16px (`gap-4` / `space-y-4`) |
| 区块间距 | 24px-32px (`space-y-6` / `space-y-8`) |
| 页面水平内边距 | 24px (`px-6`)，移动端 16px (`px-4`) |
| 页面顶部内边距 | 32px (`pt-8`) |

## 5. 圆角规范

| Token | 值 | Tailwind | 用途 |
|-------|----|----------|------|
| `radius-sm` | 4px | `rounded` | 小元素（Tag、Badge） |
| `radius-md` | 6px | `rounded-md` | 按钮、输入框 |
| `radius-lg` | 8px | `rounded-lg` | 卡片、下拉菜单（主圆角） |
| `radius-xl` | 12px | `rounded-xl` | 大卡片、模态框 |
| `radius-2xl` | 16px | `rounded-2xl` | 欢迎区、特殊容器 |
| `radius-full` | 9999px | `rounded-full` | Chips、圆形按钮、头像 |

**使用原则**：
- 卡片、面板统一使用 `rounded-lg`（8px）作为主圆角
- 按钮、输入框使用 `rounded-md`（6px）
- 示例问题 Chips 使用 `rounded-full`

## 6. 阴影规范

采用柔和阴影，不使用强阴影。

| Token | CSS | Tailwind | 用途 |
|-------|-----|----------|------|
| `shadow-sm` | `0 1px 2px 0 rgba(0,0,0,0.05)` | `shadow-sm` | 输入框、卡片默认 |
| `shadow-md` | `0 4px 6px -1px rgba(0,0,0,0.07), 0 2px 4px -2px rgba(0,0,0,0.05)` | `shadow-md` | 卡片悬停、下拉菜单 |
| `shadow-lg` | `0 10px 15px -3px rgba(0,0,0,0.08), 0 4px 6px -4px rgba(0,0,0,0.05)` | `shadow-lg` | 模态框、弹出层 |

**使用原则**：
- 卡片默认 `shadow-sm`，悬停时可升级到 `shadow-md`
- 弹出层（下拉菜单、Toast）使用 `shadow-lg`
- 阴影颜色统一使用 `rgba(0,0,0,0.05~0.08)`，非常柔和

## 7. 组件风格规范

### 7.1 按钮（Button）

#### 变体

| 变体 | 背景 | 文字 | 边框 | 悬停 | 用途 |
|------|------|------|------|------|------|
| Primary | `--color-primary` | `#ffffff` | 无 | `--color-primary-hover` | 提交查询、确认操作 |
| Secondary | `#ffffff` | `--color-text-primary` | `--color-border-strong` | `--color-bg-subtle` | 取消、次要操作 |
| Ghost | transparent | `--color-text-secondary` | 无 | `--color-bg-subtle` | 折叠面板、弱化操作 |
| Danger | `--color-error` | `#ffffff` | 无 | `#b91c1c` (Red-700) | 删除、清空 |

#### 尺寸

| 尺寸 | 高度 | 水平内边距 | 字号 | 图标尺寸 |
|------|------|-----------|------|----------|
| Small | 32px (`h-8`) | 12px (`px-3`) | 14px (`text-sm`) | 16px |
| Medium | 40px (`h-10`) | 16px (`px-4`) | 14px (`text-sm`) | 18px |
| Large | 48px (`h-12`) | 24px (`px-6`) | 16px (`text-base`) | 20px |

#### 通用规范

- 圆角：`rounded-md`（6px）
- 过渡：`transition-colors duration-150`
- 禁用态：`opacity-50 cursor-not-allowed`
- 加载态：文字替换为 Spinner（白色），按钮禁用
- 聚焦态：`focus:ring-2 focus:ring-primary focus:ring-offset-2`

```
Primary Button 示例:
┌──────────────────────┐
│    提交查询    ▶      │  ← 白字、主色背景、rounded-md
└──────────────────────┘

Secondary Button 示例:
┌──────────────────────┐
│      取消            │  ← 深灰字、白底、灰边框
└──────────────────────┘

Ghost Button 示例:
    跳过                 ← 透明背景、灰字、无边框、悬停浅灰底
```

### 7.2 输入框 / Textarea

#### 输入框（Input）

```
┌────────────────────────────────────────┐
│  请输入搜索关键词...                      │  ← placeholder: text-tertiary
└────────────────────────────────────────┘
```

- 高度：40px (`h-10`)
- 内边距：水平 12px (`px-3`)，垂直 8px (`py-2`)
- 边框：1px `--color-border-strong`（`border border-gray-300`）
- 圆角：`rounded-md`
- 聚焦态：边框变为主色 + `ring-2 ring-primary/20`
- 禁用态：`bg-gray-50 text-gray-400 cursor-not-allowed`
- 错误态：边框 `--color-error` + 下方错误文字

#### Textarea（提问输入框）

```
┌──────────────────────────────────────────┐
│                                          │
│  输入你的问题...                    0/2000│  ← 右下角字符计数
│                                          │
└──────────────────────────────────────────┘
```

- 最小高度：48px（1 行）
- 最大高度：192px（约 6 行，超出滚动）
- 自动增高：内容增加时自动扩展高度
- 内边距：12px (`p-3`)
- 边框/圆角/聚焦态：同输入框
- 字符计数器：右下角绝对定位，`text-xs text-gray-400`
- 超限状态：计数器变红 `text-red-500`，边框变红

### 7.3 表格（Table）

```
┌──────────────────────────────────────────────────────────┐
│ │ title          │ total_revenue │ rental_count │        │  ← 表头
│ ├────────────────┼───────────────┼──────────────┤        │
│ │ TELEMARK...    │ $231.73       │ 8            │        │  ← 数据行
│ │ VOYAGE...      │ $216.97       │ 7            │ ← 悬停  │
│ │ ...            │ ...           │ ...          │        │
└──────────────────────────────────────────────────────────┘
```

| 元素 | 样式 |
|------|------|
| 表头 | `bg-gray-50 text-gray-600 text-xs font-medium uppercase tracking-wider` |
| 表头内边距 | `px-4 py-3` |
| 数据行文字 | `text-sm text-gray-900` |
| 数据行内边距 | `px-4 py-3` |
| 行边框 | `border-b border-gray-100` |
| 行悬停 | `bg-gray-50` |
| 行选中 | `bg-primary-light` |
| 数字列 | 右对齐 `text-right tabular-nums` |
| 文本列 | 左对齐 `text-left` |
| 长文本截断 | `truncate max-w-xs`（列宽固定时） |

#### 表格空状态

```
┌──────────────────────────────────┐
│                                  │
│       [📋 图标]                   │
│                                  │
│    查询成功，但没有匹配的数据       │
│                                  │
│    试试调整查询条件                │
│                                  │
└──────────────────────────────────┘
```

#### 表格加载态

```
┌──────────────────────────────────────────────────────────┐
│ │ ░░░░░░░░░░░░░░░ │ ░░░░░░░░░░░░░░░ │ ░░░░░░░░░░░ │    │
│ ├─────────────────┼─────────────────┼──────────────┤    │
│ │ ░░░░░░░░░░░░░░░ │ ░░░░░░░░░░░░░░░ │ ░░░░░░░░░░░ │    │
│ │ ░░░░░░░░░░░░░░░ │ ░░░░░░░░░░░░░░░ │ ░░░░░░░░░░░ │    │
└──────────────────────────────────────────────────────────┘
```

- 骨架屏：`bg-gray-200 animate-pulse rounded`
- 表头骨架 + 5 行数据骨架

### 7.4 卡片（Card）

#### 通用卡片

```
┌─────────────────────────────────────────────┐
│                                             │  ← bg-white, rounded-lg, shadow-sm
│  [卡片标题]                          [操作]  │     border border-gray-200
│                                             │     p-4 / p-6
│  卡片内容...                                  │
│                                             │
└─────────────────────────────────────────────┘
```

- 背景：`bg-white`
- 边框：`border border-gray-200`
- 圆角：`rounded-lg`（8px）
- 阴影：`shadow-sm`
- 内边距：`p-4`（紧凑）或 `p-6`（标准）
- 悬停（可交互卡片）：`shadow-md transition-shadow duration-150`

#### 状态卡片（QueryResultCard 顶部）

```
┌──────────────────────────────────────────────────────────┐
│ [✓ 查询成功]  一次通过  ·  返回 10 行                       │
└──────────────────────────────────────────────────────────┘
```

- 成功：`bg-green-50 text-green-700`，图标 `CheckCircle`
- 修复后成功：`bg-blue-50 text-blue-700`，图标 `CheckCircle`
| 澄清：`bg-amber-50 text-amber-700`，图标 `HelpCircle`
- 失败：`bg-red-50 text-red-700`，图标 `XCircle`
- 标签圆角：`rounded-md`
- 标签内边距：`px-2.5 py-1`
- 标签字号：`text-xs font-medium`

### 7.5 Tag / Badge（状态标签）

| 状态 | 文案 | 背景 | 文字 | 图标 |
|------|------|------|------|------|
| SUCCEEDED_FIRST_PASS | 查询成功 | `bg-green-50` | `text-green-700` | CheckCircle |
| SUCCEEDED_REPAIRED | 经修复后成功 | `bg-blue-50` | `text-blue-700` | CheckCircle |
| CLARIFICATION_REQUIRED | 需要补充信息 | `bg-amber-50` | `text-amber-700` | HelpCircle |
| REJECTED_SECURITY | 安全拒绝 | `bg-red-50` | `text-red-700` | ShieldX |
| FAILED_TIMEOUT | 查询超时 | `bg-red-50` | `text-red-700` | Clock |
| FAILED_CONNECTION | 连接错误 | `bg-red-50` | `text-red-700` | WifiOff |
| FAILED_RESOURCE_RISK | 资源风险 | `bg-orange-50` | `text-orange-700` | AlertTriangle |
| FAILED_DUPLICATE_LOOP | 查询失败 | `bg-red-50` | `text-red-700` | XCircle |
| FAILED_REPAIR_EXHAUSTED | 修复失败 | `bg-red-50` | `text-red-700` | XCircle |
| FAILED_INTERNAL | 系统错误 | `bg-red-50` | `text-red-700` | ServerCrash |

- 圆角：`rounded-md`
- 内边距：`px-2.5 py-1`
- 字号：`text-xs font-medium`
- 图标尺寸：14px，与文字间距 4px

### 7.6 折叠面板（Collapsible）

用于 SQL 展示和元信息展示。

```
折叠态:
┌──────────────────────────────────────────────────────────┐
│  ▸ 查看 SQL                                               │
└──────────────────────────────────────────────────────────┘

展开态:
┌──────────────────────────────────────────────────────────┐
│  ▾ 查看 SQL                                  [📋 复制]     │
├──────────────────────────────────────────────────────────┤
│  SELECT f.title, SUM(p.amount) AS total_revenue          │
│  FROM payment p                                          │
│  ...                                                     │
└──────────────────────────────────────────────────────────┘
```

- 触发区：`flex items-center justify-between px-4 py-3 cursor-pointer hover:bg-gray-50`
- chevron 图标：`ChevronRight`（折叠）→ `ChevronDown`（展开），`transition-transform duration-150`
- 展开内容区：`border-t border-gray-100 p-4`
- 展开动画：`transition-all duration-200`（高度 + 透明度）

### 7.7 Toast / 通知

```
                                    ┌──────────────────────────┐
                                    │ ✓  SQL 已复制到剪贴板      │
                                    └──────────────────────────┘
```

- 位置：右上角（桌面）/ 底部居中（移动端）
- 自动消失：3 秒
- 动画：从右侧滑入（桌面）/ 从底部滑入（移动端）
- 类型：success（绿色）、error（红色）、info（蓝色）
- 样式：`bg-white shadow-lg rounded-lg border border-gray-200 px-4 py-3`
- 图标 + 文字 + 可选手动关闭按钮

### 7.8 加载指示器

#### Spinner

```
   ◌    ← 旋转的圆环，主色
```

- 尺寸：16px / 20px / 24px / 32px（根据场景）
- 颜色：主色 `--color-primary`（浅色背景上），白色（主色背景上）
- 动画：`animate-spin`
- CSS 实现：`border-2 border-current border-t-transparent rounded-full animate-spin`

#### Skeleton（骨架屏）

```
┌──────────────────────────────────────────┐
│ ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░ │
│ ░░░░░░░░░░░░░░░░░░░░░░░░░                │
└──────────────────────────────────────────┘
```

- 颜色：`bg-gray-200`
- 动画：`animate-pulse`
- 圆角：`rounded`（默认）或 `rounded-md`（宽条）
- 高度：根据内容元素等比（行高 20-24px）

### 7.9 空状态

```
┌───────────────────────────────────────────┐
│                                           │
│            ┌──────────┐                   │
│            │  [图标]   │                   │  ← 64px 图标，灰色
│            └──────────┘                   │
│                                           │
│         还没有查询历史记录                   │  ← text-lg font-medium gray-600
│                                           │
│    去工作台提一个问题，记录会出现在这里       │  ← text-sm gray-400
│                                           │
│            [去提问 →]                      │  ← Secondary 按钮
│                                           │
└───────────────────────────────────────────┘
```

- 居中布局：`flex flex-col items-center justify-center text-center py-16`
- 图标：64px，`text-gray-300`
- 主文字：`text-lg font-medium text-gray-600`
- 辅助文字：`text-sm text-gray-400 mt-2`
- 操作按钮：`mt-6`

### 7.10 示例问题 Chip

```
┌──────────────────────────┐
│  租金收入最高的10部电影     │  ← text-sm, rounded-full
└──────────────────────────┘
```

- 样式：`inline-flex items-center rounded-full border border-gray-200 bg-white px-4 py-2 text-sm text-gray-700 cursor-pointer`
- 悬停：`hover:bg-gray-50 hover:border-gray-300`
- 过渡：`transition-colors duration-150`
- 间距：`gap-2`（Chip 之间）

### 7.11 对话气泡（用户消息）

```
                          ┌──────────────────────────────────┐
                          │ 上个月租金收入最高的 10 部电影是？  │
                          └──────────────────────────────────┘
```

- 右对齐：`flex justify-end`
- 背景：`bg-primary-light`（`#eef2ff`）或 `bg-blue-50`
- 圆角：`rounded-2xl rounded-br-md`（右下角小圆角，模拟气泡尖角）
- 内边距：`px-4 py-3`
- 文字：`text-sm text-gray-900`
- 最大宽度：`max-w-[80%]`

### 7.12 分页器

```
  [◀ 上一页]    1  2  3  ...  20    [下一页 ▶]
```

- 居中或右对齐
- 页码按钮：`h-8 w-8 rounded-md text-sm`
- 当前页：`bg-primary text-white`
- 其他页：`text-gray-600 hover:bg-gray-50`
- 禁用（首/末页）：`opacity-40 cursor-not-allowed`

## 8. 图标方案

### 8.1 图标库

使用 **lucide-react**，理由：
- 轻量、现代、线条风格统一
- 支持 Tree-shaking，按需引入
- 与 Linear/Vercel 风格一致

### 8.2 安装

```bash
npm install lucide-react
```

### 8.3 常用图标清单

| 图标 | 名称 | 用途 |
|------|------|------|
| ✓ | `CheckCircle` | 成功状态 |
| ✕ | `XCircle` | 失败状态 |
| ❓ | `HelpCircle` | 澄清状态 |
| ⚠ | `AlertTriangle` | 警告/截断提示 |
| ⚠ | `AlertCircle` | 错误提示 |
| ▶ | `ArrowRight` / `Send` | 提交按钮 |
| ▸ | `ChevronRight` | 折叠面板（折叠态） |
| ▾ | `ChevronDown` | 折叠面板（展开态） |
| 📋 | `Table` | 表格视图 |
| 📊 | `BarChart3` | 柱状图视图 |
| 📈 | `LineChart` | 折线图视图 |
| 📋 | `Copy` | 复制按钮 |
| ⬇ | `Download` | 导出 CSV |
| 🔄 | `RefreshCw` | 重试按钮 |
| ◌ | `Loader2` | 加载 Spinner |
| 🔍 | `Search` | 搜索框 |
| 🗑 | `Trash2` | 删除按钮 |
| 🛡 | `ShieldX` | 安全拒绝 |
| 🕐 | `Clock` | 超时 |
| 📡 | `WifiOff` | 连接错误 |
| 💻 | `ServerCrash` | 内部错误 |
| 🏠 | `Home` | 工作台导航 |
| 📜 | `History` | 历史记录导航 |
| ❔ | `HelpCircle` | 帮助导航 |
| ℹ | `Info` | 关于导航 |

### 8.4 图标使用规范

- 统一尺寸：16px (`w-4 h-4`)、18px (`w-4.5 h-4.5`)、20px (`w-5 h-5`)、24px (`w-6 h-6`)
- 颜色：继承父元素 `text` 颜色（`currentColor`）
- 描边宽度：默认 1.5px（`strokeWidth={1.5}`），视觉更轻盈
- 与文字间距：`gap-2`（8px）

## 9. 暗色模式预留

本次只做浅色模式，但配色全部通过 CSS 变量定义，为后续暗色模式扩展预留。

### 扩展方式

```css
/* 浅色模式（默认） */
:root {
  --color-bg: #ffffff;
  --color-text-primary: #111827;
  /* ... */
}

/* 暗色模式（预留） */
@media (prefers-color-scheme: dark) {
  :root {
    --color-bg: #0a0a0a;
    --color-text-primary: #fafafa;
    --color-bg-subtle: #141414;
    --color-border: #262626;
    /* ... */
  }
}
```

### 预留要点

1. 所有颜色使用 CSS 变量，不硬编码 hex 值
2. Tailwind 配置中引用 CSS 变量
3. 语义色在暗色模式下需要调低饱和度、提高亮度
4. 阴影在暗色模式下替换为更深的边框

## 10. 过渡与动画规范

| 场景 | 属性 | 时长 | 缓动函数 |
|------|------|------|----------|
| 按钮悬停 | color, background-color | 150ms | ease |
| 卡片悬停 | box-shadow | 150ms | ease |
| 折叠展开 | height, opacity | 200ms | ease-in-out |
| 页面切换 | opacity | 200ms | ease |
| Toast 出现 | transform, opacity | 200ms | ease-out |
| Toast 消失 | transform, opacity | 150ms | ease-in |
| Spinner 旋转 | transform | 1000ms | linear (infinite) |
| Skeleton 脉冲 | opacity | 2000ms | ease-in-out (infinite) |

**Tailwind 工具类**：
- `transition-colors duration-150`
- `transition-all duration-200`
- `transition-shadow duration-150`
- `animate-spin`
- `animate-pulse`
