# Text-to-SQL 增强阶段 1 资格报告

## 报告状态

- 记录日期：2026-07-30
- 更新日期：2026-08-01
- 阶段：增强阶段 1——检索与路由增强
- 资格结论：`not_passed`
- 报告性质：进行中的资格快照，不是发布证明

| 范围 | `functional_complete` | `integration_complete` | `real_environment_validated` | 结论 |
|---|---:|---:|---:|---|
| Stage 1 总体 | `true` | `false` | `false` | 功能完成；集成与真实环境验证未完成 |
| Embedding Provider 单项 | `true` | `true` | `true` | Provider 契约与单次真实调用通过 |

Embedding Provider 的单项通过不得解释为授权索引、混合检索、RRF、Rerank、
上下文裁剪、多模型路由或 Pagila E2E 已完成真实环境验证。

## 2026-08-01 更新：正式配置确认与冻结重建

用户确认当前 `.env` 的三模型组合即为正式验收配置：

- simple：`deepseek-v4-flash`
- standard：`deepseek-chat-v4`
- complex：`deepseek-reasoner`

据此已完成：

1. 从当前 `.env` 派生配置重建
   `evaluation/stage1_selected_configuration.json`，三条 route 现在分别绑定
   三个不同的模型配置摘要（不再共享同一模型）；Embedding batch 同步为当前
   配置值。
2. 重建 `evaluation/stage1_calibration_freeze.json`，并验证
   env-derived `public_configuration == selected.public_configuration`、
   `freeze.stage1_config_sha256 == selected.stage1_config_sha256`、
   `freeze.controlled_code_sha256 == 当前工作树受控代码摘要`。
3. 完成计划 Task 1 缺失的三项 complexity mutation checks，每项均被测试
   拦截：
   - MEDIUM Top-K 从 10 改为 20 → 3 个测试失败；
   - 任意 fallback JOIN 视为相关 → 1 个测试失败；
   - 理由码乱序返回 → 5 个测试失败；
   - 恢复后 `tests/unit/test_complexity_routing.py` 24 项全过。
4. 全量回归：单元与安全 `1173 passed, 0 failed`；synthetic development /
   calibration 完整 Workflow 与质量门 `3 passed`（6/6 + 6/6）；
   `compileall`、`pip check`、`git diff --check` 通过。

契约版本确认：`PROMPT_VERSION=stage1-retrieval-routing-v1`、
`BASELINE_VERSION=stage1-freeze-v1`、report 契约
`stage1-report-v1`，均已完成 Stage 1 迁移。

## 2026-08-01 更新（二）：正式候选

在用户批准的真实环境上执行唯一正式候选（18 条 Pagila Gold）：

- 真实 Pagila 容器（PostgreSQL 16.14 + Pagila 3.1.0，`film`=1000）已启动，
  baseline 已重建并绑定新 config/受控代码摘要：
  `a7b3bd95e68810874b4f7ebcbc54bd1dcec41d35a6a5489c9090fbefafa29628`。
- 自动证据：`11/18` 通过；失败 `7` 条：
  - PG-MVP-010/011/012：standard route 真实调用返回 `LLM_HTTP_ERROR`
    （外部模型服务瞬时失败；工作流按设计 `FAILED_INTERNAL`，不盲重试）；
  - PG-MVP-003/008：生成 SQL 超出授权范围，被安全门正确拒绝（零执行）；
  - PG-MVP-005：已执行（6/6 行），结果列与 Gold 不一致。
- 未发现可由非 Gold 测试证明的通用 blocking/high 实现缺陷，按两次运行终局
  规则不启动第二次运行；未按失败 Case 修改 Prompt、Comparator、后处理或
  语义元数据；失败 Case 保持 `draft`。
- 完整逐 Case 报告：
  `evaluation/reports/pagila_mvp_stage1.md` /
  `evaluation/reports/pagila_mvp_stage1.json`。
- 真实 Pagila 集成回归：`78 passed / 9 skipped / 0 failed`；测试后
  `codex_stage1_%` 残留角色数为 `0`。

本次候选证明了真实 Embedding 索引构建、混合检索、三模型路由与真实 Pagila
闭环可达；但自动证据未达 `18/18`，且 18 条 Case 独立逐条审核未完成，因此
`integration_complete` 与 `real_environment_validated` 保持 `false`。

## 已取得的确定性证据

最终确定性回归结果：

- 单元与安全回归：`1161 passed in 2.75s`；
- 本地 Stage 1 集成：synthetic 纵向闭环与多模型 Workflow
  `15 passed in 0.68s`；OpenAI-compatible Embedding loopback 首次因受限
  沙箱禁止绑定 `127.0.0.1` 而出现 2 个环境错误，在允许本地回环端口的环境
  以相同测试复跑后 `2 passed in 1.10s`；
- synthetic development：6/6 复杂度、字段选择和 JOIN 召回通过，无 Embedding
  或 Rerank 降级；
- synthetic calibration：6/6 复杂度、字段选择和 JOIN 召回通过，无降级；
  组合检索相对 BM25 有 9 个分桶提升且所有比较分桶不回退；
- 配置/冻结和正式评测装配聚焦回归：`32 passed in 0.59s`；
- `compileall`、`pip check` 和 `git diff --check` 通过。

随后发现本机已有健康的锁定 Pagila 容器。未读取现有数据库凭据，而是在容器内
创建随机只读临时角色、仅通过进程内 DSN 运行回归，并在测试退出时撤销授权和
删除角色。修复唯一未同步 deadline 参数的 API integration 适配器后，完整
integration 结果为 `91 passed in 7.42s`；清理后残留的
`codex_stage1_%` 角色数为 `0`。最终收口复跑结果为
`91 passed in 7.22s`。该结果证明数据库、Connector、API、Workflow、
评测和安全路径的本地真实 Pagila 集成通过，但没有生成新的 Pagila 正式候选。

非 Gold 输入和选定配置已经冻结：

| 冻结项 | 摘要 |
|---|---|
| Stage 1 配置 | `bd66c666151db8c3236b2454696d23b20cd60fbff8ecf37c46d45c54abb422db` |
| development 原始文件 | `0ce763b3122b09a6b6718975789122918e4594b455b35d51197a37b359b595f0` |
| development 规范化 | `c1746bea22d588578929b25afb1a3a29d13c7e978f5687e2b6352b7029668dd7` |
| calibration 原始文件 | `07070687fb39592e26b02fb21891b5108b38bc0f5337240de25a4df3ac638845` |
| calibration 规范化 | `d7e7d7d60a157ec78e00ba16fbf722dddd5552eb833863310a8d9ed95797b8bd` |
| 受控代码 | `1f9e93e6749c2c8e081e54ab5c16679c4c7c3860fbea063159c9257c52b3a921` |
| calibration baseline | `70f424307045b748b82e71c5b22707da14ad7d7da53c4143bf427dae62c8a4d6` |
| 当前 Pagila baseline | `a7b3bd95e68810874b4f7ebcbc54bd1dcec41d35a6a5489c9090fbefafa29628` |

正式 Pagila 入口现在要求实际 Embedding、完整 route runtime、selected
configuration、上述 calibration freeze 和当前受控代码摘要全部一致；缺失或漂移
会在执行 Case 前失败。旧 Stage 10 报告仍不能作为 Stage 1 证据。

契约标识已完成 Stage 1 迁移（`baseline_version=stage1-freeze-v1`、
`PROMPT_VERSION=stage1-retrieval-routing-v1`、report
`stage1-report-v1`）。`evaluation/pagila_baseline.json` 目前仍绑定上一份
selected configuration 与受控代码摘要，正式候选前必须用真实容器重建
Pagila baseline，使其与新的 config/受控代码摘要一致。

## 真实 Embedding 调用证据

确定性测试通过后，执行了恰好一次获批的真实 Embedding 调用：

| 项目 | 证据 |
|---|---|
| Provider 协议 | OpenAI-compatible |
| 服务区域 | 阿里云百炼中国北京区 |
| 模型 | `text-embedding-v4` |
| 配置维度 | `1024` |
| 调用次数 | `1` |
| 返回数量 | `1` |
| 响应校验 | 模型、数量/index、1024 维、有限值、非零范数全部通过 |
| 单项结论 | `embedding_provider.real_environment_validated=true` |

本报告不保存 API Key、原始 Base URL、请求文档、响应正文或任何向量值。真实
调用只证明 Provider 对该服务和配置的协议兼容性；尚未证明真实授权 Schema
索引的构建、版本隔离、检索质量或端到端 SQL 生成效果。

## 当前实现证据边界

代码中已经存在显式 `ComplexityRouteNode`、探测—路由—物化两遍 Schema
Linking、动态 5/10/20、Embedding 与 BM25 双路召回、RRF、可解释 Rerank、
上下文裁剪，以及服务端拥有的模型路由。生产启动按基础 LLM 配置与
`LLM_SIMPLE_`、`LLM_STANDARD_`、`LLM_COMPLEX_`、可选
`LLM_FALLBACK_` 覆盖构建运行时，声明不完整时 fail closed。
Workflow 现在把同一请求的剩余 deadline 下传给 metadata 与 execute，并由
PostgreSQL Connector 同时约束连接池等待和 statement timeout。无安全 BM25
路径时的标准 Embedding 致命失败会生成脱敏 Retrieval Trace，记录冻结版本、
失败码、候选计数与阶段耗时，不记录请求、Schema 标识或 Provider 私有详情。

2026-08-01 起选定配置中三条 route 分别绑定三个不同真实生成模型，路由行为
可达已由确定性测试证明；但仍未在正式候选中运行这些真实模型。本地真实
Pagila integration 已完成；真实授权 Schema Embedding 索引、正式候选和 Gold
独立审核仍未完成，因此本报告不把 Stage 1 标记为集成完成或真实环境验证完成。

## 尚未通过的门禁

Stage 1 三层状态分别还有未闭环项：

1. Functional：已完成（2026-08-01）。Prompt、baseline、report 和 evidence
   契约版本已迁移到 Stage 1 标识；三项 complexity mutation checks 已执行并
   被测试拦截；单元/安全与 synthetic 回归全绿。
2. Integration：形成新的 Stage 1 report/evidence 契约，并完成完整 focused
   diff 的独立 blocking/high 清零审查。
3. Real environment：正式候选已运行（自动 `11/18`，真实 Embedding 索引、
   混合检索与三模型路由均已实际执行），但未达到 `18/18` 自动证据，且 18 个
   Pagila Gold Case 的独立逐条审核证据未完成。

上述门禁全部满足并记录前：

```text
stage1.functional_complete=true
stage1.integration_complete=false
stage1.real_environment_validated=false
```

## 历史证据边界

`evaluation/reports/pagila_mvp_stage10.md` 和对应 JSON 是九节点 MVP 的历史
资格记录，其结论仍为 `not_passed`。Stage 1 已修改受控代码与配置，原 Stage 10
code hash 不能作为新 baseline；历史报告不得回写，也不得被引用为显式
ComplexityRoute、混合检索或多模型路由的通过证据。

## 安全声明

- 客户端不能指定 complexity、Top-K、Embedding、模型或上下文预算；
- 授权过滤必须先于 BM25 统计、Embedding 文档、融合、Rerank 和 Prompt；
- 所有生成或修复 SQL 仍必须经过权限、AST、函数、只读和执行边界；
- Gold SQL、字段、表、JOIN、结果、标签、fixture 和失败原因不得进入索引、
  Prompt、训练或调参；
- Trace、日志和本报告不得记录密钥、原始端点、问题、SQL、Schema 名称、
  Prompt、结果或向量。
