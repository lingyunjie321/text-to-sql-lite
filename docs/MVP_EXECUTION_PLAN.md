# Text-to-SQL MVP Stage 3–10 执行台账

## 执行约束

- 当前分支：`codex/mvp-stages-3-10`
- 推送目标：`origin/codex/mvp-stages-3-10`
- 禁止合并或推送 `main`
- 阶段顺序：SQL 校验 → Schema Linking → SQL 生成 → 真实执行 →
  反思修复 → LangGraph Workflow → FastAPI → 评测与安全回归
- 每个阶段串行执行，并遵循测试先行、完整回归、独立审查、单独提交和推送。
- 受保护文件：
  - `docs/Text-to-SQL项目复现规格.md`
  - `docs/Text-to-SQL测试与验收规格.md`
  - `evaluation/cases/pagila_mvp.jsonl`
- 基线 SHA-256：
  - 主规格：
    `191f702f0bf78706ce6bf0ac09bca98bbc096c6d45ff06696887da7484ba513b`
  - 测试规格：
    `299e306461faeacbd40c208a7020b45a3e67545e54e7ee575549760a05a0a181`
  - Pagila Gold Case：
    `049e048b821e949936c1793d441f7adcda4660f10f8d0acf63e4f766a9726c22`

## 总览

| 阶段 | 当前状态 | 设计文档 | 实施计划 | 阶段提交 SHA | 下一阶段 |
|---|---|---|---|---|---|
| Stage 3 SQL 安全校验 | completed | `docs/superpowers/specs/2026-07-28-stage-3-sqlglot-validation-design.md` | `docs/superpowers/plans/2026-07-28-stage-3-sqlglot-validation.md` | `a1dba99` | Stage 4 |
| Stage 4 Schema Linking | completed | `docs/superpowers/specs/2026-07-28-stage-4-schema-linking-design.md` | `docs/superpowers/plans/2026-07-28-stage-4-schema-linking.md` | Stage 5 入口回填 | Stage 5 |
| Stage 5 SQL 生成 | not_started | 进入阶段后创建 | 进入阶段后创建 | 未产生 | Stage 6 |
| Stage 6 真实执行 | not_started | 进入阶段后创建 | 进入阶段后创建 | 未产生 | Stage 7 |
| Stage 7 反思修复 | not_started | 进入阶段后创建 | 进入阶段后创建 | 未产生 | Stage 8 |
| Stage 8 LangGraph Workflow | not_started | 进入阶段后创建 | 进入阶段后创建 | 未产生 | Stage 9 |
| Stage 9 FastAPI | not_started | 进入阶段后创建 | 进入阶段后创建 | 未产生 | Stage 10 |
| Stage 10 评测与安全回归 | not_started | 进入阶段后创建 | 进入阶段后创建 | 未产生 | 最终验收 |

## 当前阶段

### Stage 3：SQLGlot PostgreSQL AST 与安全校验

- 阶段状态：`completed`
- 上一阶段：Stage 2 元数据读取，提交 `8424ae9`
- 设计文档：
  `docs/superpowers/specs/2026-07-28-stage-3-sqlglot-validation-design.md`
- 实施计划：
  `docs/superpowers/plans/2026-07-28-stage-3-sqlglot-validation.md`
- 计划修改范围：
  - `pyproject.toml`
  - `app/validation/`
  - `tests/unit/test_validation_models.py`
  - `tests/unit/test_sql_validator_*.py`
  - `tests/security/test_sql_validator_security.py`
  - `tests/integration/test_pagila_sql_validation.py`
  - `docs/decisions/0003-sqlglot-safety-policy.md`
  - `README.md`
  - `docs/MVP_EXECUTION_PLAN.md`
- 验证命令：
  - `.venv/bin/python -m pytest tests/unit -v`
  - `.venv/bin/python -m pytest tests/security -v`
  - `.venv/bin/python -m pytest tests/integration -v -m integration`
  - `.venv/bin/python -m compileall -q app tools tests`
  - `.venv/bin/python -m pip check`
  - `docker compose -f infrastructure/pagila/compose.yaml config --quiet`
  - `git diff --check`
- 测试结果：
  - Stage 1–2 单元基线：`113 passed`
  - Stage 1–2 Pagila 集成基线：`16 passed`
  - `compileall`：通过
  - `pip check`：通过
  - Docker Compose 配置检查：通过
  - `git diff --check`：通过
- TDD 失败证据：
  - `app.validation` 缺失导致契约测试收集失败；
  - 结果 factory 缺失导致测试收集失败；
  - `validate_sql` 缺失导致结构测试收集失败；
  - 未批准函数最初被错误放行；
  - 授权对象和字段测试最初因缺少实现失败；
  - PG-MVP-002 首次暴露 SQLGlot `exp.And` 双重分类问题，修复后通过。
  - 独立审查测试证明整行表别名曾绕过 wildcard 门禁；新增直接和 CAST
    包裹回归后，使用 qualification 产生的 `exp.TableColumn` 精确拒绝。
- 阶段验证结果：
  - Stage 1–3 单元测试：`194 passed`
  - Stage 3 安全测试：`29 passed`
  - Stage 1–3 Pagila 集成测试：`34 passed`
  - `compileall`、`pip check`、Docker Compose 配置和
    `git diff --check`：通过
  - 三份受保护文件 SHA-256：与基线一致
- 代码审查结果：
  - 初审：无 blocking；1 high（整行别名绕过 wildcard）和 1 medium
    （参数化 CAST 缺少精确 AST 参数节点）。
  - high 已按 TDD 修复；medium 以精确 `exp.DataTypeParam` allowlist 修复，
    未放宽匿名函数、未知函数或未知 AST。
  - 首次复审确认上述修复后，另发现 1 high：自定义 CAST 目标可调用类型输入
    函数。已增加显式内建目标 allowlist、参数数量/类型检查和两条安全回归。
  - 最终独立复审：通过；`blocking=0`，`high=0`
- 阶段提交 SHA：`a1dba99`
- 遗留问题：无
- 下一阶段：Stage 4 Schema Linking

### Stage 4：确定性 Schema Linking

- 阶段状态：`completed`
- 上一阶段：Stage 3 SQL 安全校验，提交 `a1dba99`
- 设计文档：
  `docs/superpowers/specs/2026-07-28-stage-4-schema-linking-design.md`
- 实施计划：
  `docs/superpowers/plans/2026-07-28-stage-4-schema-linking.md`
- 计划修改范围：
  - `app/schema_linking/`
  - `tests/unit/test_schema_linking_models.py`
  - `tests/unit/test_schema_linker_*.py`
  - `tests/security/test_schema_linker_permissions.py`
  - `tests/integration/test_pagila_schema_linking.py`
  - `docs/decisions/0004-deterministic-schema-linking.md`
  - `README.md`
  - `docs/MVP_EXECUTION_PLAN.md`
- 验证命令：
  - `.venv/bin/python -m pytest tests/unit -q`
  - `.venv/bin/python -m pytest tests/security -q`
  - `.venv/bin/python -m pytest tests/integration -q -m integration`
  - `.venv/bin/python -m compileall -q app tools tests`
  - `.venv/bin/python -m pip check`
  - `docker compose -f infrastructure/pagila/compose.yaml config --quiet`
  - `git diff --check`
- 实际修改范围：
  - `app/schema_linking/`
  - `tests/unit/test_schema_linking_models.py`
  - `tests/unit/test_schema_linker_*.py`
  - `tests/security/test_schema_linker_permissions.py`
  - `tests/integration/test_pagila_schema_linking.py`
  - `docs/decisions/0004-deterministic-schema-linking.md`
  - `README.md`
  - 本设计、实施计划和执行台账
- TDD 失败证据：
  - `app.schema_linking` 缺失导致契约测试收集失败；
  - `link_schema` 缺失导致授权和安全测试收集失败；
  - `_tokenize` 缺失导致评分测试收集失败；
  - 普通 Top-K 首次把所需 FK 中间表排除，路径测试失败；加入授权图 BFS 后
    通过。
- 测试结果：
  - Stage 1–4 单元测试：`220 passed`
  - Stage 1–4 安全测试：`32 passed`
  - Stage 1–4 Pagila 集成测试：`49 passed`
  - Stage 4 Pagila Schema Linking Case：`15 passed`
    （PG-MVP-001～014、018）
  - 表字段召回：15/15 Case 全部覆盖，未授权对象命中数 0
  - 授权快照中真实存在的 Gold JOIN 边全部由返回路径覆盖
  - `compileall`、`pip check`、Docker Compose 配置和
    `git diff --check`：通过
  - 三份受保护文件 SHA-256：与基线一致
- 代码审查结果：
  - 初审：`blocking=0`、`high=1`。high 为 FK 连通表可能在关系排序参与前被
    零分噪声占满 Top-K；新增宽范围红灯后，以正命中为种子按最短 FK 距离提升
    关联零分表，修复通过。
  - 初次复审：high 已修复，另有 3 个 medium：带 FK 的无命中 fallback 顺序、
    Pagila Gold JOIN 边真空断言、缺失字段后重新 Linking 测试缺口。
  - 三项 medium 均已修复；最终独立复审：
    `blocking=0`、`high=0`、`medium=0`，Approved。
- 阶段提交 SHA：提交后在 Stage 5 入口回填
- 遗留问题：Pagila 3.1.0 的 `payment` 分区父表不携带
  `customer_id → customer.customer_id` 物理 FK，Stage 4 不伪造该路径；
  其余真实 Gold JOIN 边均已覆盖。
- 下一阶段：Stage 5 SQL 生成

## 阶段记录

后续每个阶段完成后，在此追加实际修改范围、失败测试证据、单元/集成/安全/
回归测试结果、独立审查结论、提交 SHA、遗留限制和下一阶段入口。任何用户定义
的阻塞条件成立时，当前阶段改为 `blocked`，并停止后续阶段。
