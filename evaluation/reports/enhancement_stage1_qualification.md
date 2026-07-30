# Text-to-SQL 增强阶段 1 资格报告

## 报告状态

- 记录日期：2026-07-30
- 阶段：增强阶段 1——检索与路由增强
- 资格结论：`not_passed`
- 报告性质：进行中的资格快照，不是发布证明

| 范围 | `functional_complete` | `integration_complete` | `real_environment_validated` | 结论 |
|---|---:|---:|---:|---|
| Stage 1 总体 | `false` | `false` | `false` | 尚未通过整阶段门禁 |
| Embedding Provider 单项 | `true` | `true` | `true` | Provider 契约与单次真实调用通过 |

Embedding Provider 的单项通过不得解释为授权索引、混合检索、RRF、Rerank、
上下文裁剪、多模型路由或 Pagila E2E 已完成真实环境验证。

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
| Stage 1 配置 | `a76ffcacb889f0bba10aabbe35f81d0e6ad2cfdceb49221a33864c2f89135bf8` |
| development 原始文件 | `0ce763b3122b09a6b6718975789122918e4594b455b35d51197a37b359b595f0` |
| development 规范化 | `c1746bea22d588578929b25afb1a3a29d13c7e978f5687e2b6352b7029668dd7` |
| calibration 原始文件 | `07070687fb39592e26b02fb21891b5108b38bc0f5337240de25a4df3ac638845` |
| calibration 规范化 | `d7e7d7d60a157ec78e00ba16fbf722dddd5552eb833863310a8d9ed95797b8bd` |
| 受控代码 | `e02e79d4f4dcb5ac847bd5f35153ed89076793b0c63c43c856a8a8b80081655a` |
| calibration baseline | `2b53e182b3b472fa75d92f931591d0d5feea5137e69f4e3b47698ddcb4e44782` |
| 当前 Pagila baseline | `5e4f9ee633cd7d7f753cc3f3667fcaa7030e25619eb059b48f125fb77e6b2d16` |

正式 Pagila 入口现在要求实际 Embedding、完整 route runtime、selected
configuration、上述 calibration freeze 和当前受控代码摘要全部一致；缺失或漂移
会在执行 Case 前失败。旧 Stage 10 报告仍不能作为 Stage 1 证据。

当前 Pagila baseline 虽已绑定 Stage 1 code/config，但
`baseline_version`、report 和 evidence 契约标识仍沿用 `stage10-*-v3`，
`PROMPT_VERSION` 也仍沿用旧 MVP 标识。设计要求这些契约分别升级，因此在明确
兼容依据或完成版本迁移、漂移测试和重新冻结前，它不能作为 Stage 1 正式候选
发布契约。

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

当前选定配置中三条 route 的模型配置摘要相同，因此只证明路由行为可达，不证明
至少两个真实生成模型已经运行。本地真实 Pagila integration 已完成；真实授权
Schema Embedding 索引、正式候选和 Gold 独立审核仍未完成，因此本报告不把
Stage 1 标记为功能完成、集成完成或真实环境验证完成。

## 尚未通过的门禁

Stage 1 三层状态分别还有未闭环项：

1. Functional：升级或以明确兼容证据确认 Prompt、baseline、report 和 evidence
   的 Stage 1 契约版本；完成计划中尚无记录的 complexity mutation checks。
2. Integration：形成新的 Stage 1 report/evidence 契约，并完成完整 focused
   diff 的独立 blocking/high 清零审查。
3. Real environment：使用真实 Embedding 服务构建并验证授权、版本隔离的
   Schema 索引；让至少两个不同真实生成模型通过不同复杂度 route；对 18 个
   Pagila Gold Case 运行一次新的正式候选并独立审核证据。

上述门禁全部满足并记录前：

```text
stage1.functional_complete=false
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
