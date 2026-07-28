# Stage 8 LangGraph Workflow Implementation Plan

**Goal:** Compose the nine specified nodes into a deterministic LangGraph
workflow with strict state, complete routing, three repairs, 32 steps and a
120-second request budget.

**Architecture:** Pydantic state stores only workflow data; a frozen LangGraph
context carries trusted Connector, Provider, permissions and clocks. Existing
Stage 1–7 services remain the sole owners of metadata, generation, validation,
execution and reflection behavior.

**Tech Stack:** Python 3.12, Pydantic 2 (resolved 2.13.4), LangGraph 1.2.9, existing
Stage 1–7 modules, pytest 9.1.1.

## Constraints

- Do not modify protected specs or Pagila JSONL.
- Add only the specification-approved pinned LangGraph production dependency.
- Do not use prebuilt agents, checkpoints, memory, tools or LangChain model SDKs.
- Do not change Stage 1–7 public interfaces.
- Do not put Provider, Connector, secrets, Prompt or raw errors in state.
- Do not implement FastAPI, trace sink, comparator or evaluation.
- One Stage 8 commit on `codex/mvp-stages-3-10`.

## Task 1: Dependency and Strict Workflow Models

**Files:**

- Modify: `pyproject.toml`
- Modify: `app/connectors/postgresql.py` (private retry observation only)
- Create: `app/workflow/models.py`
- Create: `app/workflow/__init__.py`
- Test: `tests/unit/test_workflow_models.py`

- [x] Write failing imports and State/final-status/observability tests.
- [x] Pin and install `langgraph==1.2.9`.
- [x] Implement strict State, Context, FinalStatus, Clarification, PublicError,
  TokenUsage and NodeTiming.
- [x] Validate attempt/history and terminal-state invariants.

## Task 2: Preprocess and Permission Nodes

**Files:**

- Create: `app/workflow/preprocess.py`
- Create: `app/workflow/nodes.py`
- Test: `tests/unit/test_workflow_preprocess.py`
- Test: `tests/security/test_workflow_permissions.py`

- [x] Cover NFKC, whitespace, 1–2000 and injected relative dates.
- [x] Cover trusted datasource/Schema/table intersection.
- [x] Prove invalid/overbroad requests call Connector/Provider zero times.
- [x] Implement fixed public errors and clarification templates.

## Task 3: Generation, Validation, Execution and Reflection Nodes

**Files:**

- Modify: `app/workflow/nodes.py`
- Test: `tests/unit/test_workflow_graph.py`
- Test: `tests/security/test_workflow_routing.py`

- [x] Build authorized GenerationContext from state.
- [x] Add only structured repair metadata to the canonical User payload.
- [x] Register initial/repair attempts and accumulate Token.
- [x] Bind validation and execute only through Stage 6.
- [x] Route every ErrorType exactly per main-spec table.
- [x] Prove dangerous, duplicate, connection and timeout paths never enter
  forbidden downstream calls.

## Task 4: Compile and Run the Nine-node Graph

**Files:**

- Create: `app/workflow/graph.py`
- Test: `tests/unit/test_workflow_graph.py`
- Test: `tests/integration/test_workflow_pagila.py`

- [x] Assert exact nine-node set and conditional edges.
- [x] Cover first-pass, empty result, clarification, repaired, duplicate and
  exhausted outcomes with deterministic Stubs.
- [x] Enforce 32 business-node steps and 120-second deadline.
- [x] Run Stub Provider + real Pagila first-pass and repaired loops.

## Task 5: Documentation, Review, Commit

**Files:**

- Create: `docs/decisions/0008-langgraph-workflow.md`
- Modify: `README.md`
- Modify: `docs/MVP_EXECUTION_PLAN.md`

- [x] Document dependency/API choice, State/Context boundary and routing.
- [x] Run unit, security, integration, compileall, pip check, Compose, diff,
  protected hashes and scoped secret scan.
- [x] Dispatch one independent read-only reviewer.
- [x] Fix every blocking/high finding through failing tests.
- [x] Record counts and verdict.
- [ ] Commit `feat: complete stage 8 LangGraph workflow`.
- [ ] Push `codex/mvp-stages-3-10`.

## Plan Self-Review

- All nine required nodes are explicit and independently testable.
- Workflow loops only through Stage 7 decisions and budgets.
- Runtime dependencies cannot be serialized into State.
- Framework recursion and business step/deadline checks are separate fail-safe
  layers.
