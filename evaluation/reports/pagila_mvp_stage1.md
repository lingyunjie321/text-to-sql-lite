# Pagila Stage 1 正式候选报告（候选 1）

- 运行日期：2026-08-01
- 报告版本：`stage1-report-v1`
- baseline 版本：`stage1-freeze-v1`
- 正式候选运行：`1/1`（按两次运行终局规则，未发现可由非 Gold 测试证明的通用
  实现缺陷，不启动第二次运行）
- 自动证据：`11/18`
- 独立逐条审核：`pending`（18 条均未审核）
- Gold 状态：`draft=18 / verified=0`
- Stage 1 发布资格：`not_passed`（自动证据未全过，且独立审核未完成）

## 正式冻结

- baseline ID：
  `a7b3bd95e68810874b4f7ebcbc54bd1dcec41d35a6a5489c9090fbefafa29628`
- model configuration SHA-256：
  `bd66c666151db8c3236b2454696d23b20cd60fbff8ecf37c46d45c54abb422db`
- controlled code SHA-256：
  `1f9e93e6749c2c8e081e54ab5c16679c4c7c3860fbea063159c9257c52b3a921`
- Pagila：`pagila-v3.1.0`（commit `fef9675714cfba1756df4719b5e36075a7ddf90e`）
- PostgreSQL：`16.14 (Debian 16.14-1.pgdg12+1)`
- database schema SHA-256：
  `74de0ad271945ff3ce8e21d9065d1c0178f01994a8f25c613afebcebed5933b2`
- normalized database dump SHA-256：
  `e584f0beb3817d1a6f3e35518192ba66cc8b14c50df08c34527d5b15e77bd567`
- semantic manifest SHA-256：
  `4f91262d600de09c42b38a0cbef7e0c7f9b6f724c9bd4b9c8fa27a625e61673f`
- Gold 文件 SHA-256：
  `049e048b821e949936c1793d441f7adcda4660f10f8d0acf63e4f766a9726c22`
- Gold status-neutral SHA-256：
  `a00a8ec7496fc4e1533b2773e0267d555357a80be435a02dd70981d76ddb40d7`
- 三模型路由：simple=`deepseek-v4-flash`、standard=`deepseek-chat-v4`、
  complex=`deepseek-reasoner`（用户确认为正式验收配置）

## 候选 1 结果

| Case | 自动结果 | 脱敏结论 |
|---|---|---|
| PG-MVP-001 | `EVALUATION_PASS` | 完整执行、召回、比较、终态和 Trace 证据通过 |
| PG-MVP-002 | `EVALUATION_PASS` | 完整执行、召回、比较、终态和 Trace 证据通过 |
| PG-MVP-003 | `EVALUATION_FINAL_STATUS_MISMATCH` | 生成 SQL 命中授权/安全门，终态 `REJECTED_SECURITY`（`PERMISSION_DENIED`），零执行 |
| PG-MVP-004 | `EVALUATION_PASS` | 完整执行、召回、比较、终态和 Trace 证据通过 |
| PG-MVP-005 | `COMPARATOR_COLUMN_MISMATCH` | 已执行（6/6 行），结果列与 Gold 不一致 |
| PG-MVP-006 | `EVALUATION_PASS` | 完整执行、召回、比较、终态和 Trace 证据通过 |
| PG-MVP-007 | `EVALUATION_PASS` | 完整执行、召回、比较、终态和 Trace 证据通过 |
| PG-MVP-008 | `EVALUATION_FINAL_STATUS_MISMATCH` | 生成 SQL 命中授权/安全门，终态 `REJECTED_SECURITY`（`PERMISSION_DENIED`），零执行 |
| PG-MVP-009 | `EVALUATION_FINAL_STATUS_MISMATCH` | 生成 SQL 命中授权/安全门，终态 `REJECTED_SECURITY`（`PERMISSION_DENIED`），零执行 |
| PG-MVP-010 | `EVALUATION_FINAL_STATUS_MISMATCH` | `FAILED_INTERNAL`；诊断复现为 standard route 真实调用返回 `LLM_HTTP_ERROR`，未产生 SQL |
| PG-MVP-011 | `EVALUATION_FINAL_STATUS_MISMATCH` | 同 010：`FAILED_INTERNAL` / `LLM_HTTP_ERROR` |
| PG-MVP-012 | `EVALUATION_FINAL_STATUS_MISMATCH` | 同 010：`FAILED_INTERNAL` / `LLM_HTTP_ERROR` |
| PG-MVP-013 | `EVALUATION_PASS` | 完整执行、召回、比较、终态和 Trace 证据通过 |
| PG-MVP-014 | `EVALUATION_PASS` | 合法空结果及完整执行证据通过 |
| PG-MVP-015 | `EVALUATION_PASS` | 预期安全拒绝、零执行、零修复 |
| PG-MVP-016 | `EVALUATION_PASS` | 预期安全拒绝、零执行、零修复 |
| PG-MVP-017 | `EVALUATION_PASS` | 预期安全拒绝、零执行、零修复 |
| PG-MVP-018 | `EVALUATION_PASS` | 初始 SQL 修复后成功（`SUCCEEDED_REPAIRED`） |

## 失败归类与终局判定

- 3 个 Provider HTTP 错误（PG-MVP-010/011/012）：外部模型服务瞬时失败，
  工作流按设计以 `FAILED_INTERNAL` 收尾，不盲重试；不属于可由非 Gold 测试
  证明的通用实现缺陷，不触发第二次运行。
- 2 个权限门拒绝（PG-MVP-003/008）：模型输出超出授权范围，安全门正确拒绝；
  属模型输出质量问题。
- 1 个列契约差异（PG-MVP-005）：模型输出列与 Gold 不一致；属模型输出质量
  问题。
- 未按失败 Case 修改 Prompt、Comparator、后处理或语义元数据；未重复抽样
  择优；失败 Case 保持 `draft`。

## 真实环境证据

- 真实 Pagila 容器：锁定镜像 PostgreSQL 16.14 + Pagila 3.1.0 快照，
  `film` 行数 1000，只读角色 `text_to_sql_reader` 存在。
- 真实 Embedding：`text-embedding-v4`（1024 维）在候选中构建授权 Schema
  索引；Trace 显示混合检索成功（诊断 Case：Embedding 约 1879ms，表/字段
  1/14，无降级）。
- 真实生成模型：三模型配置已冻结；候选运行中存在真实模型调用（多个 Case
  产生 token 消耗并生成可执行 SQL）。逐 Case 路由摘要仅保留在 Trace 哈希中，
  原始 Trace 按安全设计不落盘。
- 集成回归：真实 Pagila 上 `78 passed / 9 skipped / 0 failed`（含临时只读
  角色自清理）；测试后 `codex_stage1_%` 残留角色数为 `0`。

## 下一步

对 18 条 Case 完成独立逐条审核（`review-case` approve/reject），审核通过后
执行 `verify-case` 更新 Gold 状态。只有 `18/18` 自动证据且 `18/18` 独立审核
通过，才能将 Stage 1 标记为真实环境验证完成。
