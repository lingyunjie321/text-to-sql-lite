# Stage 6 Validated Real Execution Implementation Plan

**Goal:** Execute only the normalized SQL from a successful current-policy
validation result through the existing read-only PostgreSQL Connector and return
exactly a result or a sanitized database error.

**Architecture:** A small `app.execution` layer defines a Connector protocol,
strict immutable outcome, and a fail-closed service. It revalidates with the
same trusted authorization snapshot and requires exact result equality before
execution. Stage 1 remains the single owner of transactions, timeout,
truncation, normalization, cancellation and connection retry.

**Tech Stack:** Python 3.12, dataclasses, Protocol, existing psycopg Connector,
pytest 9.1.1.

## Constraints

- Do not modify protected specs or Pagila JSONL.
- Do not add a production dependency.
- Do not change Stage 1 Connector or Stage 3 Validator public interfaces.
- Never accept a second raw SQL string beside the validation result.
- Never trust the public `success_result()` factory as proof of validation;
  revalidate with trusted authorization context.
- Never execute a failed, stale-policy or internally inconsistent validation.
- Do not add attempt history, reflection, LangGraph, API, trace or evaluation.
- One Stage 6 commit on `codex/mvp-stages-3-10`.

## Task 1: Execution Contracts

**Files:**

- Create: `app/execution/__init__.py`
- Create: `app/execution/models.py`
- Test: `tests/unit/test_execution_models.py`

- [ ] Write failing imports and XOR/frozen tests for `ExecutionOutcome`.
- [ ] Add explicit success/failure factories.
- [ ] Observe failure before implementation.
- [ ] Implement the smallest immutable contract.

## Task 2: Fail-closed Execution Service

**Files:**

- Create: `app/execution/service.py`
- Test: `tests/unit/test_execution_service.py`
- Test: `tests/security/test_execution_boundary_security.py`

- [ ] Write failing tests for one call with `normalized_sql`.
- [ ] Prove invalid/failed/stale/inconsistent validation results call the
  Connector zero times and expose only a generic context error.
- [ ] Prove forged success results for DML, multi-statement and dangerous
  functions are revalidated and call the Connector zero times.
- [ ] Prove Connector errors become error outcomes without SQL or raw exception.
- [ ] Prove DML, multiple statements and dangerous functions rejected by Stage 3
  never reach the Connector.
- [ ] Implement the Protocol and validate → execute → outcome service.
- [ ] Do not catch unknown programming errors or add retries.

## Task 3: Real Pagila Integration

**Files:**

- Create: `tests/integration/test_validated_execution.py`

- [ ] Validate then execute a normal Pagila SELECT.
- [ ] Cover CTE/aggregate, legal empty result and 1000-row truncation.
- [ ] Cover a validator rejection with a zero-call guard.
- [ ] Cover a safe read-only runtime database error and sanitized mapping.
- [ ] Run all Stage 1–6 integration tests.

## Task 4: Documentation, Review, Commit

**Files:**

- Create: `docs/decisions/0006-validated-real-execution.md`
- Modify: `README.md`
- Modify: `docs/MVP_EXECUTION_PLAN.md`

- [ ] Document the single SQL source, Connector ownership and error boundary.
- [ ] Run unit, security, integration, compileall, pip check, Compose, diff,
  protected hashes and scoped secret scan.
- [ ] Dispatch one independent read-only reviewer.
- [ ] Fix every blocking/high finding through a failing test.
- [ ] Record final counts and review verdict.
- [ ] Commit `feat: complete stage 6 execution workflow`.
- [ ] Push `codex/mvp-stages-3-10`.

## Plan Self-Review

- The design reuses the already verified Connector instead of duplicating it.
- There is no raw SQL mismatch path and no retry amplification.
- Security policy remains owned by Stage 3 and is never weakened.
- SQL attempt and routing concepts remain in their specified later stages.
