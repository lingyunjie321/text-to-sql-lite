# Stage 4 Deterministic Schema Linking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a deterministic, authorization-scoped BM25 Schema Linker with fixed Top-K=10 and FK JOIN Path expansion.

**Architecture:** A pure `app.schema_linking` package filters the Stage 2 snapshot to the trusted authorization scope, builds in-memory table/field documents for each call, scores them with a small local BM25 implementation, adds authorized FK intermediates within the fixed table budget, and returns immutable Stage 8-ready contracts. It performs no database, model, cache, or SQL execution.

**Tech Stack:** Python 3.12 standard library, frozen/slotted dataclasses, Stage 2 metadata models and fingerprint builder, pytest 9.1.1, PostgreSQL 16.14, Pagila 3.1.0.

## Global Constraints

- Do not modify the main specification, test specification, or Pagila JSONL.
- Do not add a production dependency.
- `TOP_K` is exactly 10 and is not a function parameter.
- Filter unauthorized metadata before tokenization, document statistics, scoring, paths, and result fingerprinting.
- Do not read Gold tables, fields, SQL, tags, or fixture data in production code.
- Do not implement Embedding, RRF, Rerank, dynamic Top-K, Few-shot, RAG, LLM, Workflow, API, cache, or persistence.
- All public result models are frozen/slotted and contain no connector or driver objects.
- Execute all tasks in one Stage 4 commit on `codex/mvp-stages-3-10`; task-level commit examples below are review checkpoints only and are superseded by the user's stage-level commit rule.

---

## Task 1: Immutable Linking Contracts

**Files:**

- Create: `app/schema_linking/__init__.py`
- Create: `app/schema_linking/models.py`
- Test: `tests/unit/test_schema_linking_models.py`

**Interfaces:**

- Produces `CandidateTable`, `CandidateField`, `JoinEdge`, `JoinPath`,
  `SchemaLinkingResult`, and `TOP_K`.

- [ ] Write a failing test that imports all six models and `TOP_K`, constructs
  a result, verifies tuple collections, exact object IDs, and frozen mutation
  failure.
- [ ] Run
  `.venv/bin/python -m pytest tests/unit/test_schema_linking_models.py -v`
  and verify collection fails because `app.schema_linking` is absent.
- [ ] Implement the exact dataclasses from the design. Round stored scores to
  12 decimal places in factory helpers so repr/order evidence is stable.
- [ ] Export only the public contracts and `link_schema` placeholder-free
  names from `__init__.py`.
- [ ] Run the focused test and `compileall`.

## Task 2: Authorization-Filtered Snapshot

**Files:**

- Create: `app/schema_linking/linker.py`
- Test: `tests/unit/test_schema_linker_authorization.py`
- Test: `tests/security/test_schema_linker_permissions.py`

**Interfaces:**

- Produces
  `link_schema(question, *, allowed_schemas, allowed_tables, snapshot)`.

- [ ] Build literal authorized and unauthorized tables with distinct aliases,
  comments, fields, keys, and FK endpoints.
- [ ] Write failing tests asserting unauthorized words produce no candidate,
  score, evidence, field, path, or schema-version change.
- [ ] Write failing tests for empty scope and malformed unqualified table
  scope; the latter must raise only
  `ValueError("schema linking context is invalid")`.
- [ ] Run focused tests and verify failure because authorization filtering is
  missing.
- [ ] Implement `_authorized_snapshot()` with
  `normalize_metadata_scope()` and `build_schema_snapshot()`. Retain only
  authorized tables and constraints whose referenced tables/columns remain
  visible. Keep FK only when both endpoints are visible.
- [ ] Return an empty result using the filtered empty snapshot version for an
  empty authorization scope.
- [ ] Run authorization unit and security tests green.

## Task 3: Tokenization and BM25

**Files:**

- Modify: `app/schema_linking/linker.py`
- Test: `tests/unit/test_schema_linker_scoring.py`

**Interfaces:**

- Internal `_tokenize(text)`, `_BM25`, `_table_documents()`, and
  `_field_documents()`.

- [ ] Write failing behavior tests for snake_case, camelCase, Unicode NFKC,
  direct table name, direct field name, explicit alias, and comment matches.
- [ ] Add a two-table same-field fixture and assert table-name evidence
  disambiguates ranking.
- [ ] Run tests and verify candidates are absent or scores are zero.
- [ ] Implement tokenizer using only `unicodedata`, `re`, and `casefold()`.
  Preserve full normalized identifiers plus split parts; discard empty tokens.
- [ ] Implement BM25 with fixed `k1=1.5`, `b=0.75`, literal IDF formula, and
  zero-safe empty-corpus/average-length behavior.
- [ ] Weight names/aliases by repeated document tokens, comments once.
- [ ] Aggregate the top three field scores with multiplier `0.35`.
- [ ] Sort by score descending then canonical object ID.
- [ ] Run scoring and earlier tests green.

## Task 4: Fixed Top-K and Candidate Fields

**Files:**

- Modify: `app/schema_linking/linker.py`
- Test: `tests/unit/test_schema_linker_top_k.py`

**Interfaces:**

- Produces maximum 10 `CandidateTable` values and every field belonging to
  those tables.

- [ ] Write a failing 12-table noise test where two named Gold-like tables rank
  in the result and total candidates equal 10.
- [ ] Write a failing no-match test for 4 authorized tables and assert all four
  return in canonical order with zero score.
- [ ] Write a failing no-match test for 12 authorized tables and assert exactly
  the canonical first 10 return.
- [ ] Assert every candidate field belongs to a returned table and all fields
  of each returned table are present.
- [ ] Implement `TOP_K=10` selection with no caller override and stable fallback.
- [ ] Order fields by table rank, field score descending, and object ID.
- [ ] Run Top-K, scoring, authorization, and contract tests green.

## Task 5: Authorized FK Path Expansion

**Files:**

- Modify: `app/schema_linking/linker.py`
- Test: `tests/unit/test_schema_linker_join_paths.py`
- Modify: `tests/security/test_schema_linker_permissions.py`

**Interfaces:**

- Produces deterministic `JoinEdge` and `JoinPath`.

- [ ] Build a fixture `film → film_category → category` plus an unauthorized
  shortcut edge.
- [ ] Write a failing test where question evidence selects `film` and
  `category`, and `film_category` is inserted as the intermediate candidate.
- [ ] Assert composite FK source/target column order is preserved.
- [ ] Assert an unreachable candidate produces no fabricated path.
- [ ] Assert unauthorized shortcut nodes/constraints never appear.
- [ ] Run tests and verify paths/intermediate candidates are missing.
- [ ] Implement a bidirectional authorized adjacency list and deterministic BFS
  ordered by neighbor table then constraint name.
- [ ] Incrementally add ranked candidates and required path nodes only while
  the union remains within `TOP_K`.
- [ ] Emit one deduplicated shortest path for each connected returned table
  pair whose complete path is already in the selected set.
- [ ] Run join, Top-K, and security tests green.

## Task 6: Schema Version and Pagila Integration

**Files:**

- Test: `tests/unit/test_schema_linker_version.py`
- Create: `tests/integration/test_pagila_schema_linking.py`
- Modify production only for test-proven defects.

**Interfaces:**

- Consumes real Stage 2 snapshots and the read-only Pagila Case file in tests.

- [ ] Write a failing unit test proving an authorized comment/alias/field
  change changes the result version and ranking.
- [ ] Prove an unauthorized-only change does not change the authorized result
  version or candidates.
- [ ] Parameterize PG-MVP-001–014 and PG-MVP-018. Build authorization only from
  each Case's `allowed_tables`; do not pass `gold_tables`, `gold_fields`,
  `gold_sql`, tags, or fixture data to production.
- [ ] Assert returned tables contain every `gold_table`, fields contain every
  `gold_field`, all results remain authorized, and candidate count is at most
  10.
- [ ] Assert every emitted path edge exists in the real authorized snapshot.
- [ ] Run the focused real Pagila integration tests.
- [ ] Run all Stage 1–4 unit, security, and integration regressions.

## Task 7: Documentation, Review, and Stage Gate

**Files:**

- Create: `docs/decisions/0004-deterministic-schema-linking.md`
- Modify: `README.md`
- Modify: `docs/MVP_EXECUTION_PLAN.md`

**Interfaces:**

- Records algorithm, security boundary, tests, review, exclusions, and commit.

- [ ] Document tokenization, BM25 constants, field aggregation, fallback,
  Top-K, FK BFS, authorization filtering, version semantics, and Stage 5
  exclusions.
- [ ] Update README with a trusted-snapshot `link_schema()` example and exact
  implementation status.
- [ ] Run fresh:
  - `.venv/bin/python -m pytest tests/unit -q`
  - `.venv/bin/python -m pytest tests/security -q`
  - `.venv/bin/python -m pytest tests/integration -q -m integration`
  - `.venv/bin/python -m compileall -q app tools tests`
  - `.venv/bin/python -m pip check`
  - `docker compose -f infrastructure/pagila/compose.yaml config --quiet`
  - `git diff --check`
  - protected-file SHA-256 checks.
- [ ] Dispatch an independent read-only reviewer for correctness, permissions,
  interface compatibility, test gaps, leakage, and scope drift.
- [ ] Fix all blocking/high findings through new failing tests and rerun the
  complete gate.
- [ ] Update the execution ledger with verified counts and review verdict.
- [ ] Commit once with `feat: complete stage 4 schema linking`.
- [ ] Push `codex/mvp-stages-3-10`.

## Plan Self-Review

- Every main-spec Stage 4 behavior maps to Tasks 2–6.
- Every test-spec Schema Linking P0 item has a named test.
- The plan contains no Embedding, RRF, Rerank, dynamic Top-K, cache, model,
  Workflow, API, or Gold-data production input.
- Public types match the design and future `SQLTaskState` names without adding
  Stage 8 state.
- Authorization filtering precedes all index statistics and graph building.
- All production behavior is introduced only after a failing test.
