# Stage 5 Structured SQL Generation Implementation Plan

**Goal:** Add a strict OpenAI-compatible provider and deterministic authorized
prompt that returns exactly SQL or clarification without executing or trusting
model output.

**Architecture:** `app.generation` validates a same-version Stage 4 context,
serializes only authorized candidates and real key metadata, invokes an
`LLMProvider` protocol, and returns a frozen unified result. The default provider
uses the standard library HTTP stack and Pydantic validation.

**Tech Stack:** Python 3.12 standard library, Pydantic 2.12.5,
pydantic-settings 2.14.2, pytest 9.1.1.

## Constraints

- Do not modify protected specs or Pagila JSONL.
- Do not add a production dependency.
- Do not read `.env` in production code except through explicit settings load.
- Never expose API key, URL, Prompt, response body, model content, or raw error.
- Never execute or auto-approve generated SQL.
- No Few-shot, Gold input, RAG, reflection, workflow, API, trace, or comparator.
- One Stage 5 commit on `codex/mvp-stages-3-10`.

## Task 1: Strict Models and LLM Configuration

**Files:**

- Create: `app/generation/__init__.py`
- Create: `app/generation/models.py`
- Modify: `app/config.py`
- Test: `tests/unit/test_generation_models.py`
- Test: `tests/unit/test_llm_config.py`

- [ ] Write failing imports and XOR/frozen tests for `GeneratedSQL`,
  `GenerationContext`, `GenerationResult`, messages, usage and provider errors.
- [ ] Write failing settings tests for required environment values, Secret repr,
  URL restrictions, timeout bounds and `temperature=0`.
- [ ] Observe failures before implementation.
- [ ] Implement the smallest Pydantic/dataclass contracts and independent
  `load_llm_settings()`.
- [ ] Run focused tests and compileall.

## Task 2: Deterministic Authorized Prompt

**Files:**

- Create: `app/generation/prompt.py`
- Test: `tests/unit/test_generation_prompt.py`
- Test: `tests/security/test_generation_prompt_security.py`

- [ ] Build a literal authorized snapshot and Stage 4 result.
- [ ] Write failing tests for deterministic System/User messages, explicit
  PostgreSQL/read-only/no-wildcard/JSON rules and normalized time.
- [ ] Assert only candidate objects, candidate PK/FK and supplied JOIN paths
  appear; unrelated snapshot metadata must not.
- [ ] Assert malicious question/comment strings remain JSON data and never alter
  the fixed System message.
- [ ] Assert Gold SQL/Case files and secrets are never read or serialized.
- [ ] Implement context validation and canonical JSON serialization.
- [ ] Keep all public context failures generic and run focused tests green.

## Task 3: OpenAI-compatible Provider

**Files:**

- Create: `app/generation/provider.py`
- Test: `tests/unit/test_llm_provider.py`
- Test: `tests/security/test_llm_provider_security.py`

- [ ] Write a fake transport and failing request-shape test.
- [ ] Assert endpoint, headers, `model`, `temperature=0`, messages,
  `response_format=json_object` and timeout.
- [ ] Test SQL and clarification responses, usage defaults and exact model.
- [ ] Test timeout, connection, HTTP status, oversized body, invalid envelope,
  invalid JSON and invalid XOR.
- [ ] Assert public errors and repr never include key, URL, Prompt, body, SQL or
  raw exception.
- [ ] Implement `LLMProvider` Protocol, standard-library transport and strict
  response parsing with a 1 MiB limit.
- [ ] Run provider unit/security tests green.

## Task 4: Generation Service and Safety Boundary

**Files:**

- Create: `app/generation/service.py`
- Test: `tests/unit/test_generation_service.py`
- Test: `tests/security/test_generated_sql_safety.py`

- [ ] Write failing tests proving the service calls Provider once and preserves
  output, Token and prompt version.
- [ ] Reject empty question/candidates, non-PostgreSQL dialect, version mismatch,
  missing objects/fields and fabricated path edges before Provider call.
- [ ] Use a malicious Stub that returns DELETE/multi-statement/UDF SQL; assert the
  generation layer does not execute it and Stage 3 validator rejects it.
- [ ] Implement `generate_sql()` as validate → prompt → provider, with no
  Connector dependency.
- [ ] Run all Stage 5 unit/security tests.

## Task 5: Protocol and Pipeline Integration

**Files:**

- Create: `tests/integration/test_openai_compatible_provider.py`
- Create: `tests/integration/test_generation_validation_pipeline.py`

- [ ] Start an in-process localhost HTTP server on an ephemeral port and verify
  the real urllib request/response path without external credentials.
- [ ] Use deterministic Stub responses for Linking → Generate → Validate on
  single-table, JOIN and clarification inputs.
- [ ] Prove candidate version and authorization survive the boundary.
- [ ] Run Stage 1–5 integration and all earlier regression tests.

## Task 6: Documentation, Independent Review, Commit

**Files:**

- Create: `docs/decisions/0005-openai-compatible-generation.md`
- Modify: `README.md`
- Modify: `docs/MVP_EXECUTION_PLAN.md`

- [ ] Document Provider protocol, Prompt version, strict output, config,
  security boundary, errors and Stage 6+ exclusions.
- [ ] Update README with safe configuration and Stub/provider usage.
- [ ] Run fresh unit, security, integration, compileall, pip check, Compose,
  diff, protected hashes and scoped secret scan.
- [ ] Dispatch one independent read-only reviewer for correctness, provider
  compatibility, authorization, leakage, interface compatibility, test gaps and
  scope drift.
- [ ] Fix every blocking/high finding through failing tests and rerun the gate.
- [ ] Update the execution ledger with counts and verdict.
- [ ] Commit `feat: complete stage 5 SQL generation`.
- [ ] Push `codex/mvp-stages-3-10`.

## Plan Self-Review

- All Stage 5 main-spec behaviors map to Tasks 1–5.
- Provider abstraction prevents business code from depending on a vendor SDK.
- Prompt includes no Gold/Few-shot/RAG and cannot replace Stage 3 validation.
- No production dependency, execution, reflection, workflow or API is added.
- All safety and context checks happen before the model call or after strict
  provider parsing; raw provider data never enters public errors.
