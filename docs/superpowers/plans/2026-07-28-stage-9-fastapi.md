# Stage 9 FastAPI Implementation Plan

**Goal:** Expose the Stage 8 workflow through the one specified synchronous
FastAPI endpoint with strict request/response models and trusted bootstrap.

**Architecture:** FastAPI owns HTTP validation, request/trace IDs, trusted
identity and response mapping. Stage 8 remains the only workflow/router and
trusted runtime context carries the fixed Pagila allowlist.

**Tech Stack:** Python 3.12, FastAPI 0.139.2, Pydantic 2, HTTPX2 2.9.1 for
tests, existing Stage 1–8 modules.

## Constraints

- Do not modify protected specs or Gold JSONL.
- Add only the specification-approved FastAPI production dependency.
- Keep HTTPX2 test-only.
- Do not change Stage 1–8 public interfaces.
- Do not expose SQL on failures, secrets, Prompts, raw errors or stacks.
- Do not implement Trace sink, comparator or evaluation.
- One Stage 9 commit on `codex/mvp-stages-3-10`.

## Task 1: Dependencies and API Models

**Files:**

- Modify: `pyproject.toml`
- Create: `app/api/models.py`
- Create: `app/api/__init__.py`
- Test: `tests/unit/test_api_models.py`

- [x] Write failing request/response contract tests.
- [x] Pin/install FastAPI and test-only HTTPX2.
- [x] Implement strict QueryRequest, QueryResponse, result columns,
  clarification and public errors.
- [x] Enforce terminal response mutual exclusion.

## Task 2: Response Mapping and Trusted Dependencies

**Files:**

- Create: `app/api/bootstrap.py`
- Test: `tests/unit/test_api_response_mapping.py`
- Test: `tests/security/test_api_permissions.py`

- [x] Map all Stage 8 terminal states without serializing State directly.
- [x] Return SQL/results only on success.
- [x] Implement fixed identity and debug authorization.
- [x] Define the explicit 13-table Pagila allowlist.
- [x] Prove request fields cannot inject dependencies or expand permissions.

## Task 3: FastAPI Application and Lifespan

**Files:**

- Create: `app/api/application.py`
- Create: `app/main.py`
- Test: `tests/unit/test_api_application.py`
- Test: `tests/security/test_api_permissions.py`

- [x] Implement POST `/api/v1/text-to-sql`.
- [x] Generate independent request/trace UUIDs.
- [x] Return fixed 403 debug denial and 500 internal failure responses.
- [x] Implement fail-closed production lifespan and injected test services.
- [x] Assert OpenAPI request/response schema.

## Task 4: Real Pagila HTTP Integration

**Files:**

- Create: `tests/integration/test_api_pagila.py`

- [x] Run Stub Provider + real Connector through TestClient.
- [x] Cover first-pass success, legal empty result and one Schema repair.
- [x] Prove permissions and dangerous SQL stay zero-execution at HTTP boundary.

## Task 5: Documentation, Review, Commit

**Files:**

- Create: `docs/decisions/0009-fastapi-boundary.md`
- Modify: `README.md`
- Modify: `docs/MVP_EXECUTION_PLAN.md`

- [x] Run unit, security, integration, compileall, pip check, Compose, diff,
  protected hashes and scoped secret scan.
- [x] Dispatch an independent read-only reviewer.
- [x] Fix all blocking/high findings through failing tests.
- [x] Record counts and verdict.
- [x] Commit `feat: complete stage 9 FastAPI`.
- [x] Push `codex/mvp-stages-3-10`.
