# Stage 7 Reflection Repair Implementation Plan

**Goal:** Add deterministic SQL attempt history, stable fingerprint
deduplication, a three-repair budget and safe error routing without adding the
LangGraph workflow yet.

**Architecture:** `app.reflection` owns pure fingerprint/history/decision logic.
Accepted repairs are data only; callers must run every new attempt through the
existing Validator and validated execution service.

**Tech Stack:** Python 3.12, dataclasses, enum, hashlib, SQLGlot 30.13.0,
pytest 9.1.1.

## Constraints

- Do not modify protected specs or Pagila JSONL.
- Do not add a production dependency.
- Do not change Stage 5 generation or Stage 6 execution public interfaces.
- Never repair permission, safety, connection, timeout or unsafe resource
  failures.
- Never execute a duplicate or unvalidated repair.
- Do not add LangGraph, API, trace, comparator or evaluation.
- One Stage 7 commit on `codex/mvp-stages-3-10`.

## Task 1: Stable SQL Fingerprints

**Files:**

- Create: `app/reflection/fingerprint.py`
- Test: `tests/unit/test_sql_fingerprint.py`

- [ ] Write failing import and exact fingerprint behavior tests.
- [ ] Cover parseable formatting equivalence and raw parse-failure differences.
- [ ] Implement PostgreSQL SQLGlot canonicalization plus SHA-256.

## Task 2: Attempt History and Repair Budget

**Files:**

- Create: `app/reflection/models.py`
- Create: `app/reflection/service.py`
- Create: `app/reflection/__init__.py`
- Test: `tests/unit/test_attempt_history.py`

- [ ] Write failing tests for attempt 0 and immutable history.
- [ ] Add validation/execution recording invariants.
- [ ] Add accepted, duplicate and exhausted repair registration.
- [ ] Prove only accepted unique repairs increment `repair_count`.
- [ ] Cover A→B→A and three-repair maximum.

## Task 3: Deterministic Reflection Decisions

**Files:**

- Modify: `app/reflection/models.py`
- Modify: `app/reflection/service.py`
- Test: `tests/unit/test_reflection_routing.py`
- Test: `tests/security/test_reflection_safety.py`

- [ ] Map syntax, Schema and dialect errors to exact repair routes.
- [ ] Map ambiguity/business knowledge to clarification.
- [ ] Map permission, connection, timeout, duplicate and unknown to finalize.
- [ ] Allow resource clarification only with an explicit safe-reduction flag.
- [ ] Prove budget exhaustion returns no repair strategy.
- [ ] Prove hard errors cannot register a repair.

## Task 4: Repair Integration

**Files:**

- Create: `tests/integration/test_reflection_repair_pipeline.py`

- [ ] Reproduce the Gold reflection Case missing-column `SCHEMA_ERROR`.
- [ ] Decide re-Linking, accept one distinct Stub repair, then re-Link, validate
  and execute against real Pagila.
- [ ] Verify attempt result persistence and `repair_count=1`.
- [ ] Verify duplicate and A→B→A candidates never reach execution.

## Task 5: Documentation, Review, Commit

**Files:**

- Create: `docs/decisions/0007-reflection-repair.md`
- Modify: `README.md`
- Modify: `docs/MVP_EXECUTION_PLAN.md`

- [ ] Document fingerprint namespaces, history invariants and routing.
- [ ] Run unit, security, integration, compileall, pip check, Compose, diff,
  protected hashes and scoped secret scan.
- [ ] Dispatch one independent read-only reviewer.
- [ ] Fix all blocking/high findings through failing tests.
- [ ] Record counts and final verdict.
- [ ] Commit `feat: complete stage 7 reflection repair`.
- [ ] Push `codex/mvp-stages-3-10`.

## Plan Self-Review

- All P0 reflection/budget/fingerprint requirements map to Tasks 1–4.
- Repair acceptance is separate from model invocation and graph routing.
- Duplicate/budget checks happen before validation or execution.
- Hard failures have no SQL repair strategy.
