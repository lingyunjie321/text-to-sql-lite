# Pagila MVP Stage 10 最终资格报告

## 结论

- Stage 10 implementation: `completed`
- MVP release qualification: `not_passed`
- 正式候选运行：`1/2`
- 自动证据：`12/18`
- 独立逐条审核：`12 approved / 6 rejected`
- Gold 状态：`draft=18 / verified=0`

候选 1 未显示可由非 Gold 合成证据证明的通用 blocking/high 实现缺陷。
按照冻结后的两次运行终局规则，候选 1 因此成为最终资格结果；未启动无依据的
随机重试，也未根据当前 Gold 修改 Prompt、Comparator、后处理或语义元数据。

## 正式冻结

- baseline version：`stage10-freeze-v3`
- baseline ID：
  `3f2c562dab63fcafb8a02196f24b3330cb5dfe2b72573c673aea08f7fc1a6002`
- Pagila commit：`fef9675714cfba1756df4719b5e36075a7ddf90e`
- PostgreSQL：`16.14 (Debian 16.14-1.pgdg12+1)`
- database schema SHA-256：
  `74de0ad271945ff3ce8e21d9065d1c0178f01994a8f25c613afebcebed5933b2`
- normalized database dump SHA-256：
  `e584f0beb3817d1a6f3e35518192ba66cc8b14c50df08c34527d5b15e77bd567`
- semantic manifest SHA-256：
  `4f91262d600de09c42b38a0cbef7e0c7f9b6f724c9bd4b9c8fa27a625e61673f`
- view definitions SHA-256：
  `ecfa595e24b8f6d1103487fca39226bbfef183c0558a25d266fa9f2e2e501b57`
- controlled code SHA-256：
  `c5704f58a182fc86b62838de77872514ab4df1ac2807fb3404fe80db9d88b3c4`
- Gold file SHA-256：
  `049e048b821e949936c1793d441f7adcda4660f10f8d0acf63e4f766a9726c22`
- Gold status-neutral SHA-256：
  `a00a8ec7496fc4e1533b2773e0267d555357a80be435a02dd70981d76ddb40d7`

冻结基线同时绑定 21 个行为相关安装包版本、非秘密数据库执行参数、
非秘密模型配置摘要及 Prompt、Provider、Comparator、Evidence、Report
契约版本。静态冻结和报告外部基线匹配均通过。

## 候选 1 结果

| Case | 自动结果 | 独立审核 | 脱敏结论 |
|---|---|---|---|
| PG-MVP-001 | `EVALUATION_PASS` | approved | 完整执行、召回、比较、终态和 Trace 证据通过 |
| PG-MVP-002 | `EVALUATION_PASS` | approved | 完整执行、召回、比较、终态和 Trace 证据通过 |
| PG-MVP-003 | `EVALUATION_PASS` | approved | 完整执行、召回、比较、终态和 Trace 证据通过 |
| PG-MVP-004 | `EVALUATION_PASS` | approved | 完整执行、召回、比较、终态和 Trace 证据通过 |
| PG-MVP-005 | `COMPARATOR_COLUMN_MISMATCH` | rejected | 结果列契约不一致 |
| PG-MVP-006 | `EVALUATION_PASS` | approved | 完整执行、召回、比较、终态和 Trace 证据通过 |
| PG-MVP-007 | `COMPARATOR_COLUMN_MISMATCH` | rejected | 结果列契约不一致 |
| PG-MVP-008 | `EVALUATION_FINAL_STATUS_MISMATCH` | rejected | 候选命中权限门并被零执行安全拒绝，终态不符合预期 |
| PG-MVP-009 | `EVALUATION_FINAL_STATUS_MISMATCH` | rejected | 候选命中权限门并被零执行安全拒绝，终态不符合预期 |
| PG-MVP-010 | `EVALUATION_FIELD_RECALL_FAILED` | rejected | 必需字段未完整覆盖 |
| PG-MVP-011 | `EVALUATION_PASS` | approved | 执行、字段命中与完整结果比较通过；JOIN recall 仅为诊断项 |
| PG-MVP-012 | `EVALUATION_FIELD_RECALL_FAILED` | rejected | 必需字段未完整覆盖，且结果列不一致 |
| PG-MVP-013 | `EVALUATION_PASS` | approved | 完整执行、召回、比较、终态和 Trace 证据通过 |
| PG-MVP-014 | `EVALUATION_PASS` | approved | 合法空结果及完整执行证据通过 |
| PG-MVP-015 | `EVALUATION_PASS` | approved | 预期安全拒绝、零执行、零修复 |
| PG-MVP-016 | `EVALUATION_PASS` | approved | 预期安全拒绝、零执行、零修复 |
| PG-MVP-017 | `EVALUATION_PASS` | approved | 预期安全拒绝、零执行、零修复 |
| PG-MVP-018 | `EVALUATION_PASS` | approved | 一次有限修复后执行、召回、比较和 Trace 证据通过 |

聚合指标：

- 首次成功：`8`
- 修复后成功：`1`
- 安全 Case 通过：`3/3`
- Gold 结果比较通过：`9`
- 输入/输出 token：`19004 / 4328`
- Workflow 总耗时：`56334.332 ms`
- 数据库总耗时：`40.503 ms`

## 独立审核与终局判断

唯一集中初审报告的 `1 blocking / 5 high` 均已修复；唯一最终复审确认
`blocking=0 / high=0`，聚焦回归 `118 passed`。候选报告随后逐条审核
18 个 Case，审核结论与自动结果完全一致。

六个失败 Case 的 Gold 均已成功校验和执行，安全门禁按设计工作。现有脱敏证据
只表明候选模型输出未满足冻结列契约、必需字段覆盖或授权对象边界，不足以证明
通用实现缺陷。依据终局规则，不运行候选 2，发布资格记为 `not_passed`。

## 最终工程验证

- 单元测试：`581 passed`
- 集成测试：`73 passed`
- 安全测试：`111 passed`
- 单进程完整回归：`765 passed`
- FastAPI + 固定 Stub + 真实 Pagila：首次执行、合法空结果、一次修复闭环、
  危险 SQL 零执行拒绝均通过
- `python -m compileall`：通过
- `pip check`：通过
- Docker Compose 配置检查：通过
- `git diff --check`：通过
- 受保护项目规格、测试规格和 Gold 非状态内容哈希：保持不变

## 当前限制

- 冻结模型在本次真实候选中未达到 18/18，不能声明 MVP 发布验收通过。
- `temperature=0` 仍不保证第三方模型输出字节级确定性；本报告不通过重复抽样
  选择结果。
- FastAPI HTTP 闭环按测试规格使用固定 Stub 与真实 Pagila；真实 Provider
  已通过同一 Workflow 评测路径运行，但未将 Case 内容再次经 HTTP smoke
  发送到未明示的外部目的地。
- 未实现在线评测服务、Dashboard、OTel backend、多模型路由、多数据源、
  Few-shot、缓存或训练集导出。
