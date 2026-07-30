# Enhancement Stage 1 Retrieval and Routing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver an authorization-safe, versioned retrieval and routing pipeline with an explicit `ComplexityRouteNode`, dynamic 5/10/20 Schema Top-K, hybrid BM25/Embedding retrieval, RRF, explainable reranking, context pruning, and server-controlled multi-model routing.

**Architecture:** A probe `SchemaLinkingNode` builds an authorized candidate pool capped at 20, the explicit `ComplexityRouteNode` makes a deterministic versioned decision from question and candidate evidence, and a second invocation of the same Linking node materializes 5/10/20 final candidates from the same snapshot. Later tasks enrich the same boundary with Embedding, RRF, deterministic reranking, context selection, and model routing; existing Validator and execution services remain the only SQL safety and execution boundaries.

**Tech Stack:** Python 3.12, Pydantic 2, LangGraph 1.2.9, standard-library `urllib`, existing psycopg/SQLGlot/FastAPI modules, pytest 9.1.1.

## Global Constraints

- Work only on `main`; do not create a branch, worktree, or pull request.
- The user explicitly authorized implementation on `main`.
- Preserve the user's existing edit to `docs/Text-to-SQL项目复现规格.md`.
- Do not read `docs/Text-to-SQL原项目参考信息.md` as a requirement and never include it in a commit.
- Do not add a production dependency during Stage 1.
- Do not rewrite the PostgreSQL Connector, SQLGlot Validator, validated execution service, attempt/reflection system, API response contract, or evaluation Comparator.
- Every production behavior starts with a failing test, is observed failing for the intended reason, receives the minimum implementation, and is rerun green.
- Client requests never accept complexity, Top-K, model, embedding, or context-budget controls.
- Authorization filtering occurs before BM25 statistics, Embedding documents, rank fusion, reranking, context selection, and Prompt construction.
- Probe and materialization use the same authorized `SchemaSnapshot` and `schema_version`.
- All generated and repaired SQL continues through current authorization, AST, function, read-only, and execution boundaries.
- Pagila Gold question is allowed only as the current E2E user payload. Gold SQL, tables, fields, joins, results, labels, fixtures, and failure reasons never enter Prompt examples, retrieval/index inputs, training, or tuning.
- Stage 10 historical reports and Stage 4/8 historical design documents remain unchanged.
- Do not commit or push Stage 1 as complete unless its applicable functional, integration, security, and real-environment gates have passed. If real services are unavailable, record `real_environment_validated=false` and do not claim Stage 1 completion.

## Current Qualification Snapshot

- `embedding_provider.real_environment_validated=true`: after deterministic
  Provider tests, exactly one approved Alibaba Cloud Bailian Beijing
  OpenAI-compatible request succeeded for `text-embedding-v4` and returned one
  fully validated 1024-dimensional vector.
- `stage1.real_environment_validated=false`: the Provider smoke does not prove
  the authorized index, hybrid retrieval, two real generation-model routes,
  a new Pagila baseline, or the 18-case Gold qualification.
- No API key, raw endpoint, request document, response body, or vector value is
  stored in this plan or the qualification report.
- Checked implementation steps below are component evidence only. Task 11
  calibration freeze and all applicable Task 12 gates remain authoritative
  for the whole-stage status.

---

## File Map

| File | Responsibility |
|---|---|
| `app/workflow/complexity.py` | Pure `complexity-v1` evidence extraction and decision |
| `app/workflow/models.py` | Strict complexity and routing state |
| `app/workflow/nodes.py` | Probe, explicit route node, materialization, model/context consumption |
| `app/workflow/graph.py` | Ten node types and conditional probe/route/materialize edges |
| `app/schema_linking/models.py` | Closed Top-K type and retrieval evidence models |
| `app/schema_linking/authorization.py` | Shared authorization-first snapshot projection |
| `app/schema_linking/linker.py` | Existing authorized BM25/FK behavior parameterized by internal Top-K |
| `app/schema_linking/embedding.py` | OpenAI-compatible Embedding protocol and provider |
| `app/schema_linking/index.py` | Authorized documents, retrieval version, bounded immutable vector indexes |
| `app/schema_linking/fusion.py` | RRF formula and stable fused candidates |
| `app/schema_linking/rerank.py` | Explainable deterministic set-level reranking |
| `app/generation/context.py` | Required-field preservation and conservative input-budget selection |
| `app/generation/routing.py` | Server-owned model route table and bounded fallback decisions |
| `app/http_transport.py` | Shared bounded no-redirect HTTP transport |
| `app/config.py` | Strict Embedding and base/route/fallback model settings |
| `app/observability/models.py` | Safe routing/retrieval/context Trace models |
| `app/observability/tracing.py` | Mapping terminal State into safe Trace evidence |
| `evaluation/` | Stage 1 metrics, frozen non-Gold inputs, and new baseline evidence |
| `tests/unit/` | Pure behavior tests |
| `tests/security/` | Authorization, Gold, secret, and bypass tests |
| `tests/integration/` | Workflow, HTTP protocol, and real-database contracts |

### Task 1: Implement the pure `complexity-v1` decision

**Files:**
- Create: `app/workflow/complexity.py`
- Modify: `app/workflow/models.py`
- Modify: `app/workflow/__init__.py`
- Create: `tests/unit/test_complexity_routing.py`
- Modify: `tests/unit/test_workflow_models.py`

**Interfaces:**
- Consumes: normalized question, probe `CandidateTable` values, probe `JoinPath` values, and derived `has_repair_history`.
- Produces: `QueryComplexity`, `ComplexityReason`, `ComplexityDecision`, and `decide_complexity(...)`.

- [x] **Step 1: Write failing closed-model and mapping tests**

```python
def test_default_question_routes_to_simple_five() -> None:
    decision = decide_complexity(
        "list film titles",
        candidate_tables=(_candidate("public.film", score=4.0),),
        join_paths=(),
        has_repair_history=False,
    )

    assert decision == ComplexityDecision(
        level=QueryComplexity.SIMPLE,
        schema_top_k=5,
        reason_codes=(ComplexityReason.DEFAULT_SIMPLE,),
    )


def test_aggregation_and_time_route_to_complex_twenty() -> None:
    decision = decide_complexity(
        "monthly average payment amount",
        candidate_tables=(_candidate("public.payment", score=3.0),),
        join_paths=(),
        has_repair_history=False,
    )

    assert decision.level is QueryComplexity.COMPLEX
    assert decision.schema_top_k == 20
    assert decision.reason_codes == (
        ComplexityReason.AGGREGATION_REQUESTED,
        ComplexityReason.TIME_ANALYSIS_REQUESTED,
    )
```

Also cover window/ranking, anti-join/subquery, two positive candidates with a
relevant one-edge path, a two-edge relevant path, repair history, unrelated
fallback paths, duplicate phrases, NFKC/casefold, and invalid model
combinations. The repair-history case passes `has_repair_history=True`
independently of the numeric repair counter.

- [x] **Step 2: Run the tests and verify RED**

Run:

```bash
./.venv/bin/pytest -q tests/unit/test_complexity_routing.py tests/unit/test_workflow_models.py
```

Expected: collection fails because the complexity types and function do not
exist. Fix only test import mistakes until the failure is the missing
production behavior.

- [x] **Step 3: Implement strict models and the pure decision**

```python
class QueryComplexity(str, Enum):
    SIMPLE = "simple"
    MEDIUM = "medium"
    COMPLEX = "complex"


class ComplexityDecision(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
    )

    level: QueryComplexity
    schema_top_k: Literal[5, 10, 20]
    reason_codes: tuple[ComplexityReason, ...]
    policy_version: Literal["complexity-v1"] = "complexity-v1"
```

Before-field validators reject coerced enum strings, lists, bools and
float-valued Top-K inputs. The after validator enforces the exact
reason-to-level mapping, non-empty unique reasons, declared-enum ordering,
and exclusive `default_simple`. Implement exact reason extraction and
precedence from the design. Relevant JOIN evidence must connect at least two
positive-score candidates.

- [x] **Step 4: Run focused tests and verify GREEN**

Run the Step 2 command. Expected: all selected tests pass with no warnings.

- [ ] **Step 5: Run mutation checks**

Temporarily verify that changing `MEDIUM` from 10 to 20, treating any fallback
JOIN as relevant, or returning unsorted reasons fails at least one test.
Restore production code and rerun Step 2 green.

### Task 2: Parameterize authorized Schema Linking with 5/10/20

**Files:**
- Modify: `app/schema_linking/models.py`
- Modify: `app/schema_linking/linker.py`
- Modify: `app/schema_linking/__init__.py`
- Modify: `app/generation/prompt.py`
- Modify: every direct `SchemaLinkingResult(...)` construction in tests
- Modify: every direct `link_schema(...)` call in tests/integration code
- Modify: `tests/unit/test_schema_linking_models.py`
- Modify: `tests/unit/test_schema_linker_top_k.py`
- Modify: `tests/unit/test_schema_linker_join_paths.py`
- Modify: `tests/unit/test_generation_prompt.py`
- Modify: `tests/security/test_schema_linker_permissions.py`

**Interfaces:**
- Consumes: trusted internal `top_k: Literal[5, 10, 20]`.
- Produces: `SchemaLinkingResult.top_k` and candidates bounded by that value.

- [x] **Step 1: Replace fixed-constant tests with behavior tests**

```python
@pytest.mark.parametrize("top_k", (5, 10, 20))
def test_candidate_count_and_fk_bridges_stay_within_budget(
    top_k: SchemaTopK,
) -> None:
    result = link_schema(
        "priority tables",
        allowed_schemas=("public",),
        allowed_tables=_allowed_tables(24),
        snapshot=_snapshot(24),
        top_k=top_k,
    )

    assert 0 < len(result.candidate_tables) <= top_k
    assert result.top_k == top_k
    assert {
        table.object_id for table in result.candidate_tables
    }.issubset(set(_allowed_tables(24)))


@pytest.mark.parametrize("invalid", (True, 0, 6, 21, "20"))
def test_linker_rejects_non_closed_internal_budget(invalid: object) -> None:
    with pytest.raises(ValueError, match="schema linking context is invalid"):
        link_schema(
            "film",
            allowed_schemas=("public",),
            allowed_tables=("public.film",),
            snapshot=_snapshot(1),
            top_k=invalid,  # type: ignore[arg-type]
        )
```

Update Prompt tests to prove 20 candidates are valid when `result.top_k=20`
and 6 candidates are invalid when `result.top_k=5`.

- [x] **Step 2: Run linker, Prompt, and security tests and verify RED**

Run:

```bash
./.venv/bin/pytest -q \
  tests/unit/test_schema_linking_models.py \
  tests/unit/test_schema_linker_top_k.py \
  tests/unit/test_schema_linker_join_paths.py \
  tests/unit/test_generation_prompt.py \
  tests/security/test_schema_linker_permissions.py
```

Expected: failures show that `link_schema` has no `top_k` parameter,
`SchemaLinkingResult` has no `top_k`, and Prompt still uses `TOP_K=10`.

- [x] **Step 3: Implement the minimum dynamic-budget behavior**

```python
SchemaTopK: TypeAlias = Literal[5, 10, 20]
SUPPORTED_SCHEMA_TOP_KS: tuple[SchemaTopK, ...] = (5, 10, 20)
PROBE_SCHEMA_TOP_K: SchemaTopK = 20


def validate_schema_top_k(value: object) -> SchemaTopK:
    if type(value) is not int or value not in SUPPORTED_SCHEMA_TOP_KS:
        raise ValueError("schema linking context is invalid")
    return cast(SchemaTopK, value)
```

Pass the validated local value into `_select_table_ids(...)`, fallback
slicing, FK bridge accounting, and termination. Remove the production
`TOP_K` import. Add required `top_k` to `SchemaLinkingResult` and validate
Prompt candidate count against the result value.

- [x] **Step 4: Update direct callers explicitly**

Every helper chooses 5, 10, or 20 based on what it tests. Retrieval-quality
integration tests use 20; MVP compatibility tests use 10. Do not introduce a
default that hides missing routing decisions.

- [x] **Step 5: Run focused tests and verify GREEN**

Run Step 2 plus:

```bash
./.venv/bin/pytest -q tests/unit/test_schema_linker_*.py tests/security/test_schema_linker_permissions.py
```

Expected: all selected tests pass and each budget path is exercised.

### Task 3: Add the explicit node and two-pass Linking

**Files:**
- Modify: `app/workflow/models.py`
- Modify: `app/workflow/nodes.py`
- Modify: `app/workflow/graph.py`
- Modify: `app/workflow/__init__.py`
- Modify: `tests/unit/test_workflow_graph.py`
- Modify: `tests/security/test_workflow_routing.py`
- Modify: `tests/integration/test_reflection_repair_pipeline.py`

**Interfaces:**
- Consumes: Tasks 1–2 `ComplexityDecision`, `decide_complexity`, and dynamic `link_schema`.
- Produces: ten node types; probe → route → materialize with one metadata read.

- [x] **Step 1: Write the failing graph and end-to-end state tests**

```python
def test_graph_registers_ten_nodes_and_two_pass_linking_edges() -> None:
    graph = build_workflow().get_graph()
    business_nodes = set(graph.nodes) - {"__start__", "__end__"}

    assert business_nodes == set(WORKFLOW_NODE_NAMES)
    assert "complexity_route" in business_nodes
    assert _has_edge(graph, "schema_linking", "complexity_route")
    assert _has_edge(graph, "complexity_route", "schema_linking")
    assert _has_edge(graph, "schema_linking", "generate_sql")


def test_first_pass_uses_one_snapshot_and_materializes_selected_budget() -> None:
    result = run_workflow(_state("list film titles"), context=context)

    assert connector.metadata_calls == [
        (("public",), EXPECTED_ALLOWED_TABLES)
    ]
    assert result.complexity_decision is not None
    assert result.complexity_decision.schema_top_k == 5
    assert observed_top_ks == (20, 5)
    assert observed_snapshots[0] is observed_snapshots[1]
    assert observed_candidate_counts == (20, 5)
    assert tuple(t.node for t in result.node_timings[:5]) == (
        "request_preprocess",
        "permission_resolve",
        "schema_linking",
        "complexity_route",
        "schema_linking",
    )
```

Add a Schema repair test proving the decision is cleared, metadata is read
again, and the three-step retrieval cycle repeats. Its first relink occurs
while the existing `repair_count` is still zero and must nevertheless include
`repair_history`. Add syntax repair proof that the decision is retained and
metadata is not reread. Use a wide authorized fixture so the first-pass test
proves actual 20 → 5 rematerialization rather than only checking a one-table
result. Add fail-closed tests for a materialized result whose `top_k` or
`schema_version` disagrees with the decision and probe snapshot.

- [x] **Step 2: Run Workflow tests and verify RED**

Run:

```bash
./.venv/bin/pytest -q \
  tests/unit/test_workflow_graph.py \
  tests/security/test_workflow_routing.py \
  tests/integration/test_reflection_repair_pipeline.py
```

Expected: graph/state assertions fail because only nine nodes and one Linking
pass exist.

- [x] **Step 3: Add state and node behavior**

Add `complexity_decision: ComplexityDecision | None` to `SQLTaskState`.
Implement:

```python
def _complexity_route(
    state: SQLTaskState,
    context: WorkflowContext,
) -> NodeUpdate:
    del context
    assert state.normalized_question is not None
    return {
        "complexity_decision": decide_complexity(
            state.normalized_question,
            candidate_tables=state.candidate_tables,
            join_paths=state.join_paths,
            has_repair_history=(
                (
                    bool(state.sql_attempts)
                    and state.repair_strategy is not None
                )
                or state.repair_count > 0
            ),
        ),
    }
```

The node must not clear `error_type` or `repair_strategy`. During the first
Schema repair, `repair_count` is still zero and Generate needs the retained
`SCHEMA_ERROR` plus `RELINK_SCHEMA` to construct the repair context. Those
fields remain owned by the existing Generate acceptance boundary.

The first `_schema_linking` call reads metadata and passes
`PROBE_SCHEMA_TOP_K`. The second call detects a decision, reuses
`state.schema_snapshot`, and passes `decision.schema_top_k`.

- [x] **Step 4: Add exact conditional edges**

`_schema_route` returns `complexity_route` when no decision exists and
`generate_sql` when final candidates match the decision. Register
`COMPLEXITY_ROUTE_NODE`. Complexity success returns `schema_linking`; wrapper
failure returns `finalize`.

When reflection chooses `RELINK_SCHEMA`, its update sets
`complexity_decision=None`; other repair strategies keep the decision.

- [x] **Step 5: Recalculate the 32-step proof**

Use four distinct, valid SQL attempts whose executions each return
`SCHEMA_ERROR`. Assert exact termination as `FAILED_REPAIR_EXHAUSTED` at
`step_count == 31`, with eight Linking invocations, four Complexity
invocations, four metadata reads, and four execution attempts. Do not
increase `MAX_WORKFLOW_STEPS` or recursion limit.

- [x] **Step 6: Run focused Workflow tests and verify GREEN**

Run Step 2. Expected: all selected tests pass with the new exact node order,
one metadata read per retrieval cycle, and no authorization/safety regression.

### Task 4: Add safe complexity and dynamic-K Trace evidence

**Files:**
- Modify: `app/observability/models.py`
- Modify: `app/observability/tracing.py`
- Modify: `app/observability/__init__.py`
- Modify: `tests/unit/test_observability_trace.py`
- Modify: `tests/security/test_observability_security.py`

**Interfaces:**
- Consumes: terminal `SQLTaskState.complexity_decision`.
- Produces: optional safe `TraceComplexity`.

- [x] **Step 1: Write failing positive and negative Trace tests**

```python
def test_trace_records_versioned_complexity_evidence() -> None:
    record = build_trace_record(_terminal_state_with_complexity())

    assert record.complexity is not None
    assert record.complexity.level is QueryComplexity.MEDIUM
    assert record.complexity.schema_top_k == 10
    assert record.complexity.policy_version == "complexity-v1"
    assert record.complexity.reason_codes == (
        ComplexityReason.AGGREGATION_REQUESTED,
    )


def test_complexity_trace_contains_no_input_or_object_names() -> None:
    rendered = build_trace_record(_terminal_state_with_complexity()).model_dump_json()

    for forbidden in ("private-question", "public.film", "SELECT", "rows"):
        assert forbidden.casefold() not in rendered.casefold()
```

- [x] **Step 2: Run Trace tests and verify RED**

Run:

```bash
./.venv/bin/pytest -q \
  tests/unit/test_observability_trace.py \
  tests/security/test_observability_security.py
```

Expected: `TraceRecord` has no complexity field.

- [x] **Step 3: Implement the minimal safe mapping**

Add frozen `TraceComplexity` with only level, Top-K, reasons, and policy
version. Map it from state. Do not add question, table IDs, or candidate
documents.

- [x] **Step 4: Run Task 1–4 regression**

```bash
./.venv/bin/pytest -q \
  tests/unit/test_complexity_routing.py \
  tests/unit/test_schema_linking_models.py \
  tests/unit/test_schema_linker_*.py \
  tests/unit/test_generation_prompt.py \
  tests/unit/test_workflow_models.py \
  tests/unit/test_workflow_graph.py \
  tests/unit/test_observability_trace.py \
  tests/security/test_schema_linker_permissions.py \
  tests/security/test_workflow_routing.py \
  tests/security/test_observability_security.py
```

Expected: all selected tests pass. This is the first complete vertical slice.

### Task 5: Implement the real OpenAI-compatible Embedding provider

**Files:**
- Modify: `app/config.py`
- Create: `app/schema_linking/embedding.py`
- Modify: `app/schema_linking/__init__.py`
- Create: `tests/unit/test_embedding_provider.py`
- Create: `tests/integration/test_openai_compatible_embedding_provider.py`
- Create: `tests/security/test_embedding_provider_security.py`

**Interfaces:**
- Produces: `EmbeddingProvider`, `EmbeddingProviderError`, `EmbeddingSettings`, and `OpenAICompatibleEmbeddingProvider.embed(...)`.

- [x] **Step 1: Write failing request/response contract tests**

```python
def test_embedding_provider_preserves_input_order() -> None:
    provider = OpenAICompatibleEmbeddingProvider(
        _settings(dimension=3),
        transport=_transport(
            {
                "model": "embedding-v1",
                "data": [
                    {"index": 1, "embedding": [0.0, 1.0, 0.0]},
                    {"index": 0, "embedding": [1.0, 0.0, 0.0]},
                ],
            }
        ),
    )

    assert provider.embed(("film", "actor")) == (
        (1.0, 0.0, 0.0),
        (0.0, 1.0, 0.0),
    )
```

Cover count mismatch, duplicate/missing index, bool/non-number, NaN/Inf,
dimension mismatch, zero norm, oversized response, redirects, timeout,
connection, HTTP error, malformed JSON, empty document, batch >64, and HTTPS/
loopback validation.

- [x] **Step 2: Run tests and verify RED**

```bash
./.venv/bin/pytest -q \
  tests/unit/test_embedding_provider.py \
  tests/security/test_embedding_provider_security.py
```

Expected: imports fail because the provider does not exist.

- [x] **Step 3: Implement settings and provider**

Use `/embeddings`, Bearer auth, `model`, and ordered `input`. Reuse or
surgically extract the existing no-redirect bounded `urllib` transport
without changing generation behavior. Public errors are fixed and contain no
document, endpoint credential, or response body.

- [x] **Step 4: Run local HTTP integration**

```bash
./.venv/bin/pytest -q tests/integration/test_openai_compatible_embedding_provider.py -m integration
```

Expected: real loopback HTTP request and redirect rejection pass.

**Execution evidence (2026-07-29)**

- RED: the focused provider/security suite failed in 68 cases because the
  Embedding settings and provider did not exist.
- GREEN: the deterministic provider/security suite passed in 74 cases; the
  real loopback `/embeddings` request and redirect-rejection tests both
  passed. Existing LLM provider tests also passed after the HTTP transport
  was extracted to a neutral module.
- The approved Alibaba Cloud Bailian OpenAI-compatible service returned one
  valid vector for `text-embedding-v4`; the configured and validated
  dimension was `1024`. The response passed model, count/index, dimension,
  finite-value, and nonzero-norm validation.
- No endpoint value, API key, input document, raw response, or vector value
  was written to this evidence.
- Embedding Provider capability:
  `real_environment_validated=true`.
- Whole Stage 1: `real_environment_validated=false`. This smoke test does not
  validate the authorized index, hybrid retrieval, RRF, reranking, context
  selection, multi-model routing, Pagila baseline, or Gold E2E gates in
  Task 12.

### Task 6: Build authorized versioned documents and a bounded vector index

**Files:**
- Create: `app/schema_linking/index.py`
- Modify: `app/schema_linking/models.py`
- Create: `tests/unit/test_schema_embedding_index.py`
- Create: `tests/security/test_schema_embedding_index_security.py`

**Interfaces:**
- Consumes: authorized `SchemaSnapshot`, datasource ID, authorization scope, semantic version, and `EmbeddingProvider`.
- Produces: immutable `RetrievalVersion`, `EmbeddingIndex`, and `EmbeddingIndexRegistry`.

- [x] **Step 1: Write failing document/version/security tests**

Assert exact deterministic documents from a hand-built snapshot, then assert:

- changing an authorized comment changes version;
- changing only an unauthorized object does not;
- changing model, dimension, semantic version, document version, fusion, or
  rerank version changes version;
- no Gold/evaluation input parameter exists;
- concurrent first build publishes one complete index;
- a failed build publishes no entry;
- the 33rd version evicts exactly the least recently used entry.

- [x] **Step 2: Verify RED**

```bash
./.venv/bin/pytest -q \
  tests/unit/test_schema_embedding_index.py \
  tests/security/test_schema_embedding_index_security.py
```

- [x] **Step 3: Implement `schema-doc-v1` and version hashing**

Serialize stable UTF-8 JSON with sorted keys and length-delimited version
components. Build documents only after the same authorization filtering used
by the BM25 linker.

- [x] **Step 4: Implement atomic bounded registry**

Use an in-process lock per version, publish only after the whole batch
validates, retain 32 immutable indexes, and make LRU eviction observable by
version ID only.

- [x] **Step 5: Run tests and verify GREEN**

Run Step 2; expected all pass.

### Task 7: Add dual retrieval and RRF

**Files:**
- Create: `app/schema_linking/fusion.py`
- Modify: `app/schema_linking/linker.py`
- Modify: `app/schema_linking/models.py`
- Create: `tests/unit/test_schema_hybrid_retrieval.py`
- Create: `tests/unit/test_rrf_fusion.py`
- Create: `tests/security/test_hybrid_retrieval_permissions.py`

**Interfaces:**
- Consumes: authorized BM25 ranks and same-version cosine ranks.
- Produces: fused candidates with rank provenance and `rrf-v1`.

- [x] **Step 1: Write failing hand-derived RRF tests**

```python
def test_rrf_uses_rank_not_raw_channel_scores() -> None:
    result = reciprocal_rank_fusion(
        {
            "bm25": (
                "public.film",
                "public.actor",
                "public.payment",
            ),
            "embedding": (
                "public.actor",
                "public.payment",
                "public.film",
            ),
        },
        k=60,
    )

    assert result[0].object_id == "public.actor"
    assert result[0].contributions == {
        "bm25": pytest.approx(1 / 62),
        "embedding": pytest.approx(1 / 61),
    }
```

Choose literals whose totals do not tie; separately test exact ties use object
ID. Cover duplicates, missing channels, empty ranks, rank starting at one,
and invalid `k`.

- [x] **Step 2: Verify RED**

```bash
./.venv/bin/pytest -q \
  tests/unit/test_rrf_fusion.py \
  tests/unit/test_schema_hybrid_retrieval.py \
  tests/security/test_hybrid_retrieval_permissions.py
```

- [x] **Step 3: Implement RRF `k=60` and cosine ranking**

Never mix raw BM25 and cosine scores. Both channels cap their ranked pool at
20 and use canonical object ID tie-breaks.

- [x] **Step 4: Add same-version BM25-only degradation**

Injected Embedding timeout/connection/invalid response yields BM25-only with
an explicit degradation observation. Retrieval-version mismatch does not
degrade to an old vector index.

- [x] **Step 5: Run tests and verify GREEN**

Run Step 2 and existing linker authorization/version tests.

### Task 8: Add explainable deterministic reranking

**Files:**
- Create: `app/schema_linking/rerank.py`
- Modify: `app/schema_linking/models.py`
- Modify: `app/schema_linking/linker.py`
- Create: `tests/unit/test_schema_rerank.py`
- Create: `tests/security/test_schema_rerank_security.py`

**Interfaces:**
- Consumes: fused authorized candidates, matched fields, aliases, and authorized FK graph.
- Produces: stable reranked candidates and closed reason codes.

- [x] **Step 1: Write failing set-level behavior tests**

Use literal fixtures proving:

- a required bridge survives although it has no lexical/vector match;
- more directly matched fields outrank fewer fields;
- approved aliases affect only their authorized object;
- shorter relevant paths win;
- disconnected zero-evidence candidates are penalized;
- exact evidence ties use canonical object ID;
- reranker cannot add an object absent from fusion input.

- [x] **Step 2: Verify RED**

```bash
./.venv/bin/pytest -q \
  tests/unit/test_schema_rerank.py \
  tests/security/test_schema_rerank_security.py
```

- [x] **Step 3: Implement lexicographic feature ordering**

Implement the exact ordered features from the design. Do not add tunable
weights or an LLM call. Save only closed reasons and numeric rank evidence.

- [x] **Step 4: Implement RRF fallback on internal rerank error**

The injected-error integration path returns stable RRF ordering, never a
partially reranked set, and records `rerank_degraded`.

- [x] **Step 5: Run tests and verify GREEN**

Run Step 2 plus hybrid and existing FK tests.

### Task 9: Implement context selection and conservative budgeting

**Files:**
- Create: `app/generation/context.py`
- Modify: `app/generation/models.py`
- Modify: `app/generation/prompt.py`
- Modify: `app/workflow/models.py`
- Modify: `app/workflow/nodes.py`
- Create: `tests/unit/test_generation_context_selection.py`
- Modify: `tests/unit/test_generation_prompt.py`
- Modify: `tests/security/test_generation_prompt_security.py`

**Interfaces:**
- Consumes: final reranked candidates, snapshot, decision, and model input/output limits.
- Produces: selected fields and `ContextSelectionObservation`.

- [x] **Step 1: Write failing field-priority and budget tests**

```python
def test_context_keeps_join_keys_before_unmatched_fields() -> None:
    selection = select_generation_context(
        linking=_linking_with_many_fields(),
        snapshot=_snapshot(),
        max_input_tokens=400,
        max_output_tokens=100,
    )

    assert "public.film_actor.film_id" in selection.field_ids
    assert "public.film_actor.actor_id" in selection.field_ids
    assert selection.estimated_tokens <= selection.usable_input_tokens
```

Cover direct matches, PK/FK, filter/aggregation/time evidence, deterministic
remaining order, UTF-8 estimate `ceil(bytes/3)`, 80% input budget, and
required-evidence overflow.

- [x] **Step 2: Verify RED**

```bash
./.venv/bin/pytest -q \
  tests/unit/test_generation_context_selection.py \
  tests/unit/test_generation_prompt.py \
  tests/security/test_generation_prompt_security.py
```

- [x] **Step 3: Implement minimal selector and Prompt consumption**

The selector returns an immutable view; Validator continues receiving the
full authorized snapshot. Required evidence overflow produces the existing
resource/clarification path before any Provider call.

- [x] **Step 4: Add safe observation**

Record counts and token estimates only, not question, field names, Prompt, or
schema text.

- [x] **Step 5: Run tests and verify GREEN**

Run Step 2 and Workflow routing security tests.

### Task 10: Implement server-controlled multi-model routing

**Files:**
- Modify: `app/config.py`
- Modify: `app/generation/models.py`
- Modify: `app/generation/provider.py`
- Create: `app/generation/routing.py`
- Modify: `app/workflow/models.py`
- Modify: `app/workflow/nodes.py`
- Modify: `app/api/bootstrap.py`
- Modify: `app/observability/models.py`
- Modify: `app/observability/tracing.py`
- Create: `tests/unit/test_model_routing.py`
- Create: `tests/security/test_model_routing_security.py`
- Create: `tests/integration/test_multi_model_workflow.py`

**Interfaces:**
- Consumes: `ComplexityDecision` and server-owned route table.
- Produces: selected Provider route, context limits, and at most one same-boundary fallback.

- [x] **Step 1: Write failing route and fallback tests**

Assert simple/medium/complex choose `simple_route`, `standard_route`, and
`complex_route`. Prove a request with extra `model`, `complexity`, or `top_k`
is rejected by current `extra="forbid"` API model.

Fallback tests cover:

- timeout/connection/capacity invokes the declared fallback once;
- HTTP 429 maps to `LLM_RATE_LIMITED`, and 502/503/504 map to
  `LLM_CAPACITY_ERROR`;
- different data-boundary ID refuses fallback;
- every other HTTP status, malformed/invalid output, and unknown error refuses
  fallback;
- invalid output, safety rejection, permission rejection, and SQL validation
  failure never invoke fallback;
- fallback does not increment `repair_count`.

- [x] **Step 2: Verify RED**

```bash
./.venv/bin/pytest -q \
  tests/unit/test_model_routing.py \
  tests/security/test_model_routing_security.py \
  tests/integration/test_multi_model_workflow.py
```

- [x] **Step 3: Implement strict route settings and registry**

Use a frozen route table with `version="model-routes-v1"`, provider key,
model-config hash, input/output limits, timeout, data-boundary ID, and
optional fallback key. Bootstrap constructs all declared Providers and fails
startup on unknown keys or incompatible fallback.

Extend the existing Provider's closed public errors without exposing response
bodies: timeout, connection, HTTP 429, and HTTP 502/503/504 are the only
fallback-eligible infrastructure failures. Preserve all existing output
normalization and secret/redirect/response-size behavior.

- [x] **Step 4: Integrate selection and fallback**

`GenerateSQLNode` selects route before context pruning, calls the chosen
Provider, and handles only the predeclared infrastructure failures. Preserve
the existing Provider output normalization and SQL safety path.

- [x] **Step 5: Add safe Trace and run GREEN**

Trace stores route ID, hashed actual model configuration, fallback boolean,
route-table version, and hashed data-boundary ID. Run Step 2 and existing API/
generation/Workflow tests.

### Task 11: Extend evaluation, non-Gold gates, and Gold pollution proofs

**Files:**
- Create: `evaluation/cases/retrieval_routing_development.jsonl`
- Create: `evaluation/cases/retrieval_routing_calibration.jsonl`
- Modify: `evaluation/__init__.py`
- Modify: `evaluation/loader.py`
- Modify: `evaluation/models.py`
- Modify: `evaluation/runner.py`
- Modify: `evaluation/report.py`
- Modify: `evaluation/code_freeze.py`
- Create: `evaluation/stage1_selected_configuration.json`
- Create: `evaluation/stage1_calibration_freeze.json`
- Create: `tests/unit/test_retrieval_routing_loader.py`
- Create: `tests/unit/test_retrieval_stage_timings.py`
- Create: `tests/unit/test_stage1_evaluation_freeze.py`
- Create: `tests/unit/test_stage1_retrieval_metrics.py`
- Modify: `tests/security/test_gold_case_integrity.py`
- Modify: `tests/security/test_evaluation_runner_security.py`
- Modify: `tests/security/test_generation_prompt_security.py`
- Create: `tests/security/test_stage1_gold_isolation.py`

**Interfaces:**
- Produces: frozen non-Gold dataset digests, per-stage retrieval metrics, and successful-path Gold exclusion evidence.

- [x] **Step 1: Write failing dataset-isolation and metric tests**

The two new datasets use synthetic questions and synthetic metadata IDs.
Tests compare normalized hashes against all Pagila question/SQL/tables/fields/
joins/fixtures and fail on exact or configured reversible-copy matches.

Metrics tests use literal Case evidence to assert Recall@5/10/20,
Precision@5/10/20, mean candidates, channel/fusion/rerank recall, route
distribution, degradation, pruning, and stage latency.

- [x] **Step 2: Verify RED**

```bash
./.venv/bin/pytest -q \
  tests/unit/test_stage1_retrieval_metrics.py \
  tests/security/test_gold_case_integrity.py \
  tests/security/test_evaluation_runner_security.py \
  tests/security/test_generation_prompt_security.py
```

- [x] **Step 3: Implement dataset loading and metrics**

Do not import `EvaluationCase.difficulty` into production. Evaluation compares
the observed production complexity with labels only after the request ends.

- [x] **Step 4: Add successful-path Provider capture**

Run an allowed evaluation Case through a capturing Provider and assert its
messages contain only the current question and authorized runtime Schema,
never Gold SQL/fields/result/labels/fixture. Prove neither Stage 1 dataset is
loaded by `app/`.

- [x] **Step 5: Freeze calibration before quality comparison**

Write the development and calibration SHA-256 values plus the chosen config
hash into the new Stage 1 baseline. After this step, any config change
invalidates the calibration evidence.

### Task 12: Full verification, real-environment qualification, and stage handoff

**Files:**
- Modify: `.env.example`
- Modify: `README.md`
- Modify: `docs/Text-to-SQL项目复现规格.md`
- Modify: `docs/MVP_EXECUTION_PLAN.md`
- Modify: `docs/decisions/0011-explicit-complexity-route-node.md`
- Modify: `docs/superpowers/specs/2026-07-29-enhancement-stage-1-retrieval-routing-design.md`
- Create: `evaluation/reports/enhancement_stage1_qualification.md`
- Modify: this plan's checkbox ledger only through the execution mechanism

**Interfaces:**
- Consumes: Tasks 1–11.
- Produces: exact three-level status, verification evidence, one focused Stage 1 commit only when gates permit, and `origin main` push.

- [ ] **Step 1: Run all locally available tests**

```bash
./.venv/bin/pytest -q tests/unit tests/security
./.venv/bin/pytest -q tests/integration -m integration
./.venv/bin/python -m compileall -q app evaluation tools tests
./.venv/bin/pip check
git diff --check
```

If a real Pagila DSN is absent, report the integration subset that could not
run; do not describe it as passing.

- [ ] **Step 2: Run real Stage 1 environment**

With explicitly approved endpoints and credentials:

- build and verify the real Embedding index;
- run at least two real generation models through their routes;
- run the frozen non-Gold calibration once;
- create a new Pagila/code/config/dependency baseline;
- run the 18 Gold Cases once and independently review evidence.

Record exact versions, hashes, counts, failures, and whether
`real_environment_validated` is true.

- [ ] **Step 3: Independent review**

Provide the complete focused diff and this plan to an independent reviewer.
Resolve every blocking/high finding through a new failing test and rerun the
covering suite. Record any lower-severity residual with an explicit ruling.

- [ ] **Step 4: Confirm commit scope**

```bash
git status --short
git diff --name-only
git remote get-url origin
```

Expected:

- only Stage 0/1 specs, ADR, Stage 1 implementation/tests/evaluation/report,
  and necessary dependency lock metadata are included;
- `docs/Text-to-SQL原项目参考信息.md` is absent;
- origin is `https://github.com/lingyunjie321/text-to-sql-lite.git`.

- [ ] **Step 5: Commit and push only after the required gate**

When the documented Stage 1 gate is satisfied:

```bash
git add <exact reviewed Stage 1 paths>
git commit -m "feat: complete enhanced retrieval and routing stage"
git push origin main
```

If real-environment validation is unavailable or fails, leave
`real_environment_validated=false`, do not claim Stage 1 complete, and do not
use the commit message above.

## Plan Self-Review

- Task 1 implements the complete deterministic complexity contract without
  calling external services.
- Task 2 makes dynamic K an actual candidate bound, not a Trace label.
- Task 3 implements the user-confirmed explicit node and candidate-aware
  two-pass behavior.
- Task 4 makes the first slice independently observable and safe.
- Tasks 5–8 complete real Embedding, versioned authorization-safe hybrid
  retrieval, RRF, and explainable Rerank.
- Tasks 9–10 complete context and model routing without adding Workflow node
  abstractions not approved by the user.
- Task 11 separates development/calibration from Pagila Gold and closes the
  successful-path pollution gap.
- Task 12 distinguishes local function/integration evidence from real
  environment qualification and enforces the single-main Git workflow.
- No task implements Stage 2–5 behavior early, but every deferred capability
  remains in the final mandatory roadmap.
- No task changes or weakens the current SQL safety or execution boundary.
- No task depends on `docs/Text-to-SQL原项目参考信息.md`.
