# Text-to-SQL MVP Stage 3–10 执行台账

> 本文件是 Stage 3–10 的历史执行记录，不是当前增强阶段的 Git 或交付指令。
> 当前工作只遵守仓库根目录 `AGENTS.md`：仅使用本地 `main`，验证后推送
> `origin main`，不创建额外分支、worktree 或 Pull Request。

## 执行约束

- 当时分支：`codex/mvp-stages-3-10`
- 当时推送目标：`origin/codex/mvp-stages-3-10`
- 当时约束：禁止合并或推送 `main`；该约束已由当前 `AGENTS.md` 单分支工作流取代
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
| Stage 4 Schema Linking | completed | `docs/superpowers/specs/2026-07-28-stage-4-schema-linking-design.md` | `docs/superpowers/plans/2026-07-28-stage-4-schema-linking.md` | `12574b5` | Stage 5 |
| Stage 5 SQL 生成 | completed | `docs/superpowers/specs/2026-07-28-stage-5-sql-generation-design.md` | `docs/superpowers/plans/2026-07-28-stage-5-sql-generation.md` | `6630de3` | Stage 6 |
| Stage 6 真实执行 | completed | `docs/superpowers/specs/2026-07-28-stage-6-real-execution-design.md` | `docs/superpowers/plans/2026-07-28-stage-6-real-execution.md` | `1a301aa` | Stage 7 |
| Stage 7 反思修复 | completed | `docs/superpowers/specs/2026-07-28-stage-7-reflection-repair-design.md` | `docs/superpowers/plans/2026-07-28-stage-7-reflection-repair.md` | `0d4c6b8` | Stage 8 |
| Stage 8 LangGraph Workflow | completed | `docs/superpowers/specs/2026-07-28-stage-8-langgraph-workflow-design.md` | `docs/superpowers/plans/2026-07-28-stage-8-langgraph-workflow.md` | `22f3a91` | Stage 9 |
| Stage 9 FastAPI | completed | `docs/superpowers/specs/2026-07-28-stage-9-fastapi-design.md` | `docs/superpowers/plans/2026-07-28-stage-9-fastapi.md` | `8120c73` | Stage 10 |
| Stage 10 评测与安全回归 | implementation completed；qualification `not_passed` | `docs/superpowers/specs/2026-07-29-stage-10-evaluation-security-design.md` | `docs/superpowers/plans/2026-07-29-stage-10-evaluation-security.md` | 本阶段终局提交 | 当时等待用户决定是否合并 |

## 历史阶段记录

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
- 阶段提交 SHA：`12574b5`
- 遗留问题：Pagila 3.1.0 的 `payment` 分区父表不携带
  `customer_id → customer.customer_id` 物理 FK，Stage 4 不伪造该路径；
  其余真实 Gold JOIN 边均已覆盖。
- 下一阶段：Stage 5 SQL 生成

### Stage 5：OpenAI-compatible 结构化 SQL 生成

- 阶段状态：`completed`
- 上一阶段：Stage 4 Schema Linking，提交 `12574b5`
- 设计文档：
  `docs/superpowers/specs/2026-07-28-stage-5-sql-generation-design.md`
- 实施计划：
  `docs/superpowers/plans/2026-07-28-stage-5-sql-generation.md`
- 计划修改范围：
  - `.env.example`
  - `app/config.py`
  - `app/validation/__init__.py`
  - `app/validation/policy.py`
  - `app/generation/`
  - `tests/unit/test_generation_*.py`
  - `tests/unit/test_llm_*.py`
  - `tests/security/test_generation_*.py`
  - `tests/security/test_llm_provider_security.py`
  - `tests/integration/test_openai_compatible_provider.py`
  - `tests/integration/test_generation_validation_pipeline.py`
  - `docs/decisions/0005-openai-compatible-generation.md`
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
  - `.env.example`
  - `app/config.py`
  - `app/validation/__init__.py`
  - `app/validation/policy.py`
  - `app/generation/`
  - `tests/unit/test_generation_*.py`
  - `tests/unit/test_llm_*.py`
  - `tests/security/test_generation_prompt_security.py`
  - `tests/security/test_llm_provider_security.py`
  - `tests/security/test_generated_sql_safety.py`
  - `tests/integration/test_openai_compatible_provider.py`
  - `tests/integration/test_generation_validation_pipeline.py`
  - `docs/decisions/0005-openai-compatible-generation.md`
  - `README.md`
  - 本设计、实施计划和执行台账
- TDD 失败证据：
  - `app.generation` 和 `LLMSettings` 缺失导致契约测试收集失败；
  - `build_generation_messages` 缺失导致 Prompt 测试收集失败；
  - 合法 JOIN Path 首次暴露相邻表 strict zip 长度错误，修复后通过；
  - Provider 类型缺失导致协议测试收集失败；
  - `generate_sql` 缺失导致服务/危险输出测试收集失败；
  - 本地 HTTP server 首次因沙箱禁止端口绑定失败，获准在受控环境重跑通过；
  - 新安全红灯证明换行 API key 被接受且 urllib 会跟随 302，修复为控制字符
    拒绝和禁用 redirect 后通过。
  - 独立审查红灯证明不完整 HTTP 响应会逃逸为原始异常；修复为脱敏的 Provider
    错误后通过。
  - 独立审查红灯证明 Prompt 未携带精确函数白名单和结果行上限；改为从
    Stage 3 单一来源导出函数集，并显式序列化 `max_result_rows` 后通过。
  - 独立审查红灯证明远程 HTTP 会明文发送认证头和 Prompt；改为远程仅 HTTPS、
    回环地址可 HTTP 后通过。
  - 非 `stop` completion、超过 Top-K 候选和伪造候选描述元数据的复审测试先
    失败；改为 fail-closed、强制 Top-K，并从同版本 Snapshot 读取描述元数据。
- 测试结果：
  - Stage 1–5 单元测试：`276 passed`
  - Stage 1–5 安全测试：`37 passed`
  - Stage 1–5 Pagila/本地协议/生成管线集成：`54 passed`
  - `python -m compileall`：通过
  - `pip check`：通过
  - Docker Compose 配置检查：通过
  - `git diff --check`：通过
  - 受保护文件 SHA-256：与基线一致
  - 作用域 Secret 扫描：未发现真实凭据；README 仅有环境变量占位 DSN
  - `.env` LLM 配置结构和 Secret repr：通过（未输出值）
  - 可选真实外部模型烟测因外部数据发送权限未获批准而未执行；Stage 10
    真实模型 E2E 门禁不变
- 代码审查结果：
  - 初审发现 3 个 high：底层 HTTP 异常可能逃逸、Prompt 缺失精确函数白名单/
    1000 行约束、远程 HTTP 明文传输；均以失败测试重现并修复。
  - 复审提出 `finish_reason`、Snapshot 元数据来源、Top-K 边界和文档同步等
    nonblocking medium；实现和文档均已补齐。
  - 最终独立复审：`blocking=0`、`high=0`，Approved。
- 阶段提交 SHA：`6630de3`
- 遗留问题：无
- 下一阶段：Stage 6 真实执行

## 阶段记录

### Stage 6：校验后真实执行

- 阶段状态：`completed`
- 上一阶段：Stage 5 SQL 生成，提交 `6630de3`
- 设计文档：
  `docs/superpowers/specs/2026-07-28-stage-6-real-execution-design.md`
- 实施计划：
  `docs/superpowers/plans/2026-07-28-stage-6-real-execution.md`
- 计划修改范围：
  - `app/execution/`
  - `tests/unit/test_execution_*.py`
  - `tests/security/test_execution_boundary_security.py`
  - `tests/integration/test_validated_execution.py`
  - `docs/decisions/0006-validated-real-execution.md`
  - `README.md`
  - 本设计、实施计划和执行台账
- 验证命令：
  - `.venv/bin/python -m pytest tests/unit -q`
  - `.venv/bin/python -m pytest tests/security -q`
  - `.venv/bin/python -m pytest tests/integration -q -m integration`
  - `.venv/bin/python -m compileall -q app tools tests`
  - `.venv/bin/python -m pip check`
  - `docker compose -f infrastructure/pagila/compose.yaml config --quiet`
  - `git diff --check`
- 实际修改范围：
  - `app/execution/`
  - `tests/unit/test_execution_models.py`
  - `tests/unit/test_execution_service.py`
  - `tests/security/test_execution_boundary_security.py`
  - `tests/integration/test_validated_execution.py`
  - `docs/decisions/0006-validated-real-execution.md`
  - `README.md`
  - 本设计、实施计划和执行台账
- TDD 失败证据：
  - `app.execution` 不存在，两个单元测试和一个安全测试在收集阶段均以
    `ModuleNotFoundError` 失败；
  - 实现最小 Outcome/Protocol/Service 后，聚焦单元与安全测试转绿；
  - 独立审查复现公开 `success_result()` 可伪造 DML、多 statement 和
    `pg_sleep` 成功结果并触发 Connector；新增 3 项红灯后，执行入口改为用同一
    可信授权快照重新运行 Stage 3 并要求结果完全一致，修复通过；
  - 真实 Pagila 校验后执行集成测试随后通过。
- 测试结果：
  - Stage 6 聚焦单元/安全测试：`27 passed`
  - Stage 6 真实 Pagila 集成测试：`6 passed`
  - Stage 1–6 单元测试：`294 passed`
  - Stage 1–6 安全测试：`46 passed`
  - Stage 1–6 Pagila/本地协议集成测试：`60 passed`
  - `python -m compileall`：通过
  - `pip check`：通过
  - Docker Compose 配置检查：通过
  - `git diff --check`：通过
  - 受保护文件 SHA-256：与基线一致
  - 作用域 Secret 扫描：未发现真实凭据；README 仅有环境变量占位 DSN
- 代码审查结果：
  - 初审：`blocking=0`、`high=1`。High 为公开 `success_result()` 可伪造危险
    SQL 成功结果并绕过 Stage 3；以 DELETE、多 statement 和 `pg_sleep` 红灯
    复现后，改为同一可信授权上下文重新校验并要求结果完全一致。
  - 复审确认 High 已关闭，伪造和替换 SQL 均零 Connector 调用。
  - Outcome 运行时类型 medium 以 2 项红灯复现并修复。
  - 未限定表名/search_path medium 在锁定 public-only Pagila 权限模型下为
    非阻塞已知边界；多可读 Schema 扩展前必须处理。
  - 最终独立复审：`blocking=0`、`high=0`、`medium=0`、
    `low=2`，Approved with Low。
- 阶段提交 SHA：`1a301aa`
- 遗留问题：Stage 3 规范 SQL 保留未限定表名；当前锁定 public-only Pagila
  权限模型安全，未来多可读 Schema 扩展前必须绑定 Schema 或固定安全
  `search_path`。
- 下一阶段：Stage 7 反思修复

后续每个阶段完成后，在此追加实际修改范围、失败测试证据、单元/集成/安全/
回归测试结果、独立审查结论、提交 SHA、遗留限制和下一阶段入口。任何用户定义
的阻塞条件成立时，当前阶段改为 `blocked`，并停止后续阶段。

### Stage 7：反思修复、SQL 指纹与循环终止

- 阶段状态：`completed`
- 上一阶段：Stage 6 真实执行，提交 `1a301aa`
- 设计文档：
  `docs/superpowers/specs/2026-07-28-stage-7-reflection-repair-design.md`
- 实施计划：
  `docs/superpowers/plans/2026-07-28-stage-7-reflection-repair.md`
- 计划修改范围：
  - `app/reflection/`
  - `tests/unit/test_sql_fingerprint.py`
  - `tests/unit/test_attempt_history.py`
  - `tests/unit/test_reflection_routing.py`
  - `tests/security/test_reflection_safety.py`
  - `tests/integration/test_reflection_repair_pipeline.py`
  - `docs/decisions/0007-reflection-repair.md`
  - `README.md`
  - 本设计、实施计划和执行台账
- 验证命令：
  - `.venv/bin/python -m pytest tests/unit -q`
  - `.venv/bin/python -m pytest tests/security -q`
  - `.venv/bin/python -m pytest tests/integration -q -m integration`
  - `.venv/bin/python -m compileall -q app tools tests`
  - `.venv/bin/python -m pip check`
  - `docker compose -f infrastructure/pagila/compose.yaml config --quiet`
  - `git diff --check`
- 实际修改范围：
  - `app/reflection/`
  - `tests/unit/test_sql_fingerprint.py`
  - `tests/unit/test_attempt_history.py`
  - `tests/unit/test_reflection_routing.py`
  - `tests/security/test_reflection_safety.py`
  - `tests/integration/test_reflection_repair_pipeline.py`
  - `docs/decisions/0007-reflection-repair.md`
  - `README.md`
  - 本设计、实施计划和执行台账
- TDD 失败证据：
  - `app.reflection` 不存在，三个单元测试和一个安全测试均在收集阶段以
    `ModuleNotFoundError` 失败；
  - 最小指纹、历史、预算和路由实现后聚焦测试转绿；
  - 新增未加引号标识符大小写等价红灯，首次证明指纹不同；指纹序列化前按
    PostgreSQL 规则规范标识符后转绿，同时保留加引号大小写差异；
  - 独立审查红灯证明 TokenError 会逃逸、注释可绕过指纹、History 可变容器会
    破坏不变量、成功校验可与当前 attempt SQL 错配；分别补齐词法失败原文 hash、
    `comments=False`、tuple/frozenset 强校验和当前 SQL 指纹绑定；
  - 复审 Low 的非法修复状态和“硬错误 + 修复策略”可直接构造，新增 2 项红灯
    后补齐状态类型与 error/route/strategy/code 语义绑定；
  - PG-MVP-018 真实修复管线和 A→B→A 集成测试通过。
- 测试结果：
  - Stage 7 聚焦单元/安全测试：`52 passed`
  - Stage 7 真实 Pagila 修复集成测试：`2 passed`
  - Stage 1–7 单元测试：`335 passed`
  - Stage 1–7 安全测试：`57 passed`
  - Stage 1–7 Pagila/本地协议集成测试：`62 passed`
  - `python -m compileall`：通过
  - `pip check`：通过
  - Docker Compose 配置检查：通过
  - `git diff --check`：通过
  - 受保护文件 SHA-256：与基线一致
  - 作用域 Secret 扫描：未发现真实凭据；README 仅有环境变量占位 DSN
- 代码审查结果：
  - 初审：`blocking=0`、`high=4`。四项为 TokenError 未归一化、注释绕过去重、
    可变 History 容器破坏不变量、校验结果未绑定当前 attempt；均以失败测试
    复现并修复。
  - 初次复审确认四项 High 全部关闭，仅余文档计数 medium 和两个模型构造
    low；计数已刷新，两个 low 均已以红灯加固。
  - 最终独立复审：`blocking=0`、`high=0`、`medium=0`、`low=0`，
    Approved。
- 阶段提交 SHA：`0d4c6b8`
- 遗留问题：无
- 下一阶段：Stage 8 LangGraph Workflow

### Stage 8：九节点 LangGraph Workflow

- 阶段状态：`completed`
- 上一阶段：Stage 7 反思修复，提交 `0d4c6b8`
- 设计文档：
  `docs/superpowers/specs/2026-07-28-stage-8-langgraph-workflow-design.md`
- 实施计划：
  `docs/superpowers/plans/2026-07-28-stage-8-langgraph-workflow.md`
- 计划修改范围：
  - `pyproject.toml`
  - `app/connectors/postgresql.py`
  - `app/workflow/`
  - `tests/unit/test_postgresql_connector.py`
  - `tests/unit/test_postgresql_metadata.py`
  - `tests/unit/test_workflow_*.py`
  - `tests/security/test_workflow_*.py`
  - `tests/integration/test_langgraph_workflow.py`
  - `docs/decisions/0008-langgraph-workflow.md`
  - `README.md`
  - 本设计、实施计划和执行台账
- 验证命令：
  - `.venv/bin/python -m pytest tests/unit -q`
  - `.venv/bin/python -m pytest tests/security -q`
  - `.venv/bin/python -m pytest tests/integration -q -m integration`
  - `.venv/bin/python -m compileall -q app tools tests`
  - `.venv/bin/python -m pip check`
  - `docker compose -f infrastructure/pagila/compose.yaml config --quiet`
  - `git diff --check`
- 实际修改范围：
  - `pyproject.toml`
  - `app/connectors/postgresql.py` 的私有、并发隔离重试观测，不改变公开接口
  - `app/workflow/`
  - `tests/unit/test_postgresql_connector.py`
  - `tests/unit/test_postgresql_metadata.py`
  - `tests/unit/test_workflow_*.py`
  - `tests/security/test_workflow_*.py`
  - `tests/integration/test_workflow_pagila.py`
  - `docs/decisions/0008-langgraph-workflow.md`
  - `README.md`
  - 本设计、实施计划和执行台账
- TDD 失败证据：
  - `app.workflow` 缺失导致 State、预处理和权限测试收集失败；
  - 九节点图 API 缺失导致图与安全路由测试收集失败；
  - Stage 1 递归 `JsonValue` 首次使 Pydantic State Schema 生成递归溢出；
    将递归对象在 Schema 中保持 opaque，并在 State validator 中恢复严格运行
    时类型和 `AttemptHistory` 检查后通过；
  - 外部执行跨过 120 秒总预算最初仍返回成功；新增红灯后在 Finalize 丢弃超时
    结果并返回 `FAILED_TIMEOUT`；
  - 独立审查红灯证明模型 ID/Prompt 版本丢失、修复 Prompt 无独立版本；新增逐
    调用 `GenerationObservation`、Token 汇总不变量和 `repair-v1` 后通过；
  - 精确图边测试首次只看到 `START → RequestPreprocess → END`；为所有条件边
    增加显式 `path_map` 后，九节点 23 条允许边可静态检查；
  - 基础设施重试最初始终记录为 0；Connector 的 0/1/3 次重试和 Workflow
    元数据+执行累计红灯失败后，以私有 `ContextVar` 观测修复，公开接口不变；
  - 终态错误类型可与 `FinalStatus` 错配、Generate timing 错归前一 attempt；
    两项红灯后补齐严格终态和本节点 attempt 归属。
- 测试结果：
  - Stage 8 聚焦模型/图/权限/安全测试：通过
  - Stage 1–8 单元测试：`371 passed`
  - Stage 1–8 安全测试：`69 passed`
  - Stage 1–8 Pagila/本地协议集成测试：`64 passed`
  - Stage 8 真实 Pagila Workflow：首次成功与一次 Schema 修复均通过
  - `python -m compileall`：通过
  - `pip check`：通过
  - Docker Compose 配置检查：通过
  - `git diff --check`：通过
  - 受保护文件 SHA-256：与基线一致
  - 作用域 Secret 扫描：未发现真实凭据；README 只有环境变量占位 DSN
- 代码审查结果：
  - 独立审查初审：`blocking=0`、`high=2`。High 为模型/Prompt 身份丢失和
    Connector 内部重试不可观测，均已按 TDD 修复。
  - 初审另有 4 个 medium：attempt timing、静态图边、严格终态和路由测试
    缺口，均已补红灯并修复。
  - 追加语义类错误经 Reflect 进入 Clarification 的路由红灯和实现后再次复审；
    权限、安全、连接、超时、资源、重复和 UNKNOWN 均未被扩入 Reflect。
  - 最终独立复审：定向无缓存 `81 passed`；
    `blocking=0`、`high=0`、`medium=0`、`low=0`，Approved。
- 阶段提交 SHA：`22f3a91`
- 遗留问题：Stage 6 已记录的 public-only 未限定表名边界仍存在；未新增 Stage 8
  问题。
- 下一阶段：Stage 9 FastAPI

### Stage 9：FastAPI 同步接口与可信启动

- 阶段状态：`completed`
- 上一阶段：Stage 8 LangGraph Workflow，提交 `22f3a91`
- 设计文档：
  `docs/superpowers/specs/2026-07-28-stage-9-fastapi-design.md`
- 实施计划：
  `docs/superpowers/plans/2026-07-28-stage-9-fastapi.md`
- 计划修改范围：
  - `pyproject.toml`
  - `app/api/`
  - `app/main.py`
  - `tests/unit/test_api_*.py`
  - `tests/security/test_api_*.py`
  - `tests/integration/test_api_pagila.py`
  - `docs/decisions/0009-fastapi-boundary.md`
  - `README.md`
  - 本设计、实施计划和执行台账
- 验证命令：
  - `.venv/bin/python -m pytest tests/unit -q`
  - `.venv/bin/python -m pytest tests/security -q`
  - `.venv/bin/python -m pytest tests/integration -q -m integration`
  - `.venv/bin/python -m compileall -q app tools tests`
  - `.venv/bin/python -m pip check`
  - `docker compose -f infrastructure/pagila/compose.yaml config --quiet`
  - `git diff --check`
- 实际修改范围：
  - `pyproject.toml`
  - `app/api/`
  - `app/main.py`
  - `tests/unit/test_api_application.py`
  - `tests/unit/test_api_models.py`
  - `tests/unit/test_api_response_mapping.py`
  - `tests/security/test_api_permissions.py`
  - `tests/integration/test_api_pagila.py`
  - `docs/decisions/0009-fastapi-boundary.md`
  - `README.md`
  - 本设计、实施计划和执行台账
- TDD 失败证据：
  - `app.api` 缺失导致请求/响应模型契约测试收集失败；
  - `build_query_response` 缺失导致终态映射测试收集失败；
  - `ApplicationServices` 和 `create_app` 缺失导致应用与权限测试收集失败；
  - 首次响应模型把 `FAILED_INTERNAL` 与已定义的权限、重复、超时、连接、
    资源及已耗尽可修复错误错误组合放行；增加非法组合红灯后收紧终态不变量。
  - 独立审查红灯证明任意 Python 对象可进入 `rows`，OpenAPI 行值 Schema 为空，
    且序列化失败会逃逸为纯文本 500；改用 PEP 695 递归 JSON 类型并扩大统一
    异常边界后通过。
  - ID factory 异常最初绕过固定 500；增加 fallback UUID 和结构化错误测试后
    通过。
  - 默认 422 最初回显完整非法输入；增加敏感超长问题红灯后，改为固定脱敏
    validation handler。
  - 可配置非 Pagila datasource 最初会启动成功；增加连接前拒绝测试后
    fail-closed。
- 测试结果：
  - Stage 1–9 单元测试：`411 passed`
  - Stage 1–9 安全测试：`75 passed`
  - Stage 1–9 Pagila/协议/工作流/API 集成测试：`68 passed`
  - Stage 9 真实 Pagila HTTP Case：首次成功、合法空结果、一次 Schema 修复和
    危险模型 SQL 零执行全部通过
  - `python -m compileall`：通过
  - `pip check`：通过
  - Docker Compose 配置检查：通过
  - `git diff --check`：通过
  - 三份受保护文件 SHA-256：与基线一致
- 代码审查结果：
  - 初审发现 1 个 high：`rows` 允许非 JSON 对象，OpenAPI 为空约束且序列化
    失败绕过脱敏 500；已按失败测试修复。
  - 初审的 3 个 medium（422 回显、datasource 未锁定、终态/HTTP timeout
    覆盖）和 2 个 low（owned close 测试、计划路径）均已修复。
  - 最终独立复审：`blocking=0`、`high=0`、`medium=0`、`low=0`，
    Approved。
- 阶段提交 SHA：`8120c73`
- 遗留问题：Stage 6 已记录的 public-only 未限定表名边界仍存在；未新增
  Stage 9 问题。
- 下一阶段：Stage 10 评测与安全回归

### Stage 10：评测与安全回归

- 阶段状态：工程实现 `completed`；MVP release qualification
  `not_passed`
- 上一阶段：Stage 9 FastAPI，提交 `8120c73`
- 设计文档：
  `docs/superpowers/specs/2026-07-29-stage-10-evaluation-security-design.md`
- 实施计划：
  `docs/superpowers/plans/2026-07-29-stage-10-evaluation-security.md`
- 修改文件范围：
  - `app/observability/`
  - `app/api/bootstrap.py`
  - `app/connectors/postgresql.py`
  - `app/connectors/view_semantics.py`
  - `app/connectors/view_semantics_lock.py`
  - `app/generation/normalization.py`
  - `app/generation/prompt.py`
  - `app/generation/service.py`
  - `app/workflow/nodes.py`
  - `evaluation/`
  - `infrastructure/pagila/view_semantic_*.json`
  - `infrastructure/pagila/view_semantics.json`
  - `tools/freeze_view_semantics.py`
  - `tools/run_pagila_evaluation.py`
  - `tests/` 中 Stage 10 单元、集成、安全测试及测试包标记
  - `docs/decisions/0010-evaluation-trace-security.md`
  - `evaluation/reports/pagila_mvp_stage10.md`
  - `README.md`
  - 本设计、实施计划和执行台账
- 已完成的入口检查：
  - 当时分支与 `origin/codex/mvp-stages-3-10` 同步；
  - Stage 9 工作区干净；
  - Stage 9 最终基线：单元 `411 passed`、安全 `75 passed`、集成
    `68 passed`；
  - 三份受保护文件 SHA-256 与基线一致；
  - 2026-07-29 仅检查 `.env` 配置存在性：
    `LLM_BASE_URL`、`LLM_API_KEY`、`LLM_MODEL` 均已配置，未读取或输出值；
    真实模型凭据不再构成阻塞；
  - 2026-07-29 用户授权仅对通过真实执行、比较和审核的 Case 修改
    `status`，原 Gold 阻塞已解除；
  - Pagila commit：
    `fef9675714cfba1756df4719b5e36075a7ddf90e`；
  - PostgreSQL：`16.14 (Debian 16.14-1.pgdg12+1)`；
  - 运行时 data-only dump 在将随机 `restrict/unrestrict` nonce
    规范化为固定 `TOKEN` 后，两次连续 SHA-256 均为：
    `e584f0beb3817d1a6f3e35518192ba66cc8b14c50df08c34527d5b15e77bd567`；
  - 运行时 schema-only dump SHA-256：
    `74de0ad271945ff3ce8e21d9065d1c0178f01994a8f25c613afebcebed5933b2`；
  - Stage 10 入口回归：单元 `411 passed`、安全 `75 passed`、集成
    `68 passed`；
  - `compileall`、`pip check`、Compose 和 `git diff --check`：通过。
- TDD 与实现结果：
  - 严格 Case loader、Comparator、安全 Trace、真实评测 Runner、报告、
    两级审核摘要和单 Case 原子状态门均已实现；
  - 正式评测 CLI 在加载凭据前验证静态 fixture 与运行时数据库基线；
  - Gold 与预测在同一 `REPEATABLE READ READ ONLY` 事务和 Schema snapshot
    中运行；
  - 最终 SQL 必须与 Linker 同时命中 Gold 必需表字段；
  - Comparator 已覆盖非有限数、1000 重复行、逻辑时间键和列名对齐；
  - 实际数据库执行计数按每个 attempt 记录；
  - 与 Gold 无关的确定性投影别名规范化仅处理直接列、`COUNT(普通列)`、
    `SUM(普通列)` 和 `DATE_TRUNC(普通列, unit)`，跳过歧义并且不改值语义；
  - 一次性收集全部测试曾暴露单元/集成同名模块冲突；增加测试包标记后，
    全套可在单个 pytest 进程中收集和运行。
#### 已作废的首次候选历史

- Pagila 真实评测与逐条审核：
  - 最新候选自动通过 `17/18`；
  - PG-MVP-003 为 `EVALUATION_FIELD_RECALL_FAILED`，预测 584 行而 Gold
    为 599 行；
  - 审核通过 `0/18`，审核拒绝 `18/18`，verified `0/18`；
  - 权限/危险 SQL `3/3` 安全拒绝，数据库执行与修复均为 0；
  - 当前 Gold 文件 SHA-256：
    `049e048b821e949936c1793d441f7adcda4660f10f8d0acf63e4f766a9726c22`；
  - status-neutral SHA-256 保持：
    `a00a8ec7496fc4e1533b2773e0267d555357a80be435a02dd70981d76ddb40d7`；
  - Gold 已逐字节恢复到原始全 `draft` 状态；
  - 结构化候选报告记录的 `initial_status=verified` 来自先前已作废的状态更新
    尝试，故该报告只保留为 rejected 证据，不能作为合规验收证明。
- 测试结果：
  - 最终 blocked 快照单元：`502 passed`
  - 最终 blocked 快照安全：`88 passed`
  - 最终 blocked 快照真实 Pagila 集成：`73 passed`
  - 最终 blocked 快照单进程全量回归：`663 passed`
  - `compileall`：通过
  - `pip check`：通过
  - Docker Compose 配置检查：通过
  - `git diff --check`：通过
  - 当前 Gold 与 `HEAD` 逐字节一致，18 条状态均为 `draft`
- 代码审查结果：
  - 独立初审：`blocking=0`、`high=4`、`medium=4`、`low=1`；
  - 4 个 high（CLI 基线自证、共享事务快照、最终 SQL 表字段门、Comparator
    递归）均以失败测试修复；
  - 4 个 medium（非有限数、逻辑时间键、修复执行计数、证据/审核摘要）均已
    修复；
  - low 为 PG-MVP-011 分区父表 FK 元数据缺口；保留诊断，并由最终 JOIN
    字段命中和 599 行 Gold 完全比较补足验收证据；
  - 最终独立复审发现两个 High：观察 PG-MVP-003 后增加 boolean 偏好属于
    事后评测 coaching；`bpchar → TRIM(...)` 会改变值语义并造成范围漂移；
  - 两项调整均未作为验收修复，值改写代码已移除；旧目标当时按阻塞规则停止。
- 阶段提交 SHA：未产生
- 历史遗留问题：
  - 外部数据审查不允许再次经 FastAPI 把 Case 问题和 Schema 上下文发送到
    未明示模型目的地；真实 Provider 已在 18 Case Workflow 评测验证，
    FastAPI 闭环由固定 Stub + 同一真实 Pagila 集成测试验证；
  - 真实模型 `temperature=0` 仍不保证跨运行字节级确定性；
  - Stage 6 已记录的 public-only 未限定表名边界仍存在。
  - 第二次只读阻塞审计确认：锁定 Pagila 的 `customer_list` 视图使用
    `customer.activebool` 表示文本 `active`，但两个候选状态字段均无数据库
    注释，当前元数据/Prompt 契约也不暴露视图定义；将该表达式临时合成为别名
    会新增已见 Gold 驱动的生产语义；该事项随后已获用户明确授权，并由以下
    恢复执行记录取代。

#### 2026-07-29 恢复执行

- 用户已明确授权受控、通用、可审计的冻结视图语义能力，并要求旧 17/18
  报告永久作废。
- 合成 TDD 已证明：
  - 直接投影和简单 boolean CASE 标签的通用提取；
  - 仅解包字符串字面量的一层 `::text` 无损 cast；
  - 函数、拼接、非文本 cast、`NOT`、多字段、未授权依赖、歧义 lineage、
    CTE/子查询和敏感标签 fail-closed；
  - 普通请求不扫描视图，权限过滤早于语义派生；
  - manifest 外部锚、请求 scope 过滤和 Prompt/Trace 泄漏防护。
- 锁定 Pagila 候选账本包含 10 条逐来源证据。独立审核逐条批准 10/10；
  runtime manifest 按语义聚合为 6 条，并保留候选/审核集合摘要。
- 新 baseline 合同已绑定：
  - 代码根、`pyproject.toml`、Python 实现/版本和 21 个行为相关实际依赖版本；
  - 不含密码的数据库目标、连接池、超时、行数上限和重试配置；
  - Prompt、Provider、Comparator、Evidence、Report 版本；
  - 模型非秘密配置摘要；
  - 原始/增强 Schema 版本、视图定义、scope、候选/审核和 manifest 摘要；
  - Pagila/PostgreSQL/data/schema 与全 `draft` Gold 精确摘要；
  - 自校验 `evaluation_baseline_id`。
- Case evidence 已绑定 baseline ID；旧报告改为 invalidated version 并移入
  `evaluation/reports/invalidated/`。
- 恢复期红灯与修复：
  - 字符串 `::text` 标签最初未抽取；
  - 重复权威来源最初产生冗余 runtime entries；
  - production 最初在 manifest 校验前加载模型凭据；
  - code freeze 最初未覆盖 `pyproject.toml`/`tools/__init__.py`；
  - evaluate 最初未强制精确全 `draft` 起点；
  - Case evidence 最初可跨 baseline 重放；
  - candidate/review 账本漂移最初未被静态冻结校验发现；
  - 损坏 UTF-8 baseline/report 最初暴露解码错误。
  上述项目均先以非 Gold 测试复现，再修复转绿。
- 唯一一次完整独立初审已结束：
  - `blocking=1`：测试用 baseline 与最新代码根不一致；
  - `high=5`：旧报告跨 baseline 重放、不完整证据伪造通过、manifest 未精确
    绑定审核聚合、依赖/数据库执行配置未冻结、投影 alias 碰撞；
  - `medium=1`：报告派生指标和 verified 状态缺少完整一致性门；
  - `low=2`：source digest 文档歧义和 fixture contract provenance。
- 修复期新增非 Gold 红灯共 14 个失败，随后完成：
  - review/verify 显式绑定当前外部 baseline，并在写入前复算静态冻结；
  - `CaseEvidence` 按行为强制完整成功证据，Evidence/Review 契约升版；
  - manifest entries 必须与逐条审核结果的规范聚合逐字段相等，运行时再次检查
    授权对象、别名策略和请求 scope；
  - baseline v3 记录实际依赖版本及数据库非秘密执行配置；
  - alias normalization 先验证完整投影名唯一性，碰撞时整条 no-op；
  - 报告加载重算全部 metrics，verified 状态要求对应通过且已审核证据；
  - source digest 文档与实际安全绑定一致，fixture 使用独立版本身份。
- 恢复期测试证据：
  - 视图语义/别名/证据聚焦：`64 passed`；
  - Runner/安全聚焦：`11 passed`；
  - 审核/冻结/CLI 聚焦：`50 passed`；
  - 全部 unit + security：`692 passed`；
  - 测试用 baseline v3 自校验通过；
  - `git diff --check`：通过。
- 唯一最终复审：
  - B1、H1、H2、H3、H4、H5 全部关闭；
  - 修复引入的新 `blocking=0`、`high=0`；
  - 聚焦非 Gold 回归 `118 passed`。
- 正式冻结：
  - baseline version：`stage10-freeze-v3`；
  - baseline ID：
    `3f2c562dab63fcafb8a02196f24b3330cb5dfe2b72573c673aea08f7fc1a6002`；
  - controlled code SHA-256：
    `c5704f58a182fc86b62838de77872514ab4df1ac2807fb3404fe80db9d88b3c4`；
  - Pagila commit、PostgreSQL、Schema、data、语义 manifest、视图定义、
    依赖、数据库非秘密执行配置、模型非秘密配置和 Gold 摘要均通过自校验。
- 正式候选 `1/2`：
  - 自动证据 `12/18`；
  - 独立逐条审核 `12 approved / 6 rejected`；
  - 失败为 PG-MVP-005/007 的 `COMPARATOR_COLUMN_MISMATCH`、
    PG-MVP-008/009 的 `EVALUATION_FINAL_STATUS_MISMATCH`、
    PG-MVP-010/012 的 `EVALUATION_FIELD_RECALL_FAILED`；
  - 未发现可由非 Gold 证据证明的通用 blocking/high 实现缺陷，按终局规则
    候选 1 即为最终结果，不运行随机重试或 Gold 驱动调优；
  - Gold 保持 `draft=18`、`verified=0`。
- 最终工程验证：
  - 单元 `581 passed`；
  - 安全 `111 passed`；
  - 真实 Pagila 集成 `73 passed`；
  - 单进程完整回归 `765 passed`；
  - FastAPI 固定 Stub + 真实 Pagila 的首次执行、合法空结果、一次修复闭环和
    危险 SQL 零执行拒绝通过；
  - `compileall`、`pip check`、Docker Compose 配置和
    `git diff --check`：通过。
- 当前 Gold：文件 SHA-256
  `049e048b821e949936c1793d441f7adcda4660f10f8d0acf63e4f766a9726c22`，
  status-neutral SHA-256
  `a00a8ec7496fc4e1533b2773e0267d555357a80be435a02dd70981d76ddb40d7`，
  `draft=18`、`verified=0`。
- 代码审查结果：唯一集中初审的全部 blocking/high 已修复；唯一最终复审
  `blocking=0`、`high=0`。
- 阶段提交 SHA：本阶段终局提交（实际 SHA 见最终报告）
- 遗留问题：冻结模型未达到 18/18，工程完成但 MVP 发布资格未通过。
- 当时下一阶段：停止并等待用户决定是否合并到 `main`；当前工作流以根目录
  `AGENTS.md` 为准。
