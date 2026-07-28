# Stage 2 PostgreSQL Schema Introspection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Add authorization-scoped PostgreSQL metadata snapshots with tables, columns, comments, PK/FK, unique constraint/index information, and deterministic schema-version fingerprints.

**Architecture:** Immutable driver-independent metadata models live beside the Connector contracts. `PostgreSQLConnector.read_metadata()` performs parameterized `pg_catalog` queries inside one bounded read-only transaction, assembles only fully authorized objects, and fingerprints a canonical snapshot. Stage 2 reuses Stage 1 configuration, pool lifecycle, timeout, error normalization, and connection retry boundary.

**Tech Stack:** Python 3.12, psycopg 3.3.4, psycopg-pool 3.3.1, dataclasses, hashlib/JSON from the standard library, pytest 9.1.1, PostgreSQL 16.14, Pagila 3.1.0.

## Global Constraints

- Read `AGENTS.md`, the main specification's `# MVP 编码入口`, sections 6–7, 10, 13, and 15–17, and test specification sections 1, 4, 6, 10–11 before execution.
- Read `docs/superpowers/specs/2026-07-28-stage-2-schema-introspection-design.md` completely before execution.
- Do not modify `docs/Text-to-SQL项目复现规格.md`, `docs/Text-to-SQL测试与验收规格.md`, or `evaluation/cases/pagila_mvp.jsonl`.
- Reuse the Stage 1 PostgreSQL 16.14 image, Pagila commit, fixture hashes, database settings, read-only transaction, 30-second timeout, pool, normalized errors, and connection retry budget.
- Metadata queries use only fixed SQL plus bound parameters. Never interpolate schema, table, column, constraint, or index names.
- `allowed_tables` contains canonical `schema.table` names. Empty Schema or table scope returns an empty snapshot and never scans all visible objects.
- Only ordinary and partitioned tables (`relkind IN ('r', 'p')`) are included.
- A foreign key is returned only when both endpoints are authorized.
- Business aliases have no approved source. Model `aliases` as an empty tuple and do not infer business meaning.
- Do not implement Schema Linking, BM25, Top-K, JOIN path search, SQLGlot, generation, Workflow, API, Trace, or caching.
- Execute this plan only after the user explicitly authorizes Stage 2 coding. The current request authorizes this document, not its implementation.
- When authorized, execute directly on `main` under the single-branch workflow in `AGENTS.md`; do not create a worktree, `codex/*` branch, or Pull Request unless the user explicitly requests one.

---

## File Map

| Path | Responsibility |
|---|---|
| `app/connectors/metadata.py` | Immutable metadata models, scope normalization, snapshot assembly, canonical serialization, SHA-256 fingerprint |
| `app/connectors/metadata_queries.py` | Fixed parameterized `pg_catalog` query strings |
| `app/connectors/postgresql.py` | One-transaction metadata read, row mapping, and class-08 whole-call retry |
| `app/connectors/__init__.py` | Public metadata and Connector exports |
| `tests/unit/test_connector_metadata.py` | Models, scope, assembly, fingerprint, and malformed relationship tests |
| `tests/unit/test_postgresql_metadata.py` | Connector transaction/query/retry behavior with narrow test doubles |
| `tests/integration/test_postgresql_metadata.py` | Live authorization-scoped Pagila Metadata Contract |
| `docs/decisions/0002-postgresql-metadata-snapshot.md` | Catalog choices, scope semantics, fingerprint format, and verified Pagila evidence |
| `README.md` | Stage 2 usage and verification commands |

## Task 1: Immutable Metadata Models and Deterministic Fingerprint

**Files:**

- Create: `app/connectors/metadata.py`
- Create: `tests/unit/test_connector_metadata.py`
- Modify: `app/connectors/__init__.py`

**Interfaces:**

- Produces: `ColumnMetadata`, `TableMetadata`, `PrimaryKeyMetadata`, `ForeignKeyMetadata`, `UniqueConstraintMetadata`, `UniqueIndexMetadata`, `SchemaSnapshot`, `empty_schema_snapshot()`, and `build_schema_snapshot(...)`.
- Consumes: only Python standard-library values; no psycopg objects.

- [x] **Step 1: Write failing immutable-model tests**

Create literal model fixtures and verify frozen behavior:

```python
from dataclasses import FrozenInstanceError

import pytest

from app.connectors.metadata import ColumnMetadata


def test_column_metadata_is_immutable() -> None:
    column = ColumnMetadata(
        schema_name="public",
        table_name="film",
        column_name="film_id",
        ordinal_position=1,
        data_type="int4",
        formatted_type="integer",
        nullable=False,
        comment=None,
        aliases=(),
    )

    with pytest.raises(FrozenInstanceError):
        column.column_name = "changed"  # type: ignore[misc]
```

Instantiate every model from the design and assert its tuple fields remain tuples.

- [x] **Step 2: Write failing fingerprint tests**

Use hand-built snapshots to prove:

- changing input row order does not change `schema_version`;
- changing a type, nullable flag, comment, PK column, FK endpoint, unique index
  definition, or predicate changes `schema_version`;
- `schema_version` is 64 lowercase hexadecimal characters;
- the empty snapshot has one stable literal fingerprint.

Core ordering test:

```python
def test_schema_version_is_independent_of_input_order() -> None:
    first = build_schema_snapshot(
        tables=(film_table, language_table),
        primary_keys=(film_pk,),
        foreign_keys=(film_language_fk,),
        unique_constraints=(),
        unique_indexes=(),
    )
    second = build_schema_snapshot(
        tables=(language_table, film_table),
        primary_keys=(film_pk,),
        foreign_keys=(film_language_fk,),
        unique_constraints=(),
        unique_indexes=(),
    )

    assert first == second
    assert first.schema_version == second.schema_version
```

- [x] **Step 3: Run tests and verify expected failure**

Run:

```bash
.venv/bin/pytest tests/unit/test_connector_metadata.py -v
```

Expected: collection fails because `app.connectors.metadata` does not exist.

- [x] **Step 4: Implement exact metadata model shapes**

Use frozen, slotted dataclasses. Define:

```python
@dataclass(frozen=True, slots=True)
class ColumnMetadata:
    schema_name: str
    table_name: str
    column_name: str
    ordinal_position: int
    data_type: str
    formatted_type: str
    nullable: bool
    comment: str | None
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class TableMetadata:
    schema_name: str
    table_name: str
    relation_kind: str
    comment: str | None
    columns: tuple[ColumnMetadata, ...]
    aliases: tuple[str, ...] = ()
```

Add the five relationship/index models with the exact fields specified in the
design. Define:

```python
@dataclass(frozen=True, slots=True)
class SchemaSnapshot:
    schemas: tuple[str, ...]
    tables: tuple[TableMetadata, ...]
    primary_keys: tuple[PrimaryKeyMetadata, ...]
    foreign_keys: tuple[ForeignKeyMetadata, ...]
    unique_constraints: tuple[UniqueConstraintMetadata, ...]
    unique_indexes: tuple[UniqueIndexMetadata, ...]
    schema_version: str
```

- [x] **Step 5: Implement canonical assembly and fingerprint**

`build_schema_snapshot()` accepts unsorted tuples, sorts every collection by
the keys in the design, sorts each table's columns by `ordinal_position`, derives
the sorted distinct `schemas`, converts the structure to primitives with
`dataclasses.asdict()`, and serializes with:

```python
payload = json.dumps(
    canonical_data,
    ensure_ascii=False,
    sort_keys=True,
    separators=(",", ":"),
).encode("utf-8")
schema_version = hashlib.sha256(payload).hexdigest()
```

Do not include an empty or provisional `schema_version` in `canonical_data`.
`empty_schema_snapshot()` must call the same builder with empty tuples.

- [x] **Step 6: Export public contracts and run focused tests**

Export all models and builders from `app/connectors/__init__.py`, then run:

```bash
.venv/bin/pytest tests/unit/test_connector_metadata.py -v
.venv/bin/python -m compileall -q app
```

Expected: all metadata model and fingerprint tests pass; compile exits 0.

- [x] **Step 7: Review checkpoint**

Review that `metadata.py` imports neither psycopg nor application config, contains
no mutable collection field, and contains no cache or Schema Linking code.

Suggested commit:

```bash
git add app/connectors/metadata.py app/connectors/__init__.py tests/unit/test_connector_metadata.py
git commit -m "feat: add immutable schema metadata contracts"
```

## Task 2: Authorization Scope and Fixed Catalog Queries

**Files:**

- Modify: `app/connectors/metadata.py`
- Create: `app/connectors/metadata_queries.py`
- Modify: `tests/unit/test_connector_metadata.py`

**Interfaces:**

- Consumes: `allowed_schemas: tuple[str, ...]`, `allowed_tables: tuple[str, ...]`.
- Produces: `MetadataScope`, `normalize_metadata_scope(...)`, and fixed SQL constants `TABLE_COLUMNS_SQL`, `KEY_CONSTRAINTS_SQL`, `FOREIGN_KEYS_SQL`, `UNIQUE_INDEXES_SQL`.

- [x] **Step 1: Write failing scope tests**

Cover:

```python
def test_scope_deduplicates_and_sorts_qualified_tables() -> None:
    scope = normalize_metadata_scope(
        ("public", "public"),
        ("public.language", "public.film", "public.film"),
    )

    assert scope.schemas == ("public",)
    assert scope.table_pairs == (
        ("public", "film"),
        ("public", "language"),
    )
```

Also verify:

- whitespace-only Schema or table names raise
  `ValueError("metadata scope contains an empty identifier")`;
- unqualified `film` raises
  `ValueError("allowed table must be schema-qualified")`;
- `other.film` is removed when `other` is not in `allowed_schemas`;
- either empty input produces `scope.is_empty is True`;
- identifiers are not lowercased.

- [x] **Step 2: Run the scope tests and verify failure**

Run:

```bash
.venv/bin/pytest tests/unit/test_connector_metadata.py -v -k scope
```

Expected: tests fail because `normalize_metadata_scope` is missing.

- [x] **Step 3: Implement `MetadataScope`**

Use:

```python
@dataclass(frozen=True, slots=True)
class MetadataScope:
    schemas: tuple[str, ...]
    table_pairs: tuple[tuple[str, str], ...]

    @property
    def is_empty(self) -> bool:
        return not self.schemas or not self.table_pairs

    @property
    def schema_parameters(self) -> list[str]:
        return [schema for schema, _ in self.table_pairs]

    @property
    def table_parameters(self) -> list[str]:
        return [table for _, table in self.table_pairs]
```

Split each authorized table once at the first dot. Reject an empty side and
filter pairs whose Schema is not allowed.

- [x] **Step 4: Add the shared authorized CTE**

Every query starts with:

```sql
WITH authorized(schema_name, table_name) AS (
    SELECT *
    FROM unnest(%s::text[], %s::text[])
)
```

and joins:

```sql
JOIN authorized AS auth
  ON auth.schema_name = namespace.nspname
 AND auth.table_name = relation.relname
```

The first parameter is `scope.schema_parameters`, the second is
`scope.table_parameters`. Do not create dynamic placeholder counts.

- [x] **Step 5: Define the table/column query**

`TABLE_COLUMNS_SQL` selects these aliases in this order:

```sql
namespace.nspname AS schema_name,
relation.relname AS table_name,
CASE relation.relkind WHEN 'r' THEN 'table' ELSE 'partitioned_table' END
    AS relation_kind,
obj_description(relation.oid, 'pg_class') AS table_comment,
attribute.attname AS column_name,
attribute.attnum AS ordinal_position,
type.typname AS data_type,
format_type(attribute.atttypid, attribute.atttypmod) AS formatted_type,
NOT attribute.attnotnull AS nullable,
col_description(relation.oid, attribute.attnum) AS column_comment
```

Filter `relation.relkind IN ('r', 'p')`, `attribute.attnum > 0`, and
`NOT attribute.attisdropped`. Order by Schema, table, and `attnum`.

- [x] **Step 6: Define constraint and index queries**

`KEY_CONSTRAINTS_SQL` returns `contype IN ('p', 'u')`, one row per key column,
using `unnest(constraint.conkey) WITH ORDINALITY`. It returns constraint name,
kind, Schema, table, column, and ordinal position.

`FOREIGN_KEYS_SQL` uses:

```sql
unnest(constraint.conkey) WITH ORDINALITY AS source_key(attnum, position)
JOIN unnest(constraint.confkey) WITH ORDINALITY
  AS target_key(attnum, position)
  USING (position)
```

Join both source and target relations to `authorized`, then resolve both
attributes. Return one row per paired column ordered by constraint and position.

`UNIQUE_INDEXES_SQL` filters `indisunique`, excludes `indisprimary`, and excludes
indexes referenced by `pg_constraint.conindid`. Return one row per index with:

- index name;
- authorized table identity;
- ordered simple column names aggregated from `indkey`;
- `pg_get_indexdef(indexrelid)`;
- nullable `pg_get_expr(indpred, indrelid)`.

Exclude expression indexes when any `indkey` entry is zero; Stage 2 must not
invent a column name for an expression.

- [x] **Step 7: Verify query constants are parameterized**

Run:

```bash
.venv/bin/pytest tests/unit/test_connector_metadata.py -v -k scope
rg -n "f['\"]|\\.format\\(|% .*allowed|JOIN .*\\{" app/connectors/metadata_queries.py
```

Expected: scope tests pass; the scan finds no Python SQL interpolation.

Suggested commit:

```bash
git add app/connectors/metadata.py app/connectors/metadata_queries.py tests/unit/test_connector_metadata.py
git commit -m "feat: define authorized PostgreSQL metadata queries"
```

## Task 3: Table and Column Snapshot Read

**Files:**

- Modify: `app/connectors/postgresql.py`
- Create: `tests/unit/test_postgresql_metadata.py`
- Create: `tests/integration/test_postgresql_metadata.py`

**Interfaces:**

- Consumes: Stage 1 pool and `MetadataScope`.
- Produces: `PostgreSQLConnector.read_metadata(...)`,
  `_read_metadata_once(scope)`, and table/column mapping inside one read-only transaction.

- [x] **Step 1: Write failing empty-scope unit test**

```python
def test_empty_metadata_scope_does_not_acquire_connection(settings) -> None:
    connector = PostgreSQLConnector(settings)
    connector._pool = Mock()

    snapshot = connector.read_metadata((), ())

    assert snapshot == empty_schema_snapshot()
    connector._pool.connection.assert_not_called()
```

- [x] **Step 2: Write failing transaction/query unit test**

Use a narrow fake connection/cursor that mirrors psycopg row behavior. Assert:

- `SET TRANSACTION READ ONLY` is the first statement;
- local `statement_timeout` uses the Stage 1 value;
- all four catalog queries receive the two array parameters;
- table and column rows become a `TableMetadata` with columns in `attnum` order;
- raw cursor/connection objects never appear in the snapshot.

- [x] **Step 3: Write the first live Pagila metadata test**

```python
@pytest.mark.integration
def test_reads_authorized_film_columns(
    connector: PostgreSQLConnector,
) -> None:
    snapshot = connector.read_metadata(
        ("public",),
        ("public.film",),
    )

    assert snapshot.schemas == ("public",)
    assert [table.table_name for table in snapshot.tables] == ["film"]
    film = snapshot.tables[0]
    assert film.relation_kind == "table"
    assert [column.column_name for column in film.columns[:4]] == [
        "film_id",
        "title",
        "description",
        "release_year",
    ]
    assert film.columns[0].data_type == "int4"
    assert film.columns[0].formatted_type == "integer"
    assert film.columns[0].nullable is False
```

Before implementation, both unit and integration tests must fail because
`read_metadata()` is missing.

- [x] **Step 4: Implement the public method and empty boundary**

Add:

```python
def read_metadata(
    self,
    allowed_schemas: tuple[str, ...],
    allowed_tables: tuple[str, ...],
) -> SchemaSnapshot:
    scope = normalize_metadata_scope(allowed_schemas, allowed_tables)
    if scope.is_empty:
        return empty_schema_snapshot()
    ...
```

The public method retries `_read_metadata_once(scope)` only for normalized
class `08` errors, using `connection_retry_count`. Every retry receives the same
immutable `MetadataScope`.

- [x] **Step 5: Implement one metadata transaction**

Inside `_read_metadata_once()`:

```python
with self._pool.connection(timeout=self._settings.pool_timeout_seconds) as connection:
    with connection.transaction():
        connection.execute("SET TRANSACTION READ ONLY")
        connection.execute(
            "SELECT set_config('statement_timeout', %s, true)",
            (f"{self._settings.statement_timeout_seconds}s",),
        )
        params = (scope.schema_parameters, scope.table_parameters)
        table_rows = connection.execute(TABLE_COLUMNS_SQL, params).fetchall()
        key_rows = connection.execute(KEY_CONSTRAINTS_SQL, params).fetchall()
        foreign_key_rows = connection.execute(FOREIGN_KEYS_SQL, params).fetchall()
        unique_index_rows = connection.execute(UNIQUE_INDEXES_SQL, params).fetchall()
```

Wrap errors through `normalize_database_error()` exactly as Stage 1 does.

- [x] **Step 6: Map table and column rows**

Group by `(schema_name, table_name)`. Construct `ColumnMetadata` from literal
column positions/aliases returned by the query. Reject duplicate ordinal
positions within one table with a public-safe `SCHEMA_ERROR`.

Return a provisional assembled snapshot after Task 4 adds relationships; until
then pass empty relationship tuples to `build_schema_snapshot()`.

- [x] **Step 7: Run focused unit and live tests**

Run:

```bash
.venv/bin/pytest tests/unit/test_postgresql_metadata.py -v -k "empty or transaction or table"
.venv/bin/pytest tests/integration/test_postgresql_metadata.py -v -m integration -k film
```

Expected: table/column tests pass and all Stage 1 tests remain green.

Suggested commit:

```bash
git add app/connectors/postgresql.py tests/unit/test_postgresql_metadata.py tests/integration/test_postgresql_metadata.py
git commit -m "feat: read authorized PostgreSQL table metadata"
```

## Task 4: Keys, Relationships, Unique Indexes, and Retry Boundary

**Files:**

- Modify: `app/connectors/metadata.py`
- Modify: `app/connectors/postgresql.py`
- Modify: `tests/unit/test_connector_metadata.py`
- Modify: `tests/unit/test_postgresql_metadata.py`

**Interfaces:**

- Consumes: catalog rows from Task 3.
- Produces: complete `SchemaSnapshot` assembly and class-08 whole-snapshot retry.

- [x] **Step 1: Write failing relationship assembly tests**

Use shuffled literal rows for:

- `film_pkey(film_id)`;
- `film_actor_pkey(actor_id, film_id)` with ordinality 1 then 2;
- `film_language_id_fkey(language_id → language.language_id)`;
- a two-column synthetic FK whose paired positions must remain aligned;
- one unique constraint;
- `idx_unq_manager_staff_id` independent unique index.

Assert exact tuple order in every model.

- [x] **Step 2: Write failing authorization and malformed-row tests**

Prove:

- FK rows are absent when either endpoint is outside the authorized table set;
- no returned model contains the string `staff` when only `public.film` is authorized;
- a relationship referencing a missing authorized table or column raises
  `PostgreSQLConnectorError` with `SCHEMA_ERROR`, `retryable=False`, and no object name
  in its public message.

- [x] **Step 3: Write failing retry tests**

Patch `_read_metadata_once` with:

```python
scope = normalize_metadata_scope(("public",), ("public.film",))
connector._read_metadata_once = Mock(
    side_effect=[transient_class_08_error, expected_snapshot]
)

assert connector.read_metadata(("public",), ("public.film",)) == expected_snapshot
assert connector._read_metadata_once.call_args_list == [call(scope), call(scope)]
```

Parameterize retry counts 0, 1, and 3. Assert permission, timeout, Schema,
resource, pool-timeout, and unknown errors call once.

- [x] **Step 4: Implement key grouping**

Group PK/unique constraint rows by
`(kind, schema_name, table_name, constraint_name)`, sort columns by the returned
ordinality, and construct the corresponding model.

Group FK rows by
`(source_schema, source_table, constraint_name, target_schema, target_table)`.
Sort by pair position and append source/target columns together so pairing cannot
drift.

- [x] **Step 5: Implement independent unique-index mapping**

For each query row, convert the PostgreSQL `text[]` column list to a tuple,
preserve the complete `definition`, and preserve nullable `predicate`. Reject
an empty column list as `SCHEMA_ERROR`.

- [x] **Step 6: Validate model references before fingerprinting**

Build authorized sets of table identities and column triplets. Every PK,
unique constraint/index, and both sides of every FK must resolve. Raise:

```python
PostgreSQLConnectorError(
    DatabaseError(
        sqlstate=None,
        error_type=ErrorType.SCHEMA_ERROR,
        code="DB_SCHEMA_ERROR",
        retryable=False,
        public_message="The database metadata snapshot is inconsistent.",
    )
)
```

Do not expose the missing identifier.

- [x] **Step 7: Complete whole-call retry**

Reuse the same loop shape as `execute()` without sharing mutable counters or
creating SQL attempts. Preserve already normalized errors and retry only when
`details.retryable` is true.

- [x] **Step 8: Run all metadata unit tests**

Run:

```bash
.venv/bin/pytest tests/unit/test_connector_metadata.py tests/unit/test_postgresql_metadata.py -v
.venv/bin/python -m compileall -q app tests
```

Expected: all model, authorization, relationship, inconsistency, and retry tests pass.

Suggested commit:

```bash
git add app/connectors tests/unit/test_connector_metadata.py tests/unit/test_postgresql_metadata.py
git commit -m "feat: assemble PostgreSQL metadata relationships"
```

## Task 5: Live Pagila Metadata Contract

**Files:**

- Modify: `tests/integration/test_postgresql_metadata.py`
- Modify: `app/connectors/postgresql.py` only for test-proven defects

**Interfaces:**

- Consumes: complete Stage 2 Connector interface.
- Produces: evidence for the Pagila portion of the Connector Metadata Contract.

- [x] **Step 1: Add failing PK and FK tests**

Read the exact scopes required by each assertion:

```python
snapshot = connector.read_metadata(
    ("public",),
    ("public.film", "public.language", "public.film_actor", "public.actor"),
)
```

Assert:

- `film_pkey.columns == ("film_id",)`;
- `film_actor_pkey.columns == ("actor_id", "film_id")`;
- `film_language_id_fkey.source_columns == ("language_id",)`;
- `film_language_id_fkey.target_columns == ("language_id",)`;
- source is `public.film`, target is `public.language`.

- [x] **Step 2: Add failing unique-index tests**

For scope `public.store`, assert:

```python
assert unique_index.index_name == "idx_unq_manager_staff_id"
assert unique_index.columns == ("manager_staff_id",)
assert unique_index.predicate is None
```

For scope `public.rental`, assert the index
`idx_unq_rental_rental_date_inventory_id_customer_id` has columns
`("rental_date", "inventory_id", "customer_id")`.

- [x] **Step 3: Add failing authorization tests**

Read only `public.film` and assert:

- exactly one table is returned;
- no FK is returned because its targets are outside scope;
- serialized dataclass content contains neither `staff` nor `language`;
- unknown `public.not_a_table` produces an empty snapshot without revealing whether
  another hidden table exists.

- [x] **Step 4: Add fingerprint stability test**

Read the same authorized scope twice using one open Connector and assert identical
snapshots and identical `schema_version`. Assert the value matches the lowercase
hex pattern, not a hard-coded digest tied to an implementation serialization.

- [x] **Step 5: Run Stage 2 live tests and fix only observed defects**

Run:

```bash
.venv/bin/pytest tests/integration/test_postgresql_metadata.py -v -m integration
```

Expected: all live Pagila metadata tests pass. Any correction must remain within
metadata row mapping, query constants, or snapshot assembly.

- [x] **Step 6: Run Stage 1 regression suites**

Run:

```bash
.venv/bin/pytest tests/unit -v
.venv/bin/pytest tests/integration -v -m integration
```

Expected: every Stage 1 and Stage 2 test passes.

- [x] **Step 7: Review checkpoint**

Run a credential/object leakage scan:

```bash
rg -n 'postgresql://[^[:space:]]+:[^[:space:]]+@|password authentication failed|public\\.staff' \
  app docs/decisions README.md \
  --glob '!tests/**'
```

Expected: no usable DSN; the authentication phrase appears only in the documented
Stage 1 technical exception if retained, and `public.staff` does not appear in
runtime errors or hard-coded authorization.

Suggested commit:

```bash
git add app/connectors tests/integration/test_postgresql_metadata.py
git commit -m "test: prove Pagila metadata connector contract"
```

## Task 6: Stage 2 Decision Record and Final Verification

**Files:**

- Create: `docs/decisions/0002-postgresql-metadata-snapshot.md`
- Modify: `README.md`

**Interfaces:**

- Consumes: verified implementation and test output from Tasks 1–5.
- Produces: reproducible Stage 2 usage, catalog/fingerprint decisions, and explicit Stage 3 exclusions.

- [x] **Step 1: Write the decision record**

Record:

- why `pg_catalog` was selected over `information_schema` and SQLAlchemy;
- included relation kinds;
- exact authorization scope semantics;
- FK two-end authorization rule;
- system catalogs used;
- alias policy;
- canonical JSON and SHA-256 fingerprint format;
- verified Pagila tables, PK/FK, and unique indexes;
- test counts;
- Stage 3 SQLGlot safety-validation exclusion.

- [x] **Step 2: Update README usage**

Add a Stage 2 example:

```python
with PostgreSQLConnector(settings) as connector:
    snapshot = connector.read_metadata(
        ("public",),
        ("public.film", "public.language"),
    )
```

Explain that callers must provide server-derived authorization scope and must not
use user question text to expand it.

- [x] **Step 3: Run deterministic verification**

Run:

```bash
.venv/bin/pytest tests/unit -v
.venv/bin/python -m compileall -q app tools tests
docker compose -f infrastructure/pagila/compose.yaml config --quiet
.venv/bin/pytest tests/integration -v -m integration
```

Expected: all commands exit 0.

- [x] **Step 4: Verify protected files**

Before implementation, record SHA-256 for:

```bash
shasum -a 256 \
  docs/Text-to-SQL项目复现规格.md \
  docs/Text-to-SQL测试与验收规格.md \
  evaluation/cases/pagila_mvp.jsonl
```

Run the same command at completion and require byte-for-byte identical values.

- [x] **Step 5: Audit Stage 2 scope**

Run:

```bash
find app -maxdepth 3 -type f -print | sort
rg -n 'BM25|top_k|sqlglot|GenerateSQL|LangGraph|FastAPI' app
```

Expected: only Stage 1 Connector/config files and Stage 2 metadata files exist;
the scope scan finds no later-stage implementation.

- [x] **Step 6: Stop PostgreSQL without deleting data**

Run:

```bash
docker compose -f infrastructure/pagila/compose.yaml down
```

Expected: the container and network stop while the named Pagila volume remains.

- [x] **Step 7: Final review checkpoint**

Produce a Stage 2 report containing:

- unit and integration test counts;
- authorized table/column evidence;
- PK/FK/unique index evidence;
- fingerprint stability evidence;
- empty/unknown scope behavior;
- Stage 3 exclusions;
- environment-specific limitations.

Suggested commit:

```bash
git add README.md docs/decisions/0002-postgresql-metadata-snapshot.md
git commit -m "docs: record PostgreSQL metadata snapshot contract"
```

## Execution Order and Stop Conditions

Execute Tasks 1 through 6 in order only after explicit user authorization to
start Stage 2 coding. Stop and report before changing this design if:

- PostgreSQL 16.14 system catalogs cannot represent a required metadata field;
- the read-only application role cannot read the required authorized catalog rows;
- a required FK or unique index cannot be filtered without exposing an unauthorized endpoint;
- deterministic fingerprinting would require volatile database identifiers;
- a required action would modify one of the three protected specification/Case files.
