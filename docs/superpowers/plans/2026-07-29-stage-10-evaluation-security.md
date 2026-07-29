# Stage 10 Evaluation and Security Regression Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> `superpowers:executing-plans` to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add safe tracing, deterministic result comparison, strict Pagila
Case loading, evidence-first real-model evaluation, and per-Case verified
status updates.

**Architecture:** Existing Stage 1–9 components remain authoritative.
Observability wraps `run_workflow` without changing its public interface.
Evaluation first produces a sanitized immutable report; a separate command
updates exactly one passing Case status after review.

**Tech Stack:** Python 3.12, Pydantic 2, existing SQLGlot/PostgreSQL
Connector/LangGraph/OpenAI-compatible Provider, pytest 9.

## Global Constraints

- Do not add production dependencies.
- Do not change Gold questions, SQL, tables, fields, comparison rules, or
  expected behavior. A minimal protected-spec clarification is allowed only
  if required by the resumed objective and must be independently reviewed.
- In `evaluation/cases/pagila_mvp.jsonl`, modify only a single `status` token
  per reviewed passing Case.
- Never include questions, SQL, Prompt, rows, DSN, API key, or raw exceptions
  in Trace or evaluation reports.
- Use the root `.env` without printing secret values.
- Do not weaken Stage 3–9 policies or tests.
- Keep all Stage 10 changes in one final commit:
  `test: complete stage 10 evaluation and security regression`.
- Push only `codex/mvp-stages-3-10`; do not merge to `main`.

---

### Task 1: Strict Case Models, Loader, and Baseline

**Files:**

- Create: `evaluation/__init__.py`
- Create: `evaluation/models.py`
- Create: `evaluation/loader.py`
- Create: `tests/unit/test_evaluation_models.py`
- Create: `tests/unit/test_evaluation_loader.py`
- Create: `tests/security/test_gold_case_integrity.py`

**Interfaces:**

- Produces:
  `load_case_suite(path: Path) -> LoadedCaseSuite`
- Produces:
  `status_neutral_sha256(path: Path) -> str`
- `LoadedCaseSuite` exposes `cases`, `file_sha256`, and
  `status_neutral_sha256`.

- [x] **Step 1: Write strict model and loader tests**

```python
def test_loads_the_locked_18_case_suite() -> None:
    suite = load_case_suite(Path("evaluation/cases/pagila_mvp.jsonl"))
    assert len(suite.cases) == 18
    assert {case.case_id for case in suite.cases} == {
        f"PG-MVP-{number:03d}" for number in range(1, 19)
    }


def test_execute_case_requires_gold_contract(tmp_path: Path) -> None:
    path = tmp_path / "cases.jsonl"
    path.write_text('{"case_id":"PG-MVP-001","status":"draft",'
                    '"category":"single_table","question":"q",'
                    '"expected_behavior":"EXECUTE","gold_sql":""}\\n')
    with pytest.raises(ValueError, match="evaluation case"):
        load_case_suite(path, require_full_suite=False)
```

- [x] **Step 2: Run the tests and confirm RED**

Run:

```bash
.venv/bin/python -m pytest \
  tests/unit/test_evaluation_models.py \
  tests/unit/test_evaluation_loader.py \
  tests/security/test_gold_case_integrity.py -q
```

Expected: collection fails because `evaluation.models` and
`evaluation.loader` do not exist.

- [x] **Step 3: Implement exact Pydantic contracts and suite invariants**

Implement the test-spec fields with `extra="forbid"` and frozen models.
Validate category counts
`5/4/3/1/1/1/2/1`, unique sequential IDs, exact `pagila/postgres`,
EXECUTE/REJECT Gold contracts, and security denominator exclusion tags.

- [x] **Step 4: Implement both SHA-256 calculations**

The neutral hash parses each JSON line, removes only `status`, serializes with
`ensure_ascii=False`, sorted keys and compact separators, joins with `\n`,
and hashes the final trailing-newline payload.

- [x] **Step 5: Run focused tests and full unit/security regression**

Run:

```bash
.venv/bin/python -m pytest \
  tests/unit/test_evaluation_models.py \
  tests/unit/test_evaluation_loader.py \
  tests/security/test_gold_case_integrity.py -q
.venv/bin/python -m pytest tests/unit tests/security -q
```

Expected: all pass; initial neutral hash is
`a00a8ec7496fc4e1533b2773e0267d555357a80be435a02dd70981d76ddb40d7`.

---

### Task 2: Comparator

**Files:**

- Create: `evaluation/comparator.py`
- Create: `tests/unit/test_evaluation_comparator.py`
- Create: `tests/security/test_comparator_errors.py`

**Interfaces:**

- Produces:

```python
def compare_results(
    predicted: ExecutionResult,
    gold: ExecutionResult,
    *,
    mode: ComparisonMode,
    order_sensitive: bool,
    numeric_tolerances: Mapping[str, NumericTolerance],
    key_columns: tuple[str, ...] = (),
) -> ComparisonResult
```

- [x] **Step 1: Write failing tests for exact and multiset semantics**

Cover column count/name/type, reordered rows, duplicate count mismatch,
NULL vs empty string, nested JSON, and legal empty results.

- [x] **Step 2: Write failing tests for numeric/time/keyed semantics**

```python
def test_decimal_tolerance_boundary_is_inclusive() -> None:
    result = compare_results(
        _result(["amount"], [["10.01"]]),
        _result(["amount"], [["10.00"]]),
        mode=ComparisonMode.MULTISET,
        order_sensitive=False,
        numeric_tolerances={
            "amount": NumericTolerance(absolute=Decimal("0.01"))
        },
    )
    assert result.passed is True


def test_keyed_mode_rejects_duplicate_keys() -> None:
    result = compare_results(
        _result(["id", "value"], [[1, "a"], [1, "b"]]),
        _result(["id", "value"], [[1, "a"], [2, "b"]]),
        mode=ComparisonMode.KEYED,
        order_sensitive=False,
        numeric_tolerances={},
        key_columns=("id",),
    )
    assert result.code == "COMPARATOR_DUPLICATE_KEY"
```

- [x] **Step 3: Run and confirm RED**

Run:

```bash
.venv/bin/python -m pytest \
  tests/unit/test_evaluation_comparator.py \
  tests/security/test_comparator_errors.py -q
```

Expected: collection fails because comparator is missing.

- [x] **Step 4: Implement minimal deterministic comparison**

Use column-aware normalization. Timestamptz OID `1184` compares instants in
UTC. Tolerance matching uses deterministic bipartite matching for unordered
rows. Return stable codes only; never interpolate row values.

- [x] **Step 5: Verify focused and full unit tests**

Run:

```bash
.venv/bin/python -m pytest \
  tests/unit/test_evaluation_comparator.py \
  tests/security/test_comparator_errors.py -q
.venv/bin/python -m pytest tests/unit -q
```

---

### Task 3: Safe Trace and Production Wiring

**Files:**

- Create: `app/observability/__init__.py`
- Create: `app/observability/models.py`
- Create: `app/observability/tracing.py`
- Modify: `app/api/bootstrap.py`
- Create: `tests/unit/test_observability_trace.py`
- Create: `tests/security/test_observability_security.py`
- Modify: `tests/unit/test_api_application.py`

**Interfaces:**

- Produces:

```python
class TraceSink(Protocol):
    def emit(self, record: TraceRecord) -> None

def build_trace_record(state: SQLTaskState) -> TraceRecord

class TracedWorkflowRunner:
    def __call__(
        self, state: SQLTaskState, *, context: WorkflowContext
    ) -> SQLTaskState
```

- [x] **Step 1: Write failing safe-record tests**

Build a terminal State containing an SQL attempt, execution rows and model
observations. Assert required IDs/routes/fingerprints/timing/token metadata
exist and serialized output contains none of the SQL, question, row value,
DSN, API key, or Prompt.

- [x] **Step 2: Write failing sink-degradation tests**

Use a Sink whose `emit` raises a secret-bearing exception. Assert the exact
terminal State is returned and logs contain only
`text_to_sql_trace_sink_degraded`.

- [x] **Step 3: Run and confirm RED**

Run:

```bash
.venv/bin/python -m pytest \
  tests/unit/test_observability_trace.py \
  tests/security/test_observability_security.py -q
```

- [x] **Step 4: Implement Trace models and wrapper**

Map only whitelisted fields. `SafeLoggingTraceSink` logs the record's compact
JSON; `TracedWorkflowRunner` catches all Sink exceptions after the base runner
has returned.

- [x] **Step 5: Wire production bootstrap without interface changes**

Set `ApplicationServices.runner` to a `TracedWorkflowRunner` around the
existing `run_workflow`. Do not add fields or parameters to
`ApplicationServices`, `WorkflowContext`, or `run_workflow`.

- [x] **Step 6: Verify trace and API regressions**

Run:

```bash
.venv/bin/python -m pytest \
  tests/unit/test_observability_trace.py \
  tests/security/test_observability_security.py \
  tests/unit/test_api_application.py \
  tests/security/test_api_permissions.py -q
```

---

### Task 4: Evidence-First Evaluation Runner

**Files:**

- Create: `evaluation/runner.py`
- Create: `tests/unit/test_evaluation_runner.py`
- Create: `tests/security/test_evaluation_runner_security.py`
- Create: `tests/integration/test_pagila_evaluation_runner.py`

**Interfaces:**

- Produces:

```python
def evaluate_case(
    case: EvaluationCase,
    *,
    connector: PostgreSQLConnector,
    provider: LLMProvider,
    trace_sink: TraceSink,
) -> CaseEvaluation

def build_evaluation_report(
    evaluations: Sequence[CaseEvaluation],
    *,
    baseline: EvaluationBaseline,
    model_config_id: str,
) -> EvaluationReport
```

- [x] **Step 1: Write failing EXECUTE evidence tests**

Assert Gold SQL is validated and executed before prediction, predicted
result is compared, expected table/field recall is complete, and a mismatch
sets `passed=False` with a stable code.

- [x] **Step 2: Write failing REJECT evidence tests**

Use a dangerous fixture Provider and counting Connector. Assert zero
prediction execution, zero repair, matching public error, and no security
Case in executable-rate metrics.

- [x] **Step 3: Write failing fixture/real-provider routing tests**

Assert PG-MVP-016/017 use only `fixture.model_sql`; PG-MVP-018 uses
`fixture.initial_model_sql` on call one and delegates later calls. Gold SQL
and Gold metadata must not appear in generated messages.

- [x] **Step 4: Run and confirm RED**

Run:

```bash
.venv/bin/python -m pytest \
  tests/unit/test_evaluation_runner.py \
  tests/security/test_evaluation_runner_security.py -q
```

- [x] **Step 5: Implement counting wrappers and evidence logic**

Delegate Connector retry telemetry unchanged. Normalize Case table/field
names to `public.*`. Validate Gold with the same `validate_sql` path. Build
reports from booleans, counts, status enums, stable codes and hashes only.

- [x] **Step 6: Add real Pagila Stub integration**

Use the locked Connector fixture to prove Gold and predicted SQL share the
same database snapshot, multiset comparison passes, dangerous SQL stays
zero-execution, and PG-MVP-018 repairs once.

- [x] **Step 7: Verify focused and full integration**

Run:

```bash
TEXT_TO_SQL_DATABASE_DSN="$stage10_test_dsn" \
  .venv/bin/python -m pytest \
  tests/integration/test_pagila_evaluation_runner.py -q -m integration
```

---

### Task 5: Report Persistence and Single-Case Status Update

**Files:**

- Create: `evaluation/status.py`
- Create: `tools/run_pagila_evaluation.py`
- Create: `tests/unit/test_evaluation_status.py`
- Create: `tests/security/test_gold_status_update_security.py`

**Interfaces:**

- Produces:

```python
def write_report_atomic(
    path: Path, report: EvaluationReport
) -> None

def mark_case_verified(
    case_path: Path,
    report_path: Path,
    *,
    case_id: str,
    expected_status_neutral_sha256: str,
) -> None
```

- [x] **Step 1: Write failing atomic update tests**

Assert one call changes exactly one byte-level token, preserves line order and
trailing newline, refuses a failed/missing Case, refuses stale evidence,
refuses neutral-hash mismatch, and leaves every other byte unchanged.

- [x] **Step 2: Write failing report redaction tests**

Inject secret-looking values into rejected source objects and assert report
JSON contains no question, SQL, Prompt, DSN, API key, row value or raw
exception field.

- [x] **Step 3: Run and confirm RED**

Run:

```bash
.venv/bin/python -m pytest \
  tests/unit/test_evaluation_status.py \
  tests/security/test_gold_status_update_security.py -q
```

- [x] **Step 4: Implement fsync + atomic replace**

Use `NamedTemporaryFile` in the target directory, flush, `os.fsync`, replace,
and fsync the directory. Replace only the matched line's first exact
`"status":"draft"` token.

- [x] **Step 5: Implement CLI**

Commands:

```bash
python -m tools.run_pagila_evaluation evaluate \
  --cases evaluation/cases/pagila_mvp.jsonl \
  --baseline evaluation/pagila_baseline.json \
  --report evaluation/reports/pagila_mvp_stage10.json

python -m tools.run_pagila_evaluation verify-case \
  --cases evaluation/cases/pagila_mvp.jsonl \
  --report evaluation/reports/pagila_mvp_stage10.json \
  --baseline evaluation/pagila_baseline.json \
  --case-id PG-MVP-001
```

Load `.env` only through existing settings loaders. CLI output contains
Case IDs, statuses and stable codes, never settings values.

- [x] **Step 6: Verify focused tests and secret scan**

---

### Task 5A: Generic View-Semantic Candidate Extraction

**Files:**

- Create: `app/connectors/view_semantics.py`
- Create: `tests/unit/test_view_semantics.py`
- Create: `tests/security/test_view_semantics_security.py`

**Interfaces:**

```python
@dataclass(frozen=True, slots=True)
class ViewDefinitionInput:
    schema_name: str
    view_name: str
    sql: str = field(repr=False)

def extract_view_semantic_candidates(
    definitions: Sequence[ViewDefinitionInput],
    *,
    snapshot: SchemaSnapshot,
    allowed_schemas: tuple[str, ...],
    allowed_tables: tuple[str, ...],
    database_schema_sha256: str,
) -> ViewSemanticCandidateLedger: ...

def build_view_semantic_manifest(
    candidates: ViewSemanticCandidateLedger,
    review: ViewSemanticReview,
) -> ViewSemanticManifest: ...

def enrich_schema_snapshot(
    snapshot: SchemaSnapshot,
    manifest: ViewSemanticManifest,
) -> SchemaSnapshot: ...
```

- [x] **Step 1: Write unrelated synthetic positive tests**

Use only synthetic `public.asset(asset_id, is_archived boolean)` metadata and
views. Prove:

```sql
SELECT a.asset_id AS record_key,
       CASE WHEN a.is_archived THEN 'retired' ELSE '' END AS lifecycle_note
FROM public.asset AS a
```

creates a direct alias candidate for `asset_id` and a positive-polarity
`retired` candidate for `is_archived`. Test no Pagila table, field, Case ID,
question, or Gold content.

- [x] **Step 2: Write synthetic fail-closed tests**

Cover unsupported second statements, `SELECT *`, subqueries/CTEs, unqualified
or ambiguous columns, non-boolean conditions, `NOT`, functions/casts,
multi-field conditions, unauthorized table/column dependencies, invalid
search paths, duplicate/conflicting aliases, non-text or expression casts,
and malformed SQL. A single explicit `::text` around a string literal is
covered separately as a no-op PostgreSQL normalization shape.

- [x] **Step 3: Write candidate privacy tests**

Inject view names, unauthorized object names, emails, URLs, long strings,
numeric identifiers, free text, and secret-looking values. Assert serialized
candidate/review/manifest payloads contain no raw SQL, view name, rejected
label, unauthorized identifier, or secret.

- [x] **Step 4: Run focused tests and confirm RED**

```bash
.venv/bin/python -m pytest \
  tests/unit/test_view_semantics.py \
  tests/security/test_view_semantics_security.py -q
```

Expected: import failure because `app.connectors.view_semantics` does not
exist.

- [x] **Step 5: Implement strict models and exact extraction rules**

Use existing SQLGlot. Accept only a single top-level PostgreSQL `SELECT`.
Require qualified, unique lineage and an entirely authorized dependency set.
Implement only `direct_projection_alias_v1` and
`simple_boolean_case_label_v1`. Candidate labels pass NFKC/shape bounds but
remain unapproved.

- [x] **Step 6: Implement per-entry evidence and review digests**

Canonical JSON uses sorted keys, compact separators, and explicit
length-delimited hashing. A review can approve only an existing candidate
digest; manifest construction rejects missing, stale, duplicate, or
unreviewed decisions.

- [x] **Step 7: Implement deterministic snapshot enrichment**

Merge only approved aliases into fields present in the current snapshot.
Never replace names/comments or create objects. Rebuild through
`build_schema_snapshot` so `schema_version` changes deterministically.

- [x] **Step 8: Run focused and existing metadata/linking regression**

```bash
.venv/bin/python -m pytest \
  tests/unit/test_view_semantics.py \
  tests/security/test_view_semantics_security.py \
  tests/unit/test_connector_metadata.py \
  tests/unit/test_schema_linker_scoring.py \
  tests/security/test_schema_linker_permissions.py -q
```

---

### Task 5B: Freeze Tool and Audited Runtime Manifest

**Files:**

- Create: `tools/freeze_view_semantics.py`
- Create: `tests/unit/test_freeze_view_semantics_cli.py`
- Create: `tests/security/test_view_semantics_freeze_security.py`
- Create during freeze:
  `infrastructure/pagila/view_semantic_candidates.json`
- Create during freeze:
  `infrastructure/pagila/view_semantic_review.json`
- Create during freeze:
  `infrastructure/pagila/view_semantics.json`

**Interfaces:**

```bash
python -m tools.freeze_view_semantics candidates \
  --baseline evaluation/pagila_baseline.json \
  --output infrastructure/pagila/view_semantic_candidates.json

python -m tools.freeze_view_semantics review \
  --candidates infrastructure/pagila/view_semantic_candidates.json \
  --review infrastructure/pagila/view_semantic_review.json \
  --evidence-sha256 <digest> --approve

python -m tools.freeze_view_semantics freeze \
  --candidates infrastructure/pagila/view_semantic_candidates.json \
  --review infrastructure/pagila/view_semantic_review.json \
  --output infrastructure/pagila/view_semantics.json
```

- [x] **Step 1: Write failing CLI lifecycle tests**

Use synthetic view-query output. Assert candidates never auto-approve,
`freeze` refuses pending entries, one review command changes exactly one
decision, stale evidence fails, and output is byte-deterministic.

- [x] **Step 2: Write failing source and redaction tests**

Assert the collector uses the locked container only during `candidates`,
normal requests never call it, Docker stderr is discarded, and CLI
stdout/stderr never includes view SQL, labels, object names, DSN, or secrets.

- [x] **Step 3: Run and confirm RED**

```bash
.venv/bin/python -m pytest \
  tests/unit/test_freeze_view_semantics_cli.py \
  tests/security/test_view_semantics_freeze_security.py -q
```

- [x] **Step 4: Implement bounded freeze-only collection**

Read ordinary view definitions from the locked database, normalize the
definition set with stable length-delimited records, and calculate a single
aggregate digest. Keep view identity and SQL only in memory with
`repr=False`; never serialize them.

- [x] **Step 5: Implement atomic candidate/review/manifest writes**

Reuse the Stage 10 fsync + same-directory atomic replace pattern. Manifest
contains only approved authorized-field entries, policy/extractor versions,
base/enriched schema versions, schema dump/scope/view-definition digests, and
candidate/review file hashes.

- [x] **Step 6: Verify the complete synthetic lifecycle**

Run the focused unit/security suites and assert source definition changes,
scope drift, base snapshot drift, policy drift, or file tampering all fail
closed.

---

### Task 5C: Runtime Semantic Wrapper and Prompt Wiring

**Files:**

- Modify: `app/connectors/view_semantics.py`
- Modify: `app/connectors/__init__.py`
- Modify: `app/api/bootstrap.py`
- Modify: `app/generation/models.py`
- Modify: `app/generation/prompt.py`
- Modify: `tools/run_pagila_evaluation.py`
- Create: `tests/unit/test_frozen_semantic_connector.py`
- Modify: `tests/unit/test_generation_prompt.py`
- Modify: `tests/security/test_generation_prompt_security.py`
- Modify: `tests/security/test_evaluation_baseline_security.py`

**Interfaces:**

```python
class FrozenSemanticConnector:
    def read_metadata(
        self,
        allowed_schemas: tuple[str, ...],
        allowed_tables: tuple[str, ...],
    ) -> SchemaSnapshot: ...
    def execute(self, sql: str) -> ExecutionResult: ...
    def read_only_snapshot(self) -> ContextManager[FrozenSemanticConnector]: ...
```

- [x] **Step 1: Write failing wrapper delegation tests**

Assert metadata enrichment is request-scope filtered; execute, retry counts,
and shared read-only snapshot delegate exactly once; manifest/base-snapshot
drift fails before Provider construction.

- [x] **Step 2: Write failing Prompt and leakage tests**

Assert candidate field payloads include only aliases from the trusted
enhanced snapshot. Forged linker aliases, polarity, source digests, review
metadata, raw view SQL, and out-of-scope aliases never enter Prompt, Trace, or
API responses.

- [x] **Step 3: Run and confirm RED**

```bash
.venv/bin/python -m pytest \
  tests/unit/test_frozen_semantic_connector.py \
  tests/unit/test_generation_prompt.py \
  tests/security/test_generation_prompt_security.py \
  tests/security/test_observability_security.py -q
```

- [x] **Step 4: Implement the wrapper and startup verification**

At production/evaluation startup, read the full server allowlist snapshot,
verify manifest SHA against the external baseline, then construct the
wrapper. Do not add request-time catalog/view queries.

- [x] **Step 5: Add aliases to the versioned Prompt payload**

Read aliases from the snapshot, sort/deduplicate, add no new system
instruction, and increment `PROMPT_VERSION`. Keep Gold, Case IDs and generic
boolean preference absent.

- [x] **Step 6: Run focused, Workflow, API, and security regression**

---

### Task 5D: Immutable Evaluation Freeze and Baseline ID

**Files:**

- Create: `evaluation/code_freeze.py`
- Modify: `evaluation/comparator.py`
- Modify: `evaluation/report.py`
- Modify: `evaluation/baseline.py`
- Modify: `evaluation/loader.py`
- Modify: `tools/run_pagila_evaluation.py`
- Modify: `evaluation/pagila_baseline.json`
- Create: `tests/unit/test_evaluation_code_freeze.py`
- Modify: `tests/unit/test_evaluation_baseline.py`
- Modify: `tests/unit/test_evaluation_cli.py`
- Modify: `tests/security/test_evaluation_baseline_security.py`
- Modify: `tests/security/test_gold_case_integrity.py`

**Interfaces:**

```python
COMPARATOR_VERSION = "stage10-comparator-v1"

def controlled_code_sha256(root: Path) -> str: ...
def evaluation_baseline_id(payload: Mapping[str, object]) -> str: ...
```

- [x] **Step 1: Write failing deterministic freeze tests**

Assert stable file ordering and length-delimited hashing. Mutating any
controlled `app/`, `evaluation/`, or Stage 10 tool source changes the digest;
reports, caches, `.env`, and Gold `status` do not enter the code digest.

- [x] **Step 2: Write failing baseline-ID and all-draft tests**

Assert Prompt/Comparator/code/model/manifest/Schema/data/Case-neutral drift
changes or invalidates the baseline ID. `evaluate` must reject before DSN or
LLM credential loading unless all 18 statuses are `draft` and the exact draft
file hash matches the baseline.

- [x] **Step 3: Run and confirm RED**

```bash
.venv/bin/python -m pytest \
  tests/unit/test_evaluation_code_freeze.py \
  tests/unit/test_evaluation_baseline.py \
  tests/unit/test_evaluation_cli.py \
  tests/security/test_evaluation_baseline_security.py \
  tests/security/test_gold_case_integrity.py -q
```

- [x] **Step 4: Implement canonical code/config freeze**

Use fixed path roots and file suffixes, reject symlinks and unexpected
missing paths, and hash relative path + byte length + content. Baseline model
uses `extra="forbid"` and verifies its own ID from all other canonical fields.

- [x] **Step 5: Add `freeze-baseline` and preflight verification**

The command probes locked runtime, validates Pagila fixtures, loads the
approved semantic manifest, computes model config hash without the API key,
and atomically writes the new baseline. `evaluate` repeats every check before
constructing the Provider.

- [x] **Step 6: Mark the 17/18 report permanently invalid**

Move it to an invalidated-history path with a human-readable invalidation
record. It must not validate against the new baseline ID and status tools
must reject it.

- [x] **Step 7: Run focused and complete unit/security regression**

---

### Task 5E: Actual Semantic Freeze and Pre-Gold Independent Review

- [x] **Step 1: Generate candidates from the locked Pagila views**
- [x] **Step 2: Independently inspect and review every candidate**
- [x] **Step 3: Freeze the approved runtime manifest and code trust anchor**
- [x] **Step 4: Finish production/evaluation wiring and run all unrelated
  synthetic tests**
- [x] **Step 5: Dispatch one complete independent initial review**

The reviewer must report all evidenced blocking/high/medium/low findings in
one pass. Review extraction generality, label sensitivity, lineage,
authorization timing, manifest trust anchor, runtime leakage, Prompt scope,
baseline completeness, public interfaces, and test gaps.

- [x] **Step 6: Fix every blocking/high with new non-Gold failing tests**
- [x] **Step 7: Dispatch one final review of fixes and regressions**
- [x] **Step 8: Recompute original/enriched schema versions and new baseline**
- [x] **Step 9: Verify code, Prompt, Comparator, Cases, Schema, data, model
  configuration, semantic manifest, and baseline ID are frozen**

No current Gold question is executed before Step 9 passes.

---

### Task 6: Real-Model 18-Case Evaluation and Per-Case Review

**Files:**

- Create: `evaluation/reports/pagila_mvp_stage10.json`
- Modify only `status` fields in:
  `evaluation/cases/pagila_mvp.jsonl`

- [x] **Step 1: Recompute all resumed-baseline checksums**

It must equal
`e584f0beb3817d1a6f3e35518192ba66cc8b14c50df08c34527d5b15e77bd567`
after normalizing the random `restrict/unrestrict` nonce to `TOKEN`.

- [x] **Step 2: Run candidate 1: all 18 Cases with the real Provider**

Load root `.env` without printing values. Run sequentially. Keep every Case
`draft` while the report is generated.

- [x] **Step 3: Inspect each new Case evidence**

For each Case, verify the required Gold validation/execution/comparison or
zero-execution security evidence. Record the audit result in the report.

- [x] **Step 4: Update each passing Case separately**

Run `verify-case` once per reviewed passing Case only after the complete
18/18 qualification gate passes. Candidate 1 finished at 12/18, so the
status updater was intentionally not invoked and all 18 Cases remain
`draft`.

- [x] **Step 5: Verify Gold immutability**

Assert:

```text
status_neutral_sha256 ==
a00a8ec7496fc4e1533b2773e0267d555357a80be435a02dd70981d76ddb40d7
```

If fewer than 18 are verified after the final allowed candidate, preserve
failures as draft, update the report with exact stable reasons, and enter the
qualification-not-passed engineering terminal outcome.

**Invalidated history (2026-07-29):** The old candidate run produced 17/18
automated passes, with PG-MVP-003 failing field recall. Its structured report
also records `initial_status=verified` from an earlier, subsequently
invalidated status-update attempt, so Step 2 did not satisfy the required
all-draft precondition. Independent review rejected all 18 audit entries and
identified post-hoc boolean coaching and value-changing `bpchar → TRIM(...)`
normalization as High issues. The value rewrite was removed and every Gold
Case was restored byte-for-byte to its original `draft` state. Steps 2 and 4
therefore remain incomplete; the candidate report is retained only as
invalidated evidence and cannot be used by the resumed evaluation.

- [x] **Step 6: Apply the two-run terminal rule**

If candidate 1 is 18/18, proceed to review/status updates. If it exposes a
generic implementation defect demonstrable without current Gold, add that
synthetic regression, re-review the fix, recompute every freeze digest, and
run candidate 2 exactly once. Otherwise candidate 1 is the final
qualification result. Never tune against the current Gold after candidate 2.

- [x] **Step 7: Enter exactly one terminal outcome**

- Qualification passed: 18/18 automated and independently approved, then
  verify each Case separately.
- Qualification not passed: keep failed/insufficient Cases draft, finish
  engineering verification, and use
  `test: implement stage 10 evaluation and record qualification failure`.

---

### Task 7: Documentation, Full Gates, Review, and Commit

**Files:**

- Create: `docs/decisions/0010-evaluation-trace-security.md`
- Modify: `README.md`
- Modify: `docs/MVP_EXECUTION_PLAN.md`

- [x] **Step 1: Run all verification gates**

```bash
.venv/bin/python -m pytest tests/unit -q
.venv/bin/python -m pytest tests/security -q
.venv/bin/python -m pytest tests/integration -q -m integration
.venv/bin/python -m compileall -q app evaluation tools tests
.venv/bin/python -m pip check
PAGILA_POSTGRES_PASSWORD=x PAGILA_APP_USER=text_to_sql_reader \
  PAGILA_APP_PASSWORD=y \
  docker compose -f infrastructure/pagila/compose.yaml config --quiet
git diff --check
```

- [x] **Step 2: Verify FastAPI first-pass and repaired closure within the
  allowed evidence boundary**

Assert Generate → Validate → Execute → optional Reflect → Finalize and safe
Trace. The real Provider runs through the locked 18-Case Workflow evaluation.
FastAPI uses a fixed Stub Provider plus the same real Pagila because the
runtime's external-data review denied sending Case questions and Schema
context through HTTP to the unspecified external model destination. Record
the two evidence paths separately.

- [x] **Step 3: Confirm the bounded independent review is complete**

Use the one initial review and one final fix review from Task 5E. Do not
dispatch additional design-reversal reviews without new evidence. Confirm
the reviewed diff covers correctness, comparator edge cases, Gold mutation
scope, report leakage, permission boundaries, routing, test gaps and scope
drift.

- [x] **Step 4: Re-run every gate after review fixes**

The historical blocked snapshot was unit `502 passed`, security `88 passed`,
real Pagila integration `73 passed`, and single-process full regression
`663 passed`. These are not evidence for the resumed implementation; record
fresh counts.

- [x] **Step 5: Update README, ADR and execution ledger**

Record exact counts, per-Case outcomes, metrics, hashes, review verdict and
limitations. Do not claim release qualification passed unless all 18 are
verified; in the engineering terminal outcome, record implementation
completion and qualification failure separately.

- [x] **Step 6: Commit and push the applicable terminal outcome**

```bash
git add README.md app/api/bootstrap.py app/observability evaluation \
  tools/run_pagila_evaluation.py tests docs/MVP_EXECUTION_PLAN.md \
  docs/decisions/0010-evaluation-trace-security.md \
  docs/superpowers/plans/2026-07-29-stage-10-evaluation-security.md \
  docs/superpowers/specs/2026-07-29-stage-10-evaluation-security-design.md
git commit -m "<qualification-dependent Stage 10 message>"
git push origin codex/mvp-stages-3-10
```

---

### Task 8: Final Acceptance

- [x] **Step 1: Verify commit sequence and clean worktree**
- [x] **Step 2: Review `main...codex/mvp-stages-3-10` complete diff**
- [x] **Step 3: Confirm protected spec hashes and Gold neutral hash**
- [x] **Step 4: Confirm report entries and the selected terminal outcome**
- [ ] **Step 5: Produce the Stage 3–10 final requirement matrix**
- [ ] **Step 6: Mark the active goal complete only after all evidence passes**
