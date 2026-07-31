# 06 - 查询结果增强（参考信息展示）

> 本文档设计「查询结果增强」功能：在查询结果卡片中展示 Agent 参考了哪些表、哪些语义/口径/指标知识、走了什么复杂度路由、经历过哪些修复。这是用户最关心的可解释性增强，让 Agent 的推理过程从黑盒变白盒。

---

## 1. 设计目标与背景

### 1.1 现状

当前 `QueryResponse` 只返回 `sql`、`columns`、`rows`、`attempts`、`repair_count` 等终态字段。前端 `QueryResultCard` 展示：

```
状态卡片 → 结果表格/图表 → SQL（折叠）→ 元信息（折叠）
```

用户只能看到「最终结果」，无法知道 Agent **参考了什么、为什么这么做**。

### 1.2 增强目标

| 增强点 | 用户价值 |
|--------|----------|
| 候选表（Schema Linking） | 知道 Agent 命中了哪些表和字段，验证选表是否正确 |
| 语义参考（业务知识 RAG） | 知道 Agent 参考了哪些口径/指标/术语定义，理解口径来源 |
| 复杂度路由 | 知道 Agent 把问题判为什么难度、用了什么模型、检索多少条 |
| 修复历史 | 知道 Agent 经历过几次修复、每次错在哪、怎么修的 |

### 1.3 关键约束

> ⚠️ **需要后端扩展**：当前后端 `QueryResponse` 不包含以下任何字段。本文档假设后端会扩展响应体，新增字段全部为**可选字段**，前端做容错处理——后端未返回时该区块静默不展示，不影响现有功能。

> ⚠️ **后端架构约束**：后端当前明确「模型路由通过 .env 配置、数据库固定 Pagila、Schema Linking 候选不对外暴露」。这些扩展会打破现有「服务端可信上下文」边界，属于架构性变更，需后端评估安全影响后再实施。

---

## 2. 扩展后的 QueryResponse 类型定义

在 `src/lib/types.ts` 中扩展 `QueryResponse`，新增 4 个可选字段。**标注 `// ⚠️ 需要后端扩展` 的字段为后端需新增的**。

```typescript
// ========================
// 新增类型定义（全部需要后端扩展）
// ========================

/**
 * Schema Linking 候选表（探测 + 物化结果）
 * ⚠️ 需要后端扩展：在 QueryResponse 中新增 schema_candidates 字段
 */
export interface SchemaCandidate {
  table_name: string;        // 表名，如 "payment"
  schema: string;            // 所属 schema，如 "public"
  fields: string[];          // 命中字段列表，如 ["amount", "payment_date"]
  score: number;             // 相关性分数 0-1，越高越相关
  source: "bm25" | "embedding" | "rerank";  // 检索来源
  selected: boolean;         // 是否最终被选入 SQL（物化结果）
}

/**
 * 业务知识 RAG 命中片段
 * ⚠️ 需要后端扩展：在 QueryResponse 中新增 semantic_references 字段
 */
export interface SemanticReference {
  type: "caliber" | "metric" | "glossary" | "few_shot";
  // caliber=口径, metric=指标, glossary=术语, few_shot=示例
  title: string;             // 知识标题
  content: string;           // 知识内容
  score: number;             // 相关性分数 0-1
}

/**
 * 复杂度路由结果
 * ⚠️ 需要后端扩展：在 QueryResponse 中新增 complexity_route 字段
 */
export interface ComplexityRoute {
  level: "simple" | "standard" | "complex";  // 复杂度等级
  top_k: number;             // 检索条数 5/10/20
  model_used: string;        // 实际使用的模型名
  reason: string;            // 路由原因（自然语言）
}

/**
 * 修复过程详情（每次修复的记录）
 * ⚠️ 需要后端扩展：在 QueryResponse 中新增 repair_history 字段
 */
export interface RepairHistoryEntry {
  attempt: number;           // 第几次尝试（1-based）
  error_type: string;        // 错误类型，如 "SYNTAX_ERROR"
  fix_strategy: string;      // 修复策略描述，如 "移除无效字段 film.xxx"
  fingerprint: string;       // SQL 指纹（用于去重检测）
}

// ========================
// 扩展后的 QueryResponse
// ========================

export interface QueryResponse {
  // --- 现有字段（后端已实现）---
  request_id: string;
  trace_id: string;
  status: FinalStatus;
  sql?: string | null;
  columns?: ResponseColumn[];
  rows?: JsonValue[][];
  returned_row_count?: number;
  truncated?: boolean;
  attempts?: number;
  repair_count?: number;
  clarification?: ResponseClarification | null;
  error?: PublicError | null;

  // --- 新增字段（⚠️ 需要后端扩展，全部可选）---
  schema_candidates?: SchemaCandidate[];        // 候选表
  semantic_references?: SemanticReference[];    // 语义参考
  complexity_route?: ComplexityRoute;           // 复杂度路由
  repair_history?: RepairHistoryEntry[];        // 修复历史
}
```

### 字段说明汇总

| 字段 | 类型 | 必填 | 后端状态 | 说明 |
|------|------|------|----------|------|
| `schema_candidates` | `SchemaCandidate[]` | 否 | ⚠️ 需扩展 | Schema Linking 命中的候选表，按 score 降序 |
| `semantic_references` | `SemanticReference[]` | 否 | ⚠️ 需扩展 | 业务知识 RAG 命中片段，按 score 降序 |
| `complexity_route` | `ComplexityRoute` | 否 | ⚠️ 需扩展 | 复杂度路由决策详情 |
| `repair_history` | `RepairHistoryEntry[]` | 否 | ⚠️ 需扩展 | 修复过程记录，`repair_count > 0` 时有值 |

---

## 3. 参考信息区整体设计

### 3.1 在 QueryResultCard 中的位置

参考信息区作为新的折叠面板，插入在「结果展示区」和「SQL 折叠区」之间：

```
QueryResultCard 结构（增强后）：
┌──────────────────────────────────────────────────────┐
│ ① 状态卡片 (StatusBadge)                               │
├──────────────────────────────────────────────────────┤
│ ② 结果展示区 (Tabs: 表格/柱状图/折线图)                   │
├──────────────────────────────────────────────────────┤
│ ③ 参考信息区 (ReferenceInfo) ← 【新增】默认展开          │
│   ├── 候选表 (SchemaCandidatesTable)                   │
│   ├── 语义参考 (SemanticReferencesGroup)               │
│   ├── 复杂度路由 (ComplexityRoutePanel)                │
│   └── 修复历史 (RepairHistoryTimeline)                 │
├──────────────────────────────────────────────────────┤
│ ④ SQL 折叠区 (SqlCollapse) — 默认折叠                   │
├──────────────────────────────────────────────────────┤
│ ⑤ 元信息折叠区 (MetaInfo) — 默认折叠                     │
└──────────────────────────────────────────────────────┘
```

### 3.2 展示条件

| 状态 | 是否展示参考信息区 |
|------|-------------------|
| `SUCCEEDED_FIRST_PASS` | ✅ 展示（若后端返回了扩展字段） |
| `SUCCEEDED_REPAIRED` | ✅ 展示（含修复历史） |
| `CLARIFICATION_REQUIRED` | ❌ 不展示 |
| `REJECTED_SECURITY` / `FAILED_*` | ❌ 不展示 |

> **容错原则**：即使状态为成功，若后端未返回任何扩展字段（`schema_candidates` 等全部为 `undefined` 或空数组），则整个参考信息区不渲染，QueryResultCard 退化为现有行为。

### 3.3 参考信息区 ASCII 线框图（桌面端）

```
┌──────────────────────────────────────────────────────────────┐
│  ▾ 参考信息                                        4 项       │  ← 折叠触发区
├──────────────────────────────────────────────────────────────┤  ← border-t
│                                                              │
│  ── 候选表 ────────────────────────────────────── 5 张表 ──   │  ← 子区块标题
│  ┌────────────────────────────────────────────────────────┐  │
│  │ 表名            命中字段            来源      相关性    │  │  ← 表头
│  ├────────────────────────────────────────────────────────┤  │
│  │ ● payment       amount, payment_date  rerank   0.95  ✓ │  │  ← 已选用 ✓
│  │ ○ film          title, film_id        bm25     0.78    │  │  ← 未选用 ○
│  │ ○ customer      customer_id           embedding 0.65    │  │
│  │ ○ rental        rental_id, return_date bm25    0.62    │  │
│  │ ○ staff         staff_id              embedding 0.41    │  │
│  └────────────────────────────────────────────────────────┘  │
│                                                              │
│  ── 语义参考 ──────────────────────────────────── 3 条 ──    │  ← 子区块标题
│  ┌────────────────────────────────────────────────────────┐  │
│  │ [口径] 租金收入口径定义                          0.92   │  │  ← 类型标签 + 标题 + 分数
│  │ payment.amount 汇总值，排除 NULL 与退款记录...           │  │  ← 内容摘要
│  ├────────────────────────────────────────────────────────┤  │
│  │ [指标] 月度活跃客户数                          0.87    │  │
│  │ 当月有至少一笔有效 rental 记录的去重 customer...          │  │
│  ├────────────────────────────────────────────────────────┤  │
│  │ [术语] Pagila 业务术语表                        0.71    │  │
│  │ rental=租赁记录，payment=支付记录，inventory=库存...      │  │
│  └────────────────────────────────────────────────────────┘  │
│                                                              │
│  ── 复杂度路由 ───────────────────────────────────────────   │  ← 子区块标题
│  ┌────────────────────────────────────────────────────────┐  │
│  │ [复杂] Top-K: 20    模型: gpt-4o-mini                  │  │  ← 等级标签 + Top-K + 模型
│  │ 涉及 3 表 JOIN + 时间窗口聚合，判定为复杂查询             │  │  ← 路由原因
│  └────────────────────────────────────────────────────────┘  │
│                                                              │
│  ── 修复历史 ────────────────────────────────── 2 次修复 ──  │  ← 子区块标题
│  ┌────────────────────────────────────────────────────────┐  │
│  │  ● 第 1 次尝试                                          │  │  ← 时间线节点
│  │  │  错误：SCHEMA_ERROR                                   │  │
│  │  │  修复：移除了不存在的字段 film.replacement_cost        │  │
│  │  │  指纹：sel_film_pmt_join_v1                           │  │
│  │  ▼                                                       │  │
│  │  ● 第 2 次尝试                                          │  │
│  │     错误：SYNTAX_ERROR                                   │  │
│  │     修复：补全 GROUP BY 子句                              │  │
│  │     指纹：sel_film_pmt_join_v2                           │  │
│  │     ✓ 最终成功                                           │  │  ← 成功标记
│  └────────────────────────────────────────────────────────┘  │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

### 3.4 折叠态

```
┌──────────────────────────────────────────────────────────────┐
│  ▸ 参考信息                                        4 项       │  ← 点击展开
└──────────────────────────────────────────────────────────────┘
```

### 3.5 组件结构

```
ReferenceInfo (参考信息区容器，Collapsible)
├── SchemaCandidatesTable (候选表)
├── SemanticReferencesGroup (语义参考分组)
├── ComplexityRoutePanel (复杂度路由)
└── RepairHistoryTimeline (修复历史时间线)
```

### 3.6 样式规范

沿用 [03-visual-style.md](./03-visual-style.md) 的折叠面板规范：

| 元素 | 样式 |
|------|------|
| 折叠触发区 | `flex items-center justify-between px-4 py-3 cursor-pointer hover:bg-[var(--color-bg-subtle)]` |
| chevron 图标 | `ChevronRight`（折叠）→ 旋转 90° 变 `ChevronDown`（展开），`transition-transform duration-150` |
| 展开内容区 | `border-t border-[var(--color-border)] p-4 space-y-4` |
| 子区块标题 | `text-xs font-medium text-[var(--color-text-tertiary)] uppercase tracking-wider` + 右侧计数 |
| 子区块容器 | `rounded-md border border-[var(--color-border)] bg-[var(--color-bg-subtle)]` |

---

## 4. 候选表展示组件（SchemaCandidatesTable）

### 4.1 设计说明

展示 Schema Linking 阶段命中的候选表，让用户验证 Agent 选表是否合理。

- 按 `score` 降序排列
- `selected=true` 的表用实心圆点 `●` + 绿色 `✓` 标记，表示最终被选入 SQL
- `selected=false` 的表用空心圆点 `○` 标记，表示候选但未选用
- `source` 字段用彩色标签区分检索来源

### 4.2 ASCII 线框图

```
── 候选表 ────────────────────────────────────── 5 张表 ──
┌────────────────────────────────────────────────────────────┐
│ │ 表名          │ 命中字段          │ 来源     │ 相关性  │  │  ← 表头
│ ├───────────────┼──────────────────┼──────────┼─────────┤  │
│ │ ● payment  ✓  │ amount, payment_ │ [rerank] │ 0.95    │  │  ← 选中行高亮
│ │ ○ film        │ title, film_id   │ [bm25]   │ 0.78    │  │
│ │ ○ customer    │ customer_id      │ [embed]  │ 0.65    │  │
│ │ ○ rental      │ rental_id, ret.. │ [bm25]   │ 0.62    │  │
│ │ ○ staff       │ staff_id         │ [embed]  │ 0.41    │  │
└────────────────────────────────────────────────────────────┘
```

### 4.3 字段说明

| 列 | 内容 | 对齐 | 样式 |
|----|------|------|------|
| 选中标记 | `●`（选中）/ `○`（未选中）+ `✓`（选中） | 居中 | `●` 用 `text-[var(--color-success)]`，`○` 用 `text-[var(--color-text-tertiary)]` |
| 表名 | `schema.table_name` | 左对齐 | `font-mono text-sm text-[var(--color-text-primary)]` |
| 命中字段 | `field1, field2, ...` | 左对齐 | `font-mono text-xs text-[var(--color-text-secondary)]`，超长截断 `truncate max-w-[200px]` |
| 来源 | 检索来源标签 | 居中 | 见下方来源标签配色 |
| 相关性 | `score` 保留 2 位小数 | 右对齐 | `tabular-nums text-xs`，分数 > 0.8 用 `text-[var(--color-success)]` |

### 4.4 来源标签配色

| source | 标签文案 | 背景 | 文字 |
|--------|----------|------|------|
| `bm25` | `bm25` | `bg-amber-50` | `text-amber-700` |
| `embedding` | `embed` | `bg-blue-50` | `text-blue-700` |
| `rerank` | `rerank` | `bg-purple-50` | `text-purple-700` |

标签样式：`inline-flex items-center rounded px-1.5 py-0.5 text-xs font-medium`

### 4.5 选中行高亮

`selected=true` 的行使用 `bg-[var(--color-success-light)]` 背景高亮，强化「这张表被用到了」的视觉信号。

### 4.6 移动端适配

移动端（< 768px）表格列过多，改为卡片列表形式：

```
── 候选表 ───────────────────────────── 5 张表 ──
┌─────────────────────────────────────┐
│ ● payment                    ✓ 0.95  │  ← 表名 + 选中标记 + 分数
│   命中: amount, payment_date          │  ← 字段
│   来源: [rerank]                      │
└─────────────────────────────────────┘
┌─────────────────────────────────────┐
│ ○ film                       0.78    │
│   命中: title, film_id               │
│   来源: [bm25]                        │
└─────────────────────────────────────┘
```

- 卡片样式：`rounded-md border border-[var(--color-border)] p-3`
- 选中卡片：`border-[var(--color-success)] bg-[var(--color-success-light)]`

---

## 5. 语义参考展示组件（SemanticReferencesGroup）

### 5.1 设计说明

展示业务知识 RAG 命中的片段，按 `type` 分组（口径/指标/术语/示例），让用户理解 Agent 的口径依据。

- 按 `type` 分组展示，组内按 `score` 降序
- 分组顺序：口径 → 指标 → 术语 → 示例
- 每条展示：类型标签 + 标题 + 内容摘要 + 相关性分数
- 内容过长时截断，点击展开查看全文

### 5.2 类型分组与配色

| type | 中文标签 | 标签背景 | 标签文字 | 图标 |
|------|----------|----------|----------|------|
| `caliber` | 口径 | `bg-indigo-50` | `text-indigo-700` | `Ruler` |
| `metric` | 指标 | `bg-emerald-50` | `text-emerald-700` | `TrendingUp` |
| `glossary` | 术语 | `bg-amber-50` | `text-amber-700` | `BookOpen` |
| `few_shot` | 示例 | `bg-purple-50` | `text-purple-700` | `Lightbulb` |

> 图标来源：lucide-react，尺寸 14px，与标签文字间距 4px。

### 5.3 ASCII 线框图

```
── 语义参考 ──────────────────────────────────── 4 条 ──
┌────────────────────────────────────────────────────────────┐
│ [📏 口径] 租金收入口径定义                          0.92    │
│ payment.amount 汇总值，排除 NULL 与退款记录...    [展开 ▸]  │
├────────────────────────────────────────────────────────────┤
│ [📏 口径] 月度统计口径                              0.85    │
│ 按 payment_date 的月份分组，时区按 UTC...         [展开 ▸]  │
├────────────────────────────────────────────────────────────┤
│ [📈 指标] 月度活跃客户数                            0.87    │
│ 当月有至少一笔有效 rental 记录的去重 customer...   [展开 ▸]  │
├────────────────────────────────────────────────────────────┤
│ [📖 术语] Pagila 业务术语表                          0.71    │
│ rental=租赁记录，payment=支付记录，inventory=库存... [展开 ▸]│
└────────────────────────────────────────────────────────────┘
```

### 5.4 分组展示模式

当同一类型的参考有多条时，以类型为小标题分组：

```
── 语义参考 ──────────────────────────────────── 4 条 ──

  口径（2 条）
  ┌──────────────────────────────────────────────────────────┐
  │ [口径] 租金收入口径定义                          0.92     │
  │ payment.amount 汇总值，排除 NULL...              [展开 ▸] │
  ├──────────────────────────────────────────────────────────┤
  │ [口径] 月度统计口径                              0.85     │
  │ 按 payment_date 的月份分组...                    [展开 ▸] │
  └──────────────────────────────────────────────────────────┘

  指标（1 条）
  ┌──────────────────────────────────────────────────────────┐
  │ [指标] 月度活跃客户数                            0.87     │
  │ 当月有至少一笔有效 rental 记录...               [展开 ▸]  │
  └──────────────────────────────────────────────────────────┘

  术语（1 条）
  ┌──────────────────────────────────────────────────────────┐
  │ [术语] Pagila 业务术语表                          0.71     │
  │ rental=租赁记录...                              [展开 ▸]  │
  └──────────────────────────────────────────────────────────┘
```

> **简化模式**：当总条数 ≤ 3 条时不分组，直接平铺列表（如 5.3 所示）；> 3 条时按类型分组（如 5.4 所示），减少视觉噪音。

### 5.5 内容展开交互

每条参考的 `content` 可能较长，默认显示前 2 行（约 80 字符），超出显示「展开 ▸」：

```
折叠态:
│ [口径] 租金收入口径定义                          0.92    │
│ payment.amount 汇总值，排除 NULL 与退款记录...    [展开 ▸] │

展开态:
│ [口径] 租金收入口径定义                          0.92    │
│ payment.amount 汇总值，排除 NULL 与退款记录。               │
│ 统计范围限定在 2007 年的有效支付。退款定义为 amount < 0。   │
│ 多币种情况下统一按 USD 换算...                              │
│                                                  [收起 ▾] │
```

- 截断：`line-clamp-2`（Tailwind 插件）
- 展开按钮：`text-xs text-[var(--color-primary)] hover:underline`

### 5.6 移动端适配

移动端单列平铺，标签与标题换行显示：

```
┌─────────────────────────────────────┐
│ [口径]                              │
│ 租金收入口径定义              0.92  │
│ payment.amount 汇总值...  [展开 ▸]  │
└─────────────────────────────────────┘
```

---

## 6. 复杂度路由展示组件（ComplexityRoutePanel）

### 6.1 设计说明

展示 Agent 的复杂度判定结果，让用户知道问题被归为什么难度、用了什么模型。

### 6.2 等级标签配色

| level | 中文标签 | 标签背景 | 标签文字 | 图标 |
|-------|----------|----------|----------|------|
| `simple` | 简单 | `bg-[var(--color-success-light)]` | `text-[var(--color-success)]` | `Zap` |
| `standard` | 标准 | `bg-blue-50` | `text-blue-700` | `Activity` |
| `complex` | 复杂 | `bg-orange-50` | `text-orange-700` | `Flame` |

### 6.3 ASCII 线框图

```
── 复杂度路由 ──────────────────────────────────────────
┌────────────────────────────────────────────────────────────┐
│ [🔥 复杂]   Top-K: 20      模型: gpt-4o-mini               │
│                                                            │
│ 涉及 3 表 JOIN + 时间窗口聚合 + HAVING 过滤，               │
│ 判定为复杂查询，使用高强度模型与最大检索深度。               │
└────────────────────────────────────────────────────────────┘
```

### 6.4 布局说明

| 区域 | 内容 | 样式 |
|------|------|------|
| 第一行 | 等级标签 + Top-K + 模型名 | `flex flex-wrap items-center gap-3` |
| 等级标签 | `[图标] 中文标签` | 见 6.2 配色，`rounded-md px-2.5 py-1 text-xs font-medium` |
| Top-K | `Top-K: {top_k}` | `text-sm text-[var(--color-text-secondary)]`，`K` 值用 `font-mono font-medium text-[var(--color-text-primary)]` |
| 模型名 | `模型: {model_used}` | `text-sm text-[var(--color-text-secondary)]`，模型名用 `font-mono text-[var(--color-text-primary)]` |
| 第二行 | 路由原因 | `text-sm text-[var(--color-text-secondary)] mt-2 leading-relaxed` |

### 6.5 简单查询示例

```
┌────────────────────────────────────────────────────────────┐
│ [⚡ 简单]   Top-K: 5       模型: gpt-4o-mini                │
│                                                            │
│ 单表查询无聚合，判定为简单查询，使用轻量模型快速响应。        │
└────────────────────────────────────────────────────────────┘
```

### 6.6 移动端适配

移动端第一行内容换行排列：

```
┌─────────────────────────────────────┐
│ [🔥 复杂]                            │
│ Top-K: 20    模型: gpt-4o-mini       │
│                                     │
│ 涉及 3 表 JOIN + 时间窗口聚合...     │
└─────────────────────────────────────┘
```

---

## 7. 修复历史展示组件（RepairHistoryTimeline）

### 7.1 设计说明

以时间线样式展示修复过程，每次修复显示错误类型、修复策略、SQL 指纹。仅在 `repair_history` 非空时展示。

- 时间线从上到下，每个节点代表一次尝试
- 最后一个节点标注成功 `✓` 或失败 `✕`
- `attempt` 编号从 1 开始

### 7.2 ASCII 线框图

```
── 修复历史 ────────────────────────────── 2 次修复 ──
┌────────────────────────────────────────────────────────────┐
│                                                            │
│  ●  第 1 次尝试                                             │
│  │  ┌──────────────────────────────────────────────────┐   │
│  │  │ 错误类型  [SCHEMA_ERROR]                          │   │
│  │  │ 修复策略  移除了不存在的字段 film.replacement_cost  │   │
│  │  │ SQL 指纹  sel_film_pmt_join_v1            [📋]    │   │
│  │  └──────────────────────────────────────────────────┘   │
│  │                                                          │
│  ●  第 2 次尝试                                             │
│     ┌──────────────────────────────────────────────────┐   │
│     │ 错误类型  [SYNTAX_ERROR]                          │   │
│     │ 修复策略  补全 GROUP BY 子句                        │   │
│     │ SQL 指纹  sel_film_pmt_join_v2            [📋]    │   │
│     └──────────────────────────────────────────────────┘   │
│     ✓ 最终成功                                              │
│                                                            │
└────────────────────────────────────────────────────────────┘
```

### 7.3 时间线节点样式

| 元素 | 样式 |
|------|------|
| 节点圆点 `●` | `h-2.5 w-2.5 rounded-full bg-[var(--color-primary)]`，已修复的节点用 `bg-[var(--color-warning)]` |
| 连接线 `│` | `w-0.5 bg-[var(--color-border)]`，从节点底部延伸到下一个节点 |
| 节点标题 | `text-sm font-medium text-[var(--color-text-primary)]` |
| 详情卡片 | `rounded-md border border-[var(--color-border)] bg-white p-3 ml-4 space-y-1.5` |
| 字段标签 | `text-xs font-medium text-[var(--color-text-tertiary)]`，宽度固定 `w-16` |
| 字段值 | `text-sm text-[var(--color-text-secondary)]`，SQL 指纹用 `font-mono` |

### 7.4 错误类型标签配色

错误类型用语义色标签，沿用 [03-visual-style.md](./03-visual-style.md) 语义色：

| 错误类型分类 | 标签背景 | 标签文字 |
|-------------|----------|----------|
| `SYNTAX_ERROR` / `DIALECT_ERROR` | `bg-amber-50` | `text-amber-700` |
| `SCHEMA_ERROR` | `bg-orange-50` | `text-orange-700` |
| `BUSINESS_KNOWLEDGE_MISSING` / `AMBIGUOUS_SEMANTICS` | `bg-blue-50` | `text-blue-700` |
| `CONNECTION_ERROR` / `TIMEOUT` | `bg-red-50` | `text-red-700` |
| `DUPLICATE_SQL` / `UNKNOWN` | `bg-gray-100` | `text-gray-600` |

标签样式：`inline-flex items-center rounded px-1.5 py-0.5 text-xs font-medium font-mono`

### 7.5 最终状态标记

| 状态 | 标记 | 样式 |
|------|------|------|
| 最终成功 | `✓ 最终成功` | `text-[var(--color-success)] font-medium`，图标 `CheckCircle` |
| 最终失败 | `✕ 未能修复` | `text-[var(--color-error)] font-medium`，图标 `XCircle` |

> 最终状态标记仅在时间线最后一个节点下方显示。

### 7.6 SQL 指纹复制

每个详情卡片右侧有复制按钮，点击复制 `fingerprint` 到剪贴板：

```
│ SQL 指纹  sel_film_pmt_join_v1            [📋]    │
```

- 复制按钮样式：`text-[var(--color-text-tertiary)] hover:text-[var(--color-text-primary)]`
- 复制成功：图标变为 `Check`（绿色），2 秒后恢复

### 7.7 移动端适配

移动端详情卡片去掉左侧缩进，直接占满宽度：

```
  ●  第 1 次尝试
  │  ┌───────────────────────────────┐
  │  │ 错误类型  [SCHEMA_ERROR]       │
  │  │ 修复策略  移除了不存在的字段... │
  │  │ 指纹  sel_film_pmt_join_v1 [📋]│
  │  └───────────────────────────────┘
  │
  ●  第 2 次尝试
     ...
     ✓ 最终成功
```

---

## 8. 子区块展开/折叠策略

参考信息区内部 4 个子区块各自独立可折叠，默认展开状态如下：

| 子区块 | 默认状态 | 展示条件 |
|--------|----------|----------|
| 候选表 | 默认展开 | `schema_candidates` 非空 |
| 语义参考 | 默认展开 | `semantic_references` 非空 |
| 复杂度路由 | 默认展开 | `complexity_route` 非空 |
| 修复历史 | 默认折叠（`repair_count > 0` 时展开） | `repair_history` 非空 |

> **理由**：候选表、语义参考、复杂度路由是用户最想看的可解释性信息，默认展开；修复历史较冗长，仅在有过修复时默认展开，否则用户主动点击查看。

### 子区块折叠态

```
── 候选表 ────────────────────────────────────── 5 张表 ── ▸
```

点击 `▸` 展开为 `▾`。

---

## 9. 交互流程

### 9.1 参考信息区展开/折叠

```
状态：查询成功，QueryResultCard 已渲染
用户看到：
  - 结果表格/图表正常展示
  - 下方「参考信息」折叠面板默认展开，显示 4 个子区块
用户操作：点击「参考信息」标题栏
系统反馈：
  - chevron 图标旋转（▸ → ▾）
  - 内容区高度动画展开/折叠（transition-all duration-200）
  - 折叠后只显示标题栏 + 计数
```

### 9.2 语义参考内容展开

```
状态：语义参考列表展示，某条 content 被截断
用户看到：内容前 2 行 + [展开 ▸]
用户操作：点击 [展开 ▸]
系统反馈：
  - 内容完整展示（移除 line-clamp-2）
  - 按钮变为 [收起 ▾]
用户操作：点击 [收起 ▾]
系统反馈：内容恢复截断状态
```

### 9.3 SQL 指纹复制

```
状态：修复历史时间线展示
用户看到：每条修复记录的 SQL 指纹旁有 [📋] 复制按钮
用户操作：点击复制按钮
系统反馈：
  - 图标变为 ✓（绿色）
  - 指纹已写入剪贴板
  - Toast 提示「指纹已复制」（右上角，3 秒消失）
  - 2 秒后图标恢复为 📋
```

### 9.4 候选表行悬停

```
状态：候选表展示
用户操作：鼠标悬停某一行
系统反馈：
  - 行背景变为 bg-[var(--color-bg-subtle)]
  - （选中行悬停保持 success-light 背景）
```

### 9.5 完整查询流程中的参考信息渲染时序

```
用户提交问题
    │
    ▼
LOADING（骨架屏，不含参考信息）
    │
    ▼ 收到响应，status = SUCCEEDED_*
    │
    ├─► 渲染状态卡片
    ├─► 渲染结果表格/图表
    ├─► 检查扩展字段：
    │     ├─ schema_candidates 非空？→ 渲染候选表
    │     ├─ semantic_references 非空？→ 渲染语义参考
    │     ├─ complexity_route 非空？→ 渲染复杂度路由
    │     └─ repair_history 非空？→ 渲染修复历史
    │     （任一非空 → 渲染参考信息区容器）
    ├─► 渲染 SQL 折叠区
    └─► 渲染元信息折叠区
```

> **渐进渲染**：参考信息区与结果表格同时渲染，不做延迟加载。若后端返回数据量大导致渲染卡顿，可考虑用 `requestIdleCallback` 延迟渲染参考信息区。

---

## 10. 空状态与边界处理

### 10.1 后端未返回扩展字段

```
QueryResultCard（无参考信息区，退化为现有行为）：
┌──────────────────────────────────────────────────────┐
│ ① 状态卡片                                            │
├──────────────────────────────────────────────────────┤
│ ② 结果展示区                                          │
├──────────────────────────────────────────────────────┤
│ ④ SQL 折叠区                                          │  ← 无 ③ 参考信息区
├──────────────────────────────────────────────────────┤
│ ⑤ 元信息折叠区                                        │
└──────────────────────────────────────────────────────┘
```

### 10.2 部分扩展字段缺失

| 场景 | 处理 |
|------|------|
| 只有 `schema_candidates`，无其他 | 参考信息区只展示「候选表」子区块 |
| 只有 `complexity_route` | 参考信息区只展示「复杂度路由」子区块 |
| `repair_count = 0` 且无 `repair_history` | 不展示「修复历史」子区块 |
| `schema_candidates = []`（空数组） | 不展示「候选表」子区块 |
| `score` 字段为 `null` 或 `undefined` | 相关性列显示 `—` |

### 10.3 数据量过大

| 场景 | 处理 |
|------|------|
| 候选表 > 10 张 | 只展示前 10 张，底部显示「还有 N 张候选表 [查看全部 ▸]」 |
| 语义参考 > 20 条 | 只展示前 20 条，底部显示「还有 N 条参考 [查看全部 ▸]」 |
| 修复历史 > 5 次 | 时间线默认折叠，只显示首尾 2 条，中间显示「省略 N 次尝试」 |

---

## 11. 文件清单与组件结构

### 11.1 新增文件

```
frontend/
├── lib/
│   └── types.ts                          # 修改：新增 SchemaCandidate 等类型
└── components/
    └── workbench/
        ├── ReferenceInfo.tsx             # 新增：参考信息区容器（Collapsible）
        ├── SchemaCandidatesTable.tsx     # 新增：候选表展示
        ├── SemanticReferencesGroup.tsx   # 新增：语义参考分组展示
        ├── ComplexityRoutePanel.tsx      # 新增：复杂度路由展示
        └── RepairHistoryTimeline.tsx     # 新增：修复历史时间线
```

### 11.2 修改文件

```
frontend/
├── lib/types.ts                                    # 新增 4 个接口 + 扩展 QueryResponse
└── components/workbench/QueryResultCard.tsx        # 在结果展示区和 SQL 折叠区之间插入 <ReferenceInfo />
```

### 11.3 QueryResultCard 修改示意

```tsx
// QueryResultCard.tsx 修改要点
import { ReferenceInfo } from "./ReferenceInfo";

export function QueryResultCard({ response }: QueryResultCardProps) {
  // ... 现有逻辑 ...

  // 判断是否有参考信息可展示
  const hasReferenceInfo =
    isSuccess(response) &&
    (!!response.schema_candidates?.length ||
      !!response.semantic_references?.length ||
      !!response.complexity_route ||
      !!response.repair_history?.length);

  return (
    <div className="...">
      {/* ① 状态卡片 */}
      <div className="..."><StatusBadge ... /></div>

      {/* ② 结果展示区 */}
      <div className="..."><Tabs ... />...</div>

      {/* ③ 参考信息区（新增） */}
      {hasReferenceInfo && <ReferenceInfo response={response} />}

      {/* ④ SQL 折叠区 */}
      {response.sql && <SqlCollapse sql={response.sql} />}

      {/* ⑤ 元信息折叠区 */}
      <MetaInfo response={response} />
    </div>
  );
}
```

---

## 12. ⚠️ 需要后端扩展的接口契约清单

### 12.1 QueryResponse 扩展字段

后端需在 `app/api/models.py` 的 `QueryResponse` 中新增以下可选字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| `schema_candidates` | `list[SchemaCandidate]` | Schema Linking 候选表，按 score 降序 |
| `semantic_references` | `list[SemanticReference]` | 业务知识 RAG 命中片段 |
| `complexity_route` | `ComplexityRoute` | 复杂度路由决策详情 |
| `repair_history` | `list[RepairHistoryEntry]` | 修复过程记录 |

### 12.2 新增 Pydantic 模型（建议）

```python
# app/api/models.py 新增

class SchemaCandidate(BaseModel):
    table_name: str
    schema: str
    fields: list[str]
    score: float                    # 0.0 - 1.0
    source: Literal["bm25", "embedding", "rerank"]
    selected: bool                  # 是否最终选入 SQL

class SemanticReference(BaseModel):
    type: Literal["caliber", "metric", "glossary", "few_shot"]
    title: str
    content: str
    score: float                    # 0.0 - 1.0

class ComplexityRoute(BaseModel):
    level: Literal["simple", "standard", "complex"]
    top_k: int                      # 5 / 10 / 20
    model_used: str
    reason: str

class RepairHistoryEntry(BaseModel):
    attempt: int                    # 1-based
    error_type: str
    fix_strategy: str
    fingerprint: str
```

### 12.3 后端实现要点（供后端参考，前端不实现）

| 扩展项 | 后端数据来源 | 安全考量 |
|--------|-------------|----------|
| `schema_candidates` | Schema Linking 阶段的候选表探测结果 + 物化结果 | 候选表可能暴露库结构，需确认是否过滤敏感表 |
| `semantic_references` | 业务知识 RAG 检索命中的知识片段 | 知识库内容可能含商业机密，需脱敏 |
| `complexity_route` | 复杂度分类器的判定结果 + 模型路由配置 | `model_used` 暴露模型名，生产环境可考虑脱敏 |
| `repair_history` | 修复循环中每次尝试的错误与修复记录 | `fingerprint` 可能暴露 SQL 结构，但风险较低 |

### 12.4 兼容性要求

- 所有新增字段**必须可选**（`Optional` / 默认 `None`），确保旧版前端不受影响
- 后端可通过 `debug=true` 或新增 `include_references=true` 请求参数控制是否返回扩展字段（当前 `debug` 固定无权限，建议新增独立参数）
- 字段值为空时返回 `null` 或空数组 `[]`，不省略字段名

---

## 13. 设计决策记录

| 决策 | 选择 | 理由 |
|------|------|------|
| 参考信息区默认展开还是折叠 | **默认展开** | 用户明确要求这是核心增强，可解释性是首要诉求 |
| 参考信息区位置 | 结果展示区之后、SQL 之前 | 遵循「结果优先」原则，表格仍是第一焦点；参考信息是结果的「依据」，逻辑上紧随结果 |
| 子区块是否独立折叠 | **独立折叠** | 4 个子区块信息量大，允许用户按需收起不关心的部分 |
| 修复历史默认状态 | 有修复时展开，无修复时隐藏 | 无修复时展示空时间线无意义 |
| 来源标签是否用颜色区分 | **是** | bm25/embedding/rerank 是技术概念，颜色区分降低认知成本 |
| 内容截断行数 | 2 行（约 80 字符） | 平铺可读性与信息密度 |
| 移动端候选表展示 | 卡片化 | 表格列多，横滚体验差，卡片更适合窄屏 |
