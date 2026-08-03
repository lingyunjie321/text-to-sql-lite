# Local Model Phase 4 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow a local user to test and select an OpenAI-compatible ModelProfile at runtime, run all generation routes through that model, and use BM25-only when Embedding is absent or safely degraded.

**Architecture:** Add a model runtime service and registry beside the existing datasource runtime boundary. The Profile resolver combines a cached datasource connector with a cached model routing/optional Embedding runtime into a WorkflowContext; static `.env` resources remain a compatibility path but become optional as complete groups.

**Tech Stack:** Python 3.11+, FastAPI, Pydantic v2, pydantic-settings, SQLite, existing urllib-based OpenAI-compatible providers, pytest, Vitest.

## Global Constraints

- Work directly on local `main`; do not create branches, worktrees, or pull requests.
- Do not add dependencies or new model/database provider protocols.
- Do not modify Workflow graph nodes, Workflow State, repair limits, Comparator, Pagila Gold cases, or frontend settings behavior.
- Dynamic generation maps one provider to simple, standard, and complex routes; dynamic fallback remains disabled.
- Non-loopback endpoints require HTTPS; only localhost and IP loopback may use HTTP.
- API keys remain process-local and must not appear in SQLite, OpenAPI responses, logs, Trace, exceptions, or test output.
- Missing Embedding means BM25-only; approved Embedding failures may only degrade within the current authorization and Schema version.
- Preserve the user's existing `AGENTS.md` change and never stage it.

---

### Task 1: Extend ModelProfile and migrate the non-sensitive store

**Files:**
- Modify: `app/local/profile_models.py`
- Modify: `app/local/profile_store.py`
- Modify: `app/api/profile_models.py`
- Test: `tests/unit/test_profile_models.py`
- Test: `tests/unit/test_profile_store.py`
- Test: `tests/security/test_profile_credentials.py`

**Interfaces:**
- Consumes: existing `ModelProfile`, `ModelProfileCreate`, and `LocalProfileStore` CRUD contracts.
- Produces: `ModelProfile.embedding_dimension: StrictInt | None`; SQLite `user_version=2`; a v1→v2 migration that only adds `embedding_dimension`.

- [ ] **Step 1: Write failing model validation tests**

```python
def test_embedding_configuration_requires_endpoint_model_and_dimension() -> None:
    base = {
        "id": "local-model",
        "name": "Local Model",
        "provider_type": "openai_compatible",
        "base_url": "http://localhost:11434/v1",
        "model_name": "qwen2.5-coder",
    }
    with pytest.raises(ValidationError):
        ModelProfile(**base, embedding_model="nomic-embed-text")
    with pytest.raises(ValidationError):
        ModelProfile(
            **base,
            embedding_base_url="http://localhost:11434/v1",
            embedding_model="nomic-embed-text",
        )
    profile = ModelProfile(
        **base,
        embedding_base_url="http://localhost:11434/v1",
        embedding_model="nomic-embed-text",
        embedding_dimension=768,
    )
    assert profile.embedding_dimension == 768
```

- [ ] **Step 2: Run the focused validation test and verify RED**

Run: `pytest tests/unit/test_profile_models.py -q`

Expected: FAIL because `embedding_dimension` is currently forbidden.

- [ ] **Step 3: Add the strict optional dimension field and three-field invariant**

```python
embedding_dimension: StrictInt | None = Field(default=None, ge=1, le=1_000_000)

@model_validator(mode="after")
def validate_embedding_group(self) -> Self:
    configured = (
        self.embedding_base_url is not None,
        self.embedding_model is not None,
        self.embedding_dimension is not None,
    )
    if len(set(configured)) != 1:
        raise ValueError("embedding configuration is incomplete")
    return self
```

- [ ] **Step 4: Write failing store migration and round-trip tests**

Create a v1 database with the existing seven model columns, insert one model row, set `PRAGMA user_version=1`, construct `LocalProfileStore`, then assert version 2, the new column is present, and the old row loads with `embedding_dimension is None`. Add a v2 round-trip case with dimension 768 and scan the database artifacts for sentinel API keys.

- [ ] **Step 5: Run the focused store/security tests and verify RED**

Run: `pytest tests/unit/test_profile_store.py tests/security/test_profile_credentials.py -q`

Expected: FAIL because the store only accepts schema version 1 and does not persist the dimension.

- [ ] **Step 6: Implement the transactional v1→v2 migration and CRUD column updates**

Set `_SCHEMA_VERSION = 2`, add `embedding_dimension` to `_EXPECTED_SCHEMA`, include the column and three-field CHECK constraint for new databases, and migrate v1 with:

```sql
BEGIN IMMEDIATE;
ALTER TABLE model_profiles ADD COLUMN embedding_dimension INTEGER;
PRAGMA user_version=2;
COMMIT;
```

Validate the exact schema after migration and update create/replace/row conversion parameter lists. Roll back and raise the existing safe store errors on failure.

- [ ] **Step 7: Run Task 1 tests and commit**

Run: `pytest tests/unit/test_profile_models.py tests/unit/test_profile_store.py tests/security/test_profile_credentials.py -q`

Expected: PASS.

Commit:

```bash
git add app/local/profile_models.py app/local/profile_store.py app/api/profile_models.py tests/unit/test_profile_models.py tests/unit/test_profile_store.py tests/security/test_profile_credentials.py
git commit -m "feat: extend local model profiles"
```

---

### Task 2: Permit no-auth OpenAI-compatible providers without leaking headers

**Files:**
- Modify: `app/config/model.py`
- Modify: `app/config/embedding.py`
- Modify: `app/generation/provider.py`
- Modify: `app/schema_linking/embedding.py`
- Test: `tests/unit/test_llm_provider.py`
- Test: `tests/unit/test_embedding_provider.py`
- Test: `tests/security/test_llm_provider_security.py`
- Test: `tests/security/test_embedding_provider_security.py`

**Interfaces:**
- Consumes: `LLMSettings`, `EmbeddingSettings`, and the two existing urllib Provider classes.
- Produces: optional `api_key: SecretStr | None`; Provider requests omit `Authorization` when the key is absent.

- [ ] **Step 1: Write failing request-header tests**

```python
def test_llm_provider_omits_authorization_without_api_key() -> None:
    transport = RecordingTransport(_valid_generation_response())
    provider = OpenAICompatibleLLMProvider(
        LLMSettings(
            base_url="http://localhost:11434/v1",
            api_key=None,
            model="qwen2.5-coder",
        ),
        transport=transport,
    )
    provider.generate(_generation_request())
    assert "Authorization" not in dict(transport.request.header_items())
```

Add the equivalent Embedding test and retain the current assertions that a configured key is sent as `Bearer <secret>` without entering repr/error output.

- [ ] **Step 2: Run provider tests and verify RED**

Run: `pytest tests/unit/test_llm_provider.py tests/unit/test_embedding_provider.py -q`

Expected: FAIL because both settings require a key and both Providers always add the Header.

- [ ] **Step 3: Make credentials optional and build headers conditionally**

```python
headers = {"Content-Type": "application/json"}
if self._settings.api_key_value is not None:
    headers["Authorization"] = f"Bearer {self._settings.api_key_value}"
```

Return `str | None` from each `api_key_value` property. Keep the current validation for non-null keys and never substitute a fake key.

- [ ] **Step 4: Run provider and security tests and commit**

Run: `pytest tests/unit/test_llm_provider.py tests/unit/test_embedding_provider.py tests/security/test_llm_provider_security.py tests/security/test_embedding_provider_security.py -q`

Expected: PASS.

Commit:

```bash
git add app/config/model.py app/config/embedding.py app/generation/provider.py app/schema_linking/embedding.py tests/unit/test_llm_provider.py tests/unit/test_embedding_provider.py tests/security/test_llm_provider_security.py tests/security/test_embedding_provider_security.py
git commit -m "feat: support no-auth local model endpoints"
```

---

### Task 3: Build and test one dynamic model runtime

**Files:**
- Create: `app/local/model_runtime.py`
- Modify: `app/generation/factory.py`
- Modify: `app/local/__init__.py`
- Test: `tests/unit/test_model_runtime.py`
- Test: `tests/unit/test_model_provider_factory.py`

**Interfaces:**
- Consumes: `ModelProfile`, `ModelCredentials`, `ModelProviderFactory`, `OpenAICompatibleEmbeddingProvider`.
- Produces: `ModelRuntime(profile, model_routing, embedding_provider, embedding_registry)`; `ModelRuntimeService.build_runtime(profile, credentials)`; `ModelRuntimeService.test_connection(profile, credentials)`.

- [ ] **Step 1: Write failing single-provider routing tests**

```python
def test_dynamic_runtime_maps_one_provider_to_all_primary_routes() -> None:
    runtime = service.build_runtime(profile, ModelCredentials())
    targets = tuple(route.primary for route in runtime.model_routing.route_table.routes)
    assert {target.provider_key for target in targets} == {"primary"}
    assert len({target.model_config_sha256 for target in targets}) == 1
    assert all(route.fallback is None for route in runtime.model_routing.route_table.routes)
```

Also assert no Embedding creates `embedding_provider is None`, while complete Embedding settings create a Provider with the exact model and dimension.

- [ ] **Step 2: Run the new runtime tests and verify RED**

Run: `pytest tests/unit/test_model_runtime.py tests/unit/test_model_provider_factory.py -q`

Expected: FAIL because `app.local.model_runtime` and a public single-provider factory method do not exist.

- [ ] **Step 3: Add a surgical single-provider factory method**

Add `ModelProviderFactory.create_single(settings: LLMSettings, *, data_boundary_id: str) -> ModelRoutingRuntime`. It creates one Provider and calls the existing `build_single_provider_routing_runtime` with the current model Hash and fixed token/timeout values. Keep `create(LLMRouteSettings)` unchanged.

- [ ] **Step 4: Implement ModelRuntimeService construction**

Use fixed phase-4 settings:

```python
LLMSettings(
    base_url=profile.base_url,
    api_key=credentials.generation_api_key,
    model=profile.model_name,
    timeout_seconds=30,
    temperature=0,
    max_input_tokens=32_768,
    max_output_tokens=2_048,
)
```

When Embedding is configured, construct `EmbeddingSettings` with timeout 10, batch 10, response limit 4,194,304 and the explicit dimension. Use a data boundary derived from the Profile ID, never from a request body route name.

- [ ] **Step 5: Write failing connection-test behavior tests**

Inject deterministic Provider builders. Assert the generation probe is called exactly once with a minimal real `GenerationRequest`; absent Embedding returns `not_configured`; successful Embedding returns `connected`; a safe Embedding error returns `unavailable` with only its stable code; generation failure raises `ModelRuntimeError` with a stable public status/code.

- [ ] **Step 6: Implement connection-test result and error types**

```python
@dataclass(frozen=True, slots=True)
class ModelConnectionTestResult:
    generation_status: Literal["connected"]
    embedding_status: Literal["connected", "not_configured", "unavailable"]
    embedding_error_code: str | None = None

class ModelRuntimeError(RuntimeError):
    def __init__(self, *, code: str, public_message: str, status_code: int) -> None:
        super().__init__(public_message)
        self.code = code
        self.public_message = public_message
        self.status_code = status_code
```

Map Provider errors without retaining exception strings. Validate that the generation probe returns one valid structured `GenerationResult`; do not expose SQL or clarification content.

- [ ] **Step 7: Run Task 3 tests and commit**

Run: `pytest tests/unit/test_model_runtime.py tests/unit/test_model_provider_factory.py -q`

Expected: PASS.

Commit:

```bash
git add app/local/model_runtime.py app/local/__init__.py app/generation/factory.py tests/unit/test_model_runtime.py tests/unit/test_model_provider_factory.py
git commit -m "feat: build dynamic model runtimes"
```

---

### Task 4: Cache and invalidate model runtimes

**Files:**
- Create: `app/local/model_runtime_registry.py`
- Modify: `app/local/model_service.py`
- Modify: `app/local/credential_store.py`
- Test: `tests/unit/test_model_runtime_registry.py`
- Test: `tests/unit/test_profile_services.py`

**Interfaces:**
- Consumes: `ModelRuntimeService.build_runtime`, `ModelProfileService` writes, and the process-local credential store.
- Produces: `ModelRuntimeRegistry.get_or_create(profile)`, `invalidate(profile_id, expected_profile=None)`, and `close_all()`.

- [ ] **Step 1: Write failing registry lifecycle tests**

Cover: same identity reuses one runtime; two concurrent first calls build once; a failed build is not cached; retry succeeds; expected identity rejects an old Profile after replace; `close_all` clears runtimes and expected identities.

- [ ] **Step 2: Run registry tests and verify RED**

Run: `pytest tests/unit/test_model_runtime_registry.py -q`

Expected: FAIL because the registry module does not exist.

- [ ] **Step 3: Add credential revision tracking**

Increment an integer revision per Model Profile ID on every `put_model` and `discard_model`; expose `model_revision(profile_id) -> int`. The revision is process-local and contains no secret. Runtime identity is:

```python
(
    profile.provider_type,
    str(profile.base_url),
    profile.model_name,
    str(profile.embedding_base_url) if profile.embedding_base_url else None,
    profile.embedding_model,
    profile.embedding_dimension,
    credential_store.model_revision(profile.id),
)
```

- [ ] **Step 4: Implement the thread-safe Registry**

Mirror the proven datasource Registry lock/expected-identity behavior. Use one `RLock`; never log Provider exceptions, endpoint, model response, or credentials. `close_all` only clears model runtimes and Embedding index references because existing Providers have no close contract.

- [ ] **Step 5: Write failing Profile service invalidation tests**

Assert create records the expected identity, replace invalidates only after Store and credentials succeed, explicit null Key increments the revision, and delete discards credentials then invalidates the runtime. A failed Store write must leave the old runtime usable.

- [ ] **Step 6: Wire optional Registry coordination into ModelProfileService**

Accept `runtime_registry: ModelRuntimeRegistry | None = None`. Serialize create/replace/delete with a service `RLock`, matching the datasource write model. Preserve existing Secret semantics while making missing API keys valid runtime inputs.

- [ ] **Step 7: Run Task 4 tests and commit**

Run: `pytest tests/unit/test_model_runtime_registry.py tests/unit/test_profile_services.py tests/unit/test_credential_store.py -q`

Expected: PASS.

Commit:

```bash
git add app/local/model_runtime_registry.py app/local/model_service.py app/local/credential_store.py tests/unit/test_model_runtime_registry.py tests/unit/test_profile_services.py tests/unit/test_credential_store.py
git commit -m "feat: manage model runtime lifecycle"
```

---

### Task 5: Compose datasource and model runtimes into optional-Embedding contexts

**Files:**
- Modify: `app/api/context_factory.py`
- Modify: `app/local/datasource_runtime.py`
- Modify: `app/local/profile_resolver.py`
- Test: `tests/unit/test_workflow_context_factory.py`
- Test: `tests/unit/test_datasource_runtime.py`
- Test: `tests/unit/test_profile_resolver.py`
- Test: `tests/unit/test_profile_query.py`

**Interfaces:**
- Consumes: existing `DatasourceRuntime`, `RuntimeRegistry`, and new `ModelRuntimeRegistry`.
- Produces: context creation with `embedding_provider: EmbeddingProvider | None` and optional shared `EmbeddingIndexRegistry`; Profile resolution no longer requires static model identity.

- [ ] **Step 1: Write failing BM25-only Context tests**

```python
context = factory.create(
    connector=connector,
    model_routing=routing,
    datasource_id="local-postgres",
    allowed_schemas=("public",),
    allowed_tables=("public.film",),
    embedding_provider=None,
    semantic_version="raw-schema-v1",
)
assert context.retrieval_runtime is None
```

Add a configured Embedding case that passes an injected Registry and asserts the resulting RetrievalRuntime reuses that exact object.

- [ ] **Step 2: Run Context tests and verify RED**

Run: `pytest tests/unit/test_workflow_context_factory.py -q`

Expected: FAIL because the factory rejects `None` and always creates a new Registry.

- [ ] **Step 3: Implement optional Embedding Context creation**

Add `embedding_registry: EmbeddingIndexRegistry | None = None`. Reject a registry without a Provider. With no Provider return a `WorkflowContext` without retrieval runtime; with a Provider use the passed Registry or create one for static compatibility.

- [ ] **Step 4: Expose datasource semantic version without changing Connector ownership**

Add `semantic_version: str` to `DatasourceRuntime`. Populate it when the service builds the current context. Keep the existing `context` field during phase 4 to avoid breaking stage-3 callers; the Profile resolver uses `connector`, Profile allowlist, and `semantic_version` to create the selected model Context.

- [ ] **Step 5: Write failing dynamic pair resolution tests**

Cover dynamic model + dynamic datasource, dynamic model + static datasource, BM25-only model, Embedding model with shared Registry, missing model Profile, model runtime failure, datasource runtime failure, and no fallback to static model/data.

- [ ] **Step 6: Refactor resolver composition minimally**

Keep `StaticProfileResolver` as a compatibility class name. Add `model_runtime_registry` and `context_factory`. Resolve both Profiles first, obtain a dynamic model runtime, obtain the matching static or dynamic datasource runtime, then create the WorkflowContext. Map model errors to stable Profile resolution errors and retain current datasource mappings.

- [ ] **Step 7: Run Task 5 tests and commit**

Run: `pytest tests/unit/test_workflow_context_factory.py tests/unit/test_datasource_runtime.py tests/unit/test_profile_resolver.py tests/unit/test_profile_query.py -q`

Expected: PASS.

Commit:

```bash
git add app/api/context_factory.py app/local/datasource_runtime.py app/local/profile_resolver.py tests/unit/test_workflow_context_factory.py tests/unit/test_datasource_runtime.py tests/unit/test_profile_resolver.py tests/unit/test_profile_query.py
git commit -m "feat: compose profile model contexts"
```

---

### Task 6: Make complete static model groups optional at bootstrap

**Files:**
- Modify: `app/config/model.py`
- Modify: `app/config/embedding.py`
- Modify: `app/config/__init__.py`
- Modify: `app/api/bootstrap.py`
- Test: `tests/unit/test_llm_config.py`
- Test: `tests/unit/test_config.py`
- Test: `tests/unit/test_bootstrap_lifecycle.py`
- Test: `tests/unit/test_api_application.py`

**Interfaces:**
- Consumes: existing environment loaders and `ApplicationServices`.
- Produces: `load_optional_llm_route_settings() -> LLMRouteSettings | None`; `load_optional_embedding_settings() -> EmbeddingSettings | None`; Bootstrap services containing the new runtime service/registry with or without static Contexts.

- [ ] **Step 1: Write failing all-or-none loader tests**

For both generation and Embedding, clear all group variables and assert `None`; provide a complete group and assert settings; provide each representative partial group and assert `ValidationError`. Keep route overrides invalid when the base group is absent.

- [ ] **Step 2: Run config tests and verify RED**

Run: `pytest tests/unit/test_llm_config.py tests/unit/test_config.py -q`

Expected: FAIL because optional loaders do not exist.

- [ ] **Step 3: Implement explicit optional loaders**

Inspect only the named environment variables for each group. Return `None` when every required and optional group variable is absent; otherwise delegate to the strict existing loader so partial settings fail closed. Do not catch broad validation errors.

- [ ] **Step 4: Write failing profile-only Bootstrap tests**

With no database, LLM, or Embedding environment groups, assert application services build with empty static contexts plus Profile services, datasource/model runtime services, and both Registries. With complete static LLM but no Embedding, assert static contexts are BM25-only. With either partial group, assert `ApplicationBootstrapError` at the matching stage. Assert shutdown clears both Registries and credentials.

- [ ] **Step 5: Wire optional static resources and dynamic model services**

Build the model runtime service/registry independently of static model settings. Only construct static model routing when the optional LLM group exists. Only construct static Embedding when its group exists. Permit `ApplicationServices(contexts={}, model_routing=None)` when a model runtime registry exists; keep `context` property behavior unchanged for old callers. Pass the model Registry to `ModelProfileService` and Resolver. Cleanup order: model Registry, datasource Registry, static connector registry, credential store.

- [ ] **Step 6: Run Task 6 tests and commit**

Run: `pytest tests/unit/test_llm_config.py tests/unit/test_config.py tests/unit/test_bootstrap_lifecycle.py tests/unit/test_api_application.py -q`

Expected: PASS.

Commit:

```bash
git add app/config/model.py app/config/embedding.py app/config/__init__.py app/api/bootstrap.py tests/unit/test_llm_config.py tests/unit/test_config.py tests/unit/test_bootstrap_lifecycle.py tests/unit/test_api_application.py
git commit -m "feat: allow profile-only application startup"
```

---

### Task 7: Add the save-before-test model API

**Files:**
- Modify: `app/api/profile_models.py`
- Modify: `app/api/routes/models.py`
- Modify: `app/api/bootstrap.py`
- Test: `tests/unit/test_profile_routes.py`
- Test: `tests/security/test_profile_credentials.py`

**Interfaces:**
- Consumes: `ModelRuntimeService.test_connection` and existing Profile error response mapping.
- Produces: `POST /api/v1/local/models/test`; `ModelConnectionTestRequest`; `ModelConnectionTestResponse`.

- [ ] **Step 1: Write failing route contract tests**

Test a request without `id`/`name`, no API Key, and no Embedding. Assert HTTP 200:

```json
{
  "generation": "connected",
  "embedding": "not_configured",
  "embedding_error": null
}
```

Assert Profile list stays empty and the temporary request is not present in the credential store or model Registry. Add configured Embedding success and unavailable cases, plus generation 422/503/504 stable errors.

- [ ] **Step 2: Run route tests and verify RED**

Run: `pytest tests/unit/test_profile_routes.py -q`

Expected: FAIL with 404 for the missing route.

- [ ] **Step 3: Define strict write-only request and response models**

The request includes `provider_type`, `base_url`, `model_name`, optional generation Key, and the three optional Embedding public fields plus optional Embedding Key. Reuse the same endpoint and Secret validators as Profile create without requiring or fabricating persisted IDs. Response contains only enum statuses and an optional stable `{code, message}` object.

- [ ] **Step 4: Add the route before `/{profile_id}` matching**

Call the runtime service directly with a transient validated Profile whose internal fixed ID/name are never returned or persisted. Map only `ModelRuntimeError` through `ProfileErrorResponse`; unexpected errors use the existing fixed log event with no exception text.

- [ ] **Step 5: Extend OpenAPI and credential leakage assertions**

Assert `/api/v1/local/models/test` exists, both Key fields are `writeOnly`, response schemas contain neither Key nor endpoint, and sentinel values do not appear in response, OpenAPI, caplog, SQLite artifacts, or exception text.

- [ ] **Step 6: Run Task 7 tests and commit**

Run: `pytest tests/unit/test_profile_routes.py tests/security/test_profile_credentials.py -q`

Expected: PASS.

Commit:

```bash
git add app/api/profile_models.py app/api/routes/models.py app/api/bootstrap.py tests/unit/test_profile_routes.py tests/security/test_profile_credentials.py
git commit -m "feat: add local model connection test"
```

---

### Task 8: Verify dynamic Profile queries, offline mode, and documentation

**Files:**
- Modify: `tests/integration/test_openai_compatible_provider.py`
- Modify: `tests/integration/test_openai_compatible_embedding_provider.py`
- Modify: `tests/integration/test_api_pagila.py`
- Modify: `tests/integration/test_api_mysql_sakila.py`
- Modify: `docs/current-architecture.md`
- Modify: `README.md`

**Interfaces:**
- Consumes: the completed runtime/API behavior from Tasks 1–7.
- Produces: real loopback contract evidence, Profile-ID E2E coverage, and accurate phase-4 status documentation.

- [ ] **Step 1: Add a real loopback no-auth generation contract test**

Run an in-process HTTP server, assert no Authorization Header is received, return the fixed OpenAI-compatible structured response, and verify all three dynamic routes select the same model configuration.

- [ ] **Step 2: Add BM25-only and Embedding degradation integration tests**

Build a Profile-only application with deterministic datasource/model fixtures. Assert absent Embedding completes Schema Linking with `retrieval_runtime is None`; an approved loopback Embedding timeout produces `bm25_only` degradation without changing allowed tables or Schema version.

- [ ] **Step 3: Add Profile-ID API E2E cases**

For Pagila/PostgreSQL and configured Sakila/MySQL environments, create ModelProfile and DatasourceProfile through services, submit only `question`, `datasource_id`, and `model_profile_id`, and assert the selected dynamic provider is used. Preserve the existing environment markers and do not turn unavailable real services into new unconditional skips.

- [ ] **Step 4: Run focused integration and security suites**

Run:

```bash
pytest tests/integration/test_openai_compatible_provider.py tests/integration/test_openai_compatible_embedding_provider.py tests/integration/test_api_pagila.py -q
pytest tests/security -q
```

Expected: PASS; optional MySQL real-environment tests retain their existing configured behavior.

- [ ] **Step 5: Run complete project verification**

Run:

```bash
python -m compileall -q app tests
python -m pytest tests/unit tests/security -q --cov=app --cov-branch --cov-report=term-missing
python -m pytest tests/integration -q
python -m pip check
npm test -- --run
npm run build
git diff --check
```

Run the npm commands from `frontend/`. Require unit+security branch coverage at or above 83%. Record any environment-gated real database test separately; do not claim it passed without output.

- [ ] **Step 6: Update architecture and README status**

Document the phase-4 Profile query chain, runtime ownership, optional static groups, BM25-only behavior, model-test endpoint, stable errors, and the exact verification evidence. Keep frontend completion explicitly assigned to phase 5.

- [ ] **Step 7: Commit final integration/docs changes and push main**

```bash
git add tests/integration/test_openai_compatible_provider.py tests/integration/test_openai_compatible_embedding_provider.py tests/integration/test_api_pagila.py tests/integration/test_api_mysql_sakila.py docs/current-architecture.md README.md
git commit -m "test: verify local model phase 4"
git push origin main
```

Expected: push succeeds to `https://github.com/lingyunjie321/text-to-sql-lite.git`; `docs/Text-to-SQL原项目参考信息.md` is not staged or pushed.
