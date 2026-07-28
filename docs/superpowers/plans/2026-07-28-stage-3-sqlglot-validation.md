# Stage 3 SQLGlot PostgreSQL Safety Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a fail-closed PostgreSQL SQL validator that accepts only one authorized, read-only `SELECT`, verifies tables and columns against the Stage 2 snapshot, and enforces the MVP function policy.

**Architecture:** A new pure `app.validation` package owns immutable results, the versioned policy, and SQLGlot orchestration. The validator parses with the PostgreSQL dialect, rejects dangerous or unknown AST before object resolution, resolves only trusted authorization scope against the immutable Stage 2 snapshot, qualifies fields on an AST copy, and returns driver-independent evidence. It never executes SQL.

**Tech Stack:** Python 3.12, SQLGlot 30.13.0, frozen/slotted dataclasses, Stage 2 `SchemaSnapshot`/`MetadataScope`, pytest 9.1.1, PostgreSQL 16.14, Pagila 3.1.0.

## Global Constraints

- Read `AGENTS.md`, the main specification's `# MVP 编码入口`, sections 4–6, 9, 13, and 15–17, and test specification sections 1, 5, 8, and 10–11 before execution.
- Read `docs/superpowers/specs/2026-07-28-stage-3-sqlglot-validation-design.md` completely before execution.
- Read `evaluation/cases/pagila_mvp.jsonl` before adding Pagila validation tests.
- Do not modify `docs/Text-to-SQL项目复现规格.md`, `docs/Text-to-SQL测试与验收规格.md`, or `evaluation/cases/pagila_mvp.jsonl`.
- Pin `sqlglot==30.13.0`; do not use a range or the optional C/Rust extension.
- Parse only with `read="postgres"` and serialize only with `dialect="postgres"`.
- Validation is fail-closed: explicitly forbidden and unknown AST nodes/functions never pass.
- Authorization comes from `allowed_schemas` and canonical `schema.table` names, never from SQL text, question text, or database visibility.
- Field existence comes only from the passed Stage 2 snapshot; validation performs no database query.
- Failure messages must not contain SQL, Schema/table/field/function names, SQLGlot errors, DSN, or credentials.
- Do not implement Schema Linking, generation, SQL fingerprints, Workflow, Connector execution, API, Trace, or resource-cost estimation.
- Execute this plan only after the user explicitly authorizes Stage 3 coding. The current request authorizes the design and plan, not implementation.
- When authorized, execute directly on `main` under the single-branch workflow in `AGENTS.md`; do not create a worktree, `codex/*` branch, or Pull Request unless explicitly requested.

---

## File Map

| Path | Responsibility |
|---|---|
| `pyproject.toml` | Pin SQLGlot 30.13.0 |
| `app/validation/models.py` | Immutable validation result and issue contracts |
| `app/validation/policy.py` | `mvp-v1` AST/function policy and public-safe issue constants |
| `app/validation/sql_validator.py` | Parse, structural safety, scope authorization, qualification, and evidence |
| `app/validation/__init__.py` | Public validation exports |
| `tests/unit/test_validation_models.py` | Model invariants and policy pin |
| `tests/unit/test_sql_validator_structure.py` | Parser, statement, read-only, forbidden AST, wildcard |
| `tests/unit/test_sql_validator_functions.py` | Complete function allowlist and default-deny behavior |
| `tests/unit/test_sql_validator_objects.py` | Table authorization, CTE/derived sources, fields, aliases, subqueries |
| `tests/security/test_sql_validator_security.py` | Full P0 dangerous SQL matrix and leakage assertions |
| `tests/integration/test_pagila_sql_validation.py` | Pagila Case SQL against live Stage 2 snapshots |
| `docs/decisions/0003-sqlglot-safety-policy.md` | Version, AST, authorization, functions, errors, and evidence |
| `README.md` | Stage 3 status, validator usage, and verification commands |

## Task 1: Dependency, Immutable Contracts, and Policy Skeleton

**Files:**

- Modify: `pyproject.toml`
- Create: `app/validation/__init__.py`
- Create: `app/validation/models.py`
- Create: `app/validation/policy.py`
- Create: `tests/unit/test_validation_models.py`

**Interfaces:**

- Consumes: `ErrorType` from `app.connectors.errors`.
- Produces: `ValidationIssue`, `ValidationResult`, `POLICY_VERSION`, `success_result(...)`, and `failure_result(...)`.

- [ ] **Step 1: Write failing contract tests**

Create `tests/unit/test_validation_models.py`:

```python
from dataclasses import FrozenInstanceError

import pytest

from app.connectors.errors import ErrorType
from app.validation import (
    POLICY_VERSION,
    ValidationIssue,
    ValidationResult,
)


def test_validation_contracts_are_immutable() -> None:
    issue = ValidationIssue(
        error_type=ErrorType.PERMISSION_DENIED,
        code="SQL_NOT_READ_ONLY",
        public_message="The SQL statement is not permitted.",
    )
    result = ValidationResult(
        is_valid=False,
        normalized_sql=None,
        referenced_tables=(),
        referenced_columns=(),
        issue=issue,
        policy_version="mvp-v1",
    )

    with pytest.raises(FrozenInstanceError):
        result.is_valid = True  # type: ignore[misc]
    assert isinstance(result.referenced_tables, tuple)
    assert isinstance(result.referenced_columns, tuple)


def test_policy_version_is_explicit() -> None:
    assert POLICY_VERSION == "mvp-v1"
```

- [ ] **Step 2: Run the tests and verify expected failure**

Run:

```bash
.venv/bin/python -m pytest tests/unit/test_validation_models.py -v
```

Expected: collection fails because `app.validation` does not exist.

- [ ] **Step 3: Pin and install SQLGlot**

Add to `[project].dependencies` in `pyproject.toml`:

```toml
"sqlglot==30.13.0",
```

Install the edited project:

```bash
.venv/bin/python -m pip install -e '.[test]'
.venv/bin/python -c "import sqlglot; assert sqlglot.__version__ == '30.13.0'"
```

Expected: installation exits 0 and prints no assertion error.

- [ ] **Step 4: Implement immutable result contracts**

Create `app/validation/models.py`:

```python
from dataclasses import dataclass

from app.connectors.errors import ErrorType


POLICY_VERSION = "mvp-v1"


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    error_type: ErrorType
    code: str
    public_message: str


@dataclass(frozen=True, slots=True)
class ValidationResult:
    is_valid: bool
    normalized_sql: str | None
    referenced_tables: tuple[str, ...]
    referenced_columns: tuple[str, ...]
    issue: ValidationIssue | None
    policy_version: str
```

Create `policy.py` with:

```python
from app.validation.models import POLICY_VERSION

__all__ = ["POLICY_VERSION"]
```

Task 2 extends this module with AST policy and issue objects. This keeps
`models.py` independent from policy issue objects and avoids a module cycle.
Export the three public contract names from `app/validation/__init__.py`.

- [ ] **Step 5: Add result factory tests**

Extend `tests/unit/test_validation_models.py`:

```python
from app.validation.models import failure_result, success_result


def test_failure_result_contains_no_partial_sql_or_references() -> None:
    issue = ValidationIssue(
        error_type=ErrorType.SYNTAX_ERROR,
        code="SQL_PARSE_ERROR",
        public_message="The SQL statement is invalid.",
    )

    result = failure_result(issue)

    assert result == ValidationResult(
        is_valid=False,
        normalized_sql=None,
        referenced_tables=(),
        referenced_columns=(),
        issue=issue,
        policy_version="mvp-v1",
    )


def test_success_result_sorts_and_deduplicates_references() -> None:
    result = success_result(
        "SELECT film_id FROM film",
        referenced_tables=("public.film", "public.film"),
        referenced_columns=(
            "public.film.film_id",
            "public.film.film_id",
        ),
    )

    assert result.referenced_tables == ("public.film",)
    assert result.referenced_columns == ("public.film.film_id",)
    assert result.issue is None
```

- [ ] **Step 6: Run and verify the new tests fail**

Run:

```bash
.venv/bin/python -m pytest tests/unit/test_validation_models.py -v
```

Expected: factory tests fail because `failure_result` and `success_result` are missing.

- [ ] **Step 7: Implement the factories**

Add exact keyword-only factories to `models.py`:

```python
def failure_result(issue: ValidationIssue) -> ValidationResult:
    return ValidationResult(
        is_valid=False,
        normalized_sql=None,
        referenced_tables=(),
        referenced_columns=(),
        issue=issue,
        policy_version=POLICY_VERSION,
    )


def success_result(
    normalized_sql: str,
    *,
    referenced_tables: tuple[str, ...],
    referenced_columns: tuple[str, ...],
) -> ValidationResult:
    return ValidationResult(
        is_valid=True,
        normalized_sql=normalized_sql,
        referenced_tables=tuple(sorted(set(referenced_tables))),
        referenced_columns=tuple(sorted(set(referenced_columns))),
        issue=None,
        policy_version=POLICY_VERSION,
    )
```

Use the `POLICY_VERSION` defined in `models.py` and export both factories.

- [ ] **Step 8: Run focused verification**

Run:

```bash
.venv/bin/python -m pytest tests/unit/test_validation_models.py -v
.venv/bin/python -m compileall -q app/validation
```

Expected: contract tests pass and compilation exits 0.

- [ ] **Step 9: Review checkpoint and commit**

Confirm `app.validation` imports neither psycopg nor `PostgreSQLConnector`, and result models contain no SQLGlot AST.

```bash
git add pyproject.toml app/validation tests/unit/test_validation_models.py
git commit -m "feat: define SQL validation contracts"
```

## Task 2: PostgreSQL Parsing and Structural Safety Gate

**Files:**

- Modify: `app/validation/policy.py`
- Create: `app/validation/sql_validator.py`
- Create: `tests/unit/test_sql_validator_structure.py`
- Modify: `app/validation/__init__.py`

**Interfaces:**

- Consumes: empty or populated `SchemaSnapshot` and canonical authorization tuples.
- Produces: `validate_sql(sql, *, allowed_schemas, allowed_tables, snapshot) -> ValidationResult`.

- [ ] **Step 1: Write failing parser and statement tests**

Create `tests/unit/test_sql_validator_structure.py`:

```python
import pytest

from app.connectors.errors import ErrorType
from app.connectors.metadata import empty_schema_snapshot
from app.validation import validate_sql


def _validate(sql: str):
    return validate_sql(
        sql,
        allowed_schemas=(),
        allowed_tables=(),
        snapshot=empty_schema_snapshot(),
    )


def test_accepts_one_table_free_select() -> None:
    result = _validate("select current_date")

    assert result.is_valid
    assert result.normalized_sql == "SELECT CURRENT_DATE"


@pytest.mark.parametrize("sql", ["", "   ", "SELECT ("])
def test_parse_failures_are_repairable_syntax_errors(sql: str) -> None:
    result = _validate(sql)

    assert not result.is_valid
    assert result.issue is not None
    assert result.issue.error_type is ErrorType.SYNTAX_ERROR
    assert result.issue.code == "SQL_PARSE_ERROR"


def test_rejects_all_statements_when_input_contains_two() -> None:
    result = _validate("SELECT 1; SELECT 2")

    assert not result.is_valid
    assert result.issue is not None
    assert result.issue.error_type is ErrorType.PERMISSION_DENIED
    assert result.issue.code == "SQL_MULTIPLE_STATEMENTS"
```

- [ ] **Step 2: Run and verify failure**

Run:

```bash
.venv/bin/python -m pytest tests/unit/test_sql_validator_structure.py -v \
  -k "table_free or parse or two"
```

Expected: collection fails because `validate_sql` is missing.

- [ ] **Step 3: Define public-safe issue constants**

Extend the imports in `policy.py`:

```python
from sqlglot import exp

from app.connectors.errors import ErrorType
from app.validation.models import POLICY_VERSION, ValidationIssue
```

Then define:

```python
PARSE_ERROR = ValidationIssue(
    ErrorType.SYNTAX_ERROR,
    "SQL_PARSE_ERROR",
    "The SQL statement is invalid.",
)
MULTIPLE_STATEMENTS = ValidationIssue(
    ErrorType.PERMISSION_DENIED,
    "SQL_MULTIPLE_STATEMENTS",
    "The SQL statement is not permitted.",
)
NOT_READ_ONLY = ValidationIssue(
    ErrorType.PERMISSION_DENIED,
    "SQL_NOT_READ_ONLY",
    "The SQL statement is not permitted.",
)
FORBIDDEN_NODE = ValidationIssue(
    ErrorType.PERMISSION_DENIED,
    "SQL_FORBIDDEN_NODE",
    "The SQL statement is not permitted.",
)
WILDCARD_FORBIDDEN = ValidationIssue(
    ErrorType.PERMISSION_DENIED,
    "SQL_WILDCARD_FORBIDDEN",
    "The SQL statement is not permitted.",
)
UNKNOWN_AST = ValidationIssue(
    ErrorType.PERMISSION_DENIED,
    "SQL_UNKNOWN_AST",
    "The SQL statement is not permitted.",
)
DIALECT_ERROR = ValidationIssue(
    ErrorType.DIALECT_ERROR,
    "SQL_DIALECT_ERROR",
    "The SQL dialect is not supported.",
)
```

Positional construction is allowed because all three fields are explicit and immutable.

- [ ] **Step 4: Implement only parsing and single-statement behavior**

Create `sql_validator.py`:

```python
from sqlglot import ErrorLevel, exp, parse
from sqlglot.errors import ParseError, UnsupportedError

from app.connectors.metadata import SchemaSnapshot
from app.validation.models import (
    ValidationResult,
    failure_result,
    success_result,
)
from app.validation.policy import (
    DIALECT_ERROR,
    MULTIPLE_STATEMENTS,
    NOT_READ_ONLY,
    PARSE_ERROR,
)


def validate_sql(
    sql: str,
    *,
    allowed_schemas: tuple[str, ...],
    allowed_tables: tuple[str, ...],
    snapshot: SchemaSnapshot,
) -> ValidationResult:
    try:
        expressions = [
            item
            for item in parse(
                sql,
                read="postgres",
                error_level=ErrorLevel.RAISE,
            )
            if item
        ]
    except ParseError:
        return failure_result(PARSE_ERROR)
    if not expressions:
        return failure_result(PARSE_ERROR)
    if len(expressions) != 1:
        return failure_result(MULTIPLE_STATEMENTS)

    expression = expressions[0]
    if not isinstance(expression, exp.Select):
        return failure_result(NOT_READ_ONLY)
    try:
        normalized_sql = expression.sql(
            dialect="postgres",
            unsupported_level=ErrorLevel.RAISE,
        )
    except UnsupportedError:
        return failure_result(DIALECT_ERROR)
    return success_result(
        normalized_sql,
        referenced_tables=(),
        referenced_columns=(),
    )
```

Temporarily accept only behavior covered by these tests. Object context is added in Tasks 4–5.

- [ ] **Step 5: Run parser tests green**

Run:

```bash
.venv/bin/python -m pytest tests/unit/test_sql_validator_structure.py -v \
  -k "table_free or parse or two"
```

Expected: selected tests pass.

- [ ] **Step 6: Add failing forbidden-node tests**

Add a parameterized table:

```python
@pytest.mark.parametrize(
    "sql",
    [
        "INSERT INTO film(film_id) VALUES (1)",
        "UPDATE film SET title = 'x'",
        "DELETE FROM film",
        "MERGE INTO film USING language ON true WHEN MATCHED THEN DELETE",
        "CREATE TABLE unsafe(id int)",
        "ALTER TABLE film ADD COLUMN unsafe int",
        "DROP TABLE film",
        "TRUNCATE TABLE film",
        "COPY film TO STDOUT",
        "CALL unsafe()",
        "DO $$ BEGIN END $$",
        "SET search_path TO public",
        "RESET search_path",
        (
            "WITH changed AS (DELETE FROM film RETURNING film_id) "
            "SELECT film_id FROM changed"
        ),
        "SELECT film_id INTO backup FROM film",
        "SELECT film_id FROM film FOR UPDATE",
        "SELECT film_id FROM film FOR SHARE",
    ],
)
def test_rejects_non_read_only_or_forbidden_ast(sql: str) -> None:
    result = _validate(sql)

    assert not result.is_valid
    assert result.issue is not None
    assert result.issue.error_type is ErrorType.PERMISSION_DENIED
    assert result.issue.code in {
        "SQL_NOT_READ_ONLY",
        "SQL_FORBIDDEN_NODE",
    }
```

Add:

```python
@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM film",
        "SELECT film.* FROM film",
        "SELECT COUNT(film.*) FROM film",
    ],
)
def test_rejects_projection_wildcards(sql: str) -> None:
    assert _validate(sql).issue.code == "SQL_WILDCARD_FORBIDDEN"


def test_allows_count_star() -> None:
    assert _validate("SELECT COUNT(*)").is_valid


def test_unknown_ast_fails_closed() -> None:
    result = _validate("SELECT 1 OFFSET 1")
    assert result.issue.code == "SQL_UNKNOWN_AST"
```

- [ ] **Step 7: Run forbidden tests and verify failure**

Run:

```bash
.venv/bin/python -m pytest tests/unit/test_sql_validator_structure.py -v
```

Expected: forbidden CTE, locks, wildcards, or unknown AST cases fail because traversal policy is missing.

- [ ] **Step 8: Implement structural policy**

In `policy.py`, define:

```python
FORBIDDEN_NODE_TYPES = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Merge,
    exp.Create,
    exp.Alter,
    exp.Drop,
    exp.TruncateTable,
    exp.Copy,
    exp.Command,
    exp.Set,
    exp.Into,
    exp.Lock,
)

ALLOWED_NON_FUNCTION_NODE_TYPES = frozenset({
    exp.Select,
    exp.From,
    exp.Join,
    exp.Subquery,
    exp.CTE,
    exp.With,
    exp.Alias,
    exp.TableAlias,
    exp.Table,
    exp.Column,
    exp.Identifier,
    exp.Literal,
    exp.Null,
    exp.Boolean,
    exp.Where,
    exp.Group,
    exp.Having,
    exp.Order,
    exp.Ordered,
    exp.Limit,
    exp.Distinct,
    exp.Star,
    exp.DataType,
    exp.Var,
    exp.Exists,
    exp.Paren,
    exp.Not,
    exp.And,
    exp.Or,
    exp.EQ,
    exp.NEQ,
    exp.GT,
    exp.GTE,
    exp.LT,
    exp.LTE,
    exp.Is,
    exp.Between,
    exp.In,
    exp.Like,
    exp.ILike,
    exp.Add,
    exp.Sub,
    exp.Mul,
    exp.Div,
    exp.Mod,
    exp.Neg,
})
```

In `sql_validator.py`, after root validation:

1. Reject any node matching `FORBIDDEN_NODE_TYPES`.
2. Reject a `Star` unless its direct parent is `exp.Count` and the star is
   unqualified; `COUNT(table.*)` has a `Column` wrapper and remains rejected.
3. Skip `exp.Func` subclasses in the generic AST allowlist; Task 3 validates every function.
4. Reject any other exact node type outside `ALLOWED_NON_FUNCTION_NODE_TYPES`.

Do not use `isinstance(node, exp.Expression)` as a broad allow rule.

- [ ] **Step 9: Run complete structural tests**

Run:

```bash
.venv/bin/python -m pytest tests/unit/test_sql_validator_structure.py -v
.venv/bin/python -m compileall -q app/validation tests/unit/test_sql_validator_structure.py
```

Expected: all structural tests pass.

- [ ] **Step 10: Review checkpoint and commit**

Verify `sql_validator.py` contains no regular-expression SQL safety checks and never truncates a multi-statement input to its first statement.

```bash
git add app/validation tests/unit/test_sql_validator_structure.py
git commit -m "feat: enforce SQLGlot structural safety gate"
```

## Task 3: Versioned Function Allowlist

**Files:**

- Modify: `app/validation/policy.py`
- Modify: `app/validation/sql_validator.py`
- Create: `tests/unit/test_sql_validator_functions.py`

**Interfaces:**

- Consumes: parsed SQLGlot `exp.Func` nodes.
- Produces: an exact logical function-name mapping and `SQL_FUNCTION_NOT_ALLOWED` failures.

- [ ] **Step 1: Write failing approved-function tests**

Create `tests/unit/test_sql_validator_functions.py`:

```python
import pytest

from app.connectors.metadata import empty_schema_snapshot
from app.validation import validate_sql


def _validate(expression: str):
    return validate_sql(
        f"SELECT {expression}",
        allowed_schemas=(),
        allowed_tables=(),
        snapshot=empty_schema_snapshot(),
    )


@pytest.mark.parametrize(
    "expression",
    [
        "COUNT(1)",
        "SUM(1)",
        "AVG(1)",
        "MIN(1)",
        "MAX(1)",
        "COALESCE(NULL, 0)",
        "NULLIF(1, 0)",
        "LOWER('A')",
        "UPPER('a')",
        "LENGTH('a')",
        "TRIM(' a ')",
        "SUBSTRING('abc' FROM 1 FOR 2)",
        "DATE_TRUNC('month', TIMESTAMP '2026-07-28')",
        "EXTRACT(YEAR FROM DATE '2026-07-28')",
        "CURRENT_DATE",
        "ROUND(1.5)",
        "ABS(-1)",
        "CEIL(1.2)",
        "FLOOR(1.8)",
        "CASE WHEN 1 = 1 THEN 1 ELSE 0 END",
        "CAST(1 AS TEXT)",
    ],
)
def test_allows_only_mvp_function_set(expression: str) -> None:
    assert _validate(expression).is_valid
```

- [ ] **Step 2: Write failing denied-function tests**

Add:

```python
@pytest.mark.parametrize(
    "expression",
    [
        "pg_sleep(1)",
        "dblink('x', 'y')",
        "pg_read_file('/tmp/x')",
        "lo_import('/tmp/x')",
        "custom_udf(1)",
        "IF(TRUE, 1, 0)",
    ],
)
def test_rejects_anonymous_unapproved_and_if_functions(
    expression: str,
) -> None:
    result = _validate(expression)

    assert not result.is_valid
    assert result.issue is not None
    assert result.issue.code == "SQL_FUNCTION_NOT_ALLOWED"
    assert expression.split("(", 1)[0].lower() not in (
        result.issue.public_message.lower()
    )
```

- [ ] **Step 3: Run and verify failure**

Run:

```bash
.venv/bin/python -m pytest tests/unit/test_sql_validator_functions.py -v
```

Expected: approved functions are rejected by the unfinished function gate or denied functions get the wrong issue code.

- [ ] **Step 4: Define the exact function mapping**

In `policy.py`:

```python
ALLOWED_FUNCTION_NAMES = {
    exp.Count: "COUNT",
    exp.Sum: "SUM",
    exp.Avg: "AVG",
    exp.Min: "MIN",
    exp.Max: "MAX",
    exp.Coalesce: "COALESCE",
    exp.Nullif: "NULLIF",
    exp.Lower: "LOWER",
    exp.Upper: "UPPER",
    exp.Length: "LENGTH",
    exp.Trim: "TRIM",
    exp.Substring: "SUBSTRING",
    exp.TimestampTrunc: "DATE_TRUNC",
    exp.Extract: "EXTRACT",
    exp.CurrentDate: "CURRENT_DATE",
    exp.Round: "ROUND",
    exp.Abs: "ABS",
    exp.Ceil: "CEIL",
    exp.Floor: "FLOOR",
    exp.Case: "CASE",
    exp.Cast: "CAST",
}

FUNCTION_NOT_ALLOWED = ValidationIssue(
    ErrorType.PERMISSION_DENIED,
    "SQL_FUNCTION_NOT_ALLOWED",
    "The SQL statement uses a function that is not permitted.",
)
```

- [ ] **Step 5: Implement function validation**

For every `exp.Func` node:

- allow `exp.If` only when its parent is `exp.Case`;
- otherwise require `type(node)` in `ALLOWED_FUNCTION_NAMES`;
- reject `exp.Anonymous` and every unmapped subclass;
- do not compare raw SQL text or accept prefixes.

For this task, call the function check after structural AST validation. Task 5
moves the call behind successful table/column validation so the final runtime
order matches the main specification.

- [ ] **Step 6: Run function and structural regressions**

Run:

```bash
.venv/bin/python -m pytest \
  tests/unit/test_sql_validator_functions.py \
  tests/unit/test_sql_validator_structure.py -v
```

Expected: all approved/denied function and structural cases pass.

- [ ] **Step 7: Review checkpoint and commit**

Inspect the SQLGlot 30.13.0 parse tree for `DATE_TRUNC` and `CASE`; confirm the implementation maps `TimestampTrunc` and does not accidentally authorize standalone `IF`.

```bash
git add app/validation tests/unit/test_sql_validator_functions.py
git commit -m "feat: enforce MVP SQL function policy"
```

## Task 4: Authorization-Scoped Base Table Resolution

**Files:**

- Modify: `app/validation/policy.py`
- Modify: `app/validation/sql_validator.py`
- Create: `tests/unit/test_sql_validator_objects.py`

**Interfaces:**

- Consumes: `MetadataScope`, `SchemaSnapshot`, and SQLGlot query scopes.
- Produces: canonical `schema.table` evidence and a copied AST whose base tables have resolved Schema identifiers.

- [ ] **Step 1: Create literal snapshot fixtures**

In `tests/unit/test_sql_validator_objects.py`, define frozen Stage 2 models for:

- `public.film(film_id, title, language_id)`;
- `public.language(language_id, name)`;
- `archive.film(film_id)`.

Use `build_schema_snapshot()` directly. Do not query PostgreSQL in unit tests:

```python
def _table(
    schema_name: str,
    table_name: str,
    columns: tuple[str, ...],
) -> TableMetadata:
    return TableMetadata(
        schema_name=schema_name,
        table_name=table_name,
        relation_kind="table",
        comment=None,
        columns=tuple(
            ColumnMetadata(
                schema_name=schema_name,
                table_name=table_name,
                column_name=column_name,
                ordinal_position=position,
                data_type="text",
                formatted_type="text",
                nullable=False,
                comment=None,
            )
            for position, column_name in enumerate(columns, start=1)
        ),
    )


PUBLIC_SNAPSHOT = build_schema_snapshot(
    tables=(
        _table("public", "film", ("film_id", "title", "language_id")),
        _table("public", "language", ("language_id", "name")),
    ),
    primary_keys=(),
    foreign_keys=(),
    unique_constraints=(),
    unique_indexes=(),
)


def _validate(
    sql: str,
    *,
    allowed_schemas: tuple[str, ...] = ("public",),
    allowed_tables: tuple[str, ...] = (
        "public.film",
        "public.language",
    ),
    snapshot: SchemaSnapshot = PUBLIC_SNAPSHOT,
) -> ValidationResult:
    return validate_sql(
        sql,
        allowed_schemas=allowed_schemas,
        allowed_tables=allowed_tables,
        snapshot=snapshot,
    )
```

Build the cross-Schema snapshot with the same helper and tables
`public.film(film_id)` and `archive.film(film_id)`.

- [ ] **Step 2: Write failing authorized-source tests**

Add:

```python
def test_resolves_one_unqualified_authorized_table() -> None:
    result = _validate(
        "SELECT f.film_id FROM film AS f",
        allowed_schemas=("public",),
        allowed_tables=("public.film",),
        snapshot=PUBLIC_SNAPSHOT,
    )

    assert result.is_valid
    assert result.referenced_tables == ("public.film",)


def test_cte_name_is_not_checked_as_a_database_table() -> None:
    result = _validate(
        "WITH selected AS (SELECT film_id FROM film) "
        "SELECT film_id FROM selected",
        allowed_schemas=("public",),
        allowed_tables=("public.film",),
        snapshot=PUBLIC_SNAPSHOT,
    )

    assert result.is_valid
    assert result.referenced_tables == ("public.film",)
```

Add a derived-table version:

```python
SELECT picked.film_id
FROM (SELECT film_id FROM film) AS picked
```

Expected referenced table remains only `public.film`.

- [ ] **Step 3: Write failing denied/ambiguous-source tests**

Cover exact codes:

```python
@pytest.mark.parametrize(
    ("sql", "code"),
    [
        ("SELECT staff_id FROM staff", "SQL_OBJECT_NOT_ALLOWED"),
        ("SELECT film_id FROM other.film", "SQL_OBJECT_NOT_ALLOWED"),
        (
            "SELECT film_id FROM catalog.public.film",
            "SQL_OBJECT_NOT_ALLOWED",
        ),
    ],
)
def test_rejects_sources_outside_authorization(sql: str, code: str) -> None:
    assert _validate_public(sql).issue.code == code
```

For both `public.film` and `archive.film` authorized, unqualified `film` must return
`SCHEMA_ERROR / SQL_OBJECT_AMBIGUOUS`; `archive.film` must pass when explicitly
qualified. For `public.missing` authorized but absent from the snapshot, return
`SCHEMA_ERROR / SQL_OBJECT_UNKNOWN`.

Add a case-sensitive table fixture `public.CamelCase(id)`: quoted
`"public"."CamelCase"` must pass when exactly authorized, while unquoted
`public.CamelCase` folds according to PostgreSQL rules and must not be treated as
the quoted identifier.

- [ ] **Step 4: Run and verify failure**

Run:

```bash
.venv/bin/python -m pytest tests/unit/test_sql_validator_objects.py -v \
  -k "table or source or authorization or ambiguous or unknown"
```

Expected: object tests fail because base tables are not resolved or authorized.

- [ ] **Step 5: Add object/context issues**

In `policy.py`, add:

```python
CONTEXT_INVALID = ValidationIssue(
    ErrorType.UNKNOWN,
    "SQL_VALIDATION_CONTEXT_INVALID",
    "The SQL validation context is invalid.",
)
OBJECT_NOT_ALLOWED = ValidationIssue(
    ErrorType.PERMISSION_DENIED,
    "SQL_OBJECT_NOT_ALLOWED",
    "The SQL statement references an object that is not permitted.",
)
OBJECT_AMBIGUOUS = ValidationIssue(
    ErrorType.SCHEMA_ERROR,
    "SQL_OBJECT_AMBIGUOUS",
    "The SQL statement contains an ambiguous database object.",
)
OBJECT_UNKNOWN = ValidationIssue(
    ErrorType.SCHEMA_ERROR,
    "SQL_OBJECT_UNKNOWN",
    "The SQL statement references an invalid database object.",
)
```

- [ ] **Step 6: Implement context and base-table resolution**

Use `normalize_metadata_scope()` and `traverse_scope()`:

```python
scope = normalize_metadata_scope(allowed_schemas, allowed_tables)
authorized = set(scope.table_pairs)
snapshot_tables = {
    (table.schema_name, table.table_name)
    for table in snapshot.tables
}
if not snapshot_tables.issubset(authorized):
    return failure_result(CONTEXT_INVALID)
```

Create the working copy with:

```python
resolved_expression = normalize_identifiers(
    expression.copy(),
    dialect="postgres",
)
```

Import `normalize_identifiers` from
`sqlglot.optimizer.normalize_identifiers`. This applies PostgreSQL lowercase
folding only to unquoted identifiers and preserves quoted identifier case.

On `resolved_expression`, traverse every SQLGlot scope and inspect
`query_scope.sources.values()`:

- skip values that are SQLGlot `Scope`;
- process values that are `exp.Table`;
- reject non-empty `table.catalog`;
- resolve explicit `table.db` exactly;
- resolve unqualified `table.name` against authorized pairs;
- set missing `db` with `exp.to_identifier(resolved_schema)`;
- collect canonical table names;
- require the resolved pair in `snapshot_tables`.

Deduplicate the same base `Table` object by identity so correlated scope traversal cannot double-count it.

Import `Scope` and `traverse_scope` from `sqlglot.optimizer.scope`; never infer
CTE status from an alias string.

- [ ] **Step 7: Add context mismatch test**

Pass `PUBLIC_SNAPSHOT` with an empty authorization scope and assert:

```python
assert result.issue.error_type is ErrorType.UNKNOWN
assert result.issue.code == "SQL_VALIDATION_CONTEXT_INVALID"
assert "film" not in result.issue.public_message.lower()
```

- [ ] **Step 8: Run object and earlier tests**

Run:

```bash
.venv/bin/python -m pytest \
  tests/unit/test_sql_validator_objects.py \
  tests/unit/test_sql_validator_structure.py \
  tests/unit/test_sql_validator_functions.py -v
```

Expected: table authorization tests and earlier safety tests pass.

- [ ] **Step 9: Review checkpoint and commit**

Confirm CTE/derived sources are represented by `Scope`, never matched by name against the database allowlist, and no database call occurs.

```bash
git add app/validation tests/unit/test_sql_validator_objects.py
git commit -m "feat: authorize SQL base table scopes"
```

## Task 5: Column Qualification and Canonical Evidence

**Files:**

- Modify: `app/validation/policy.py`
- Modify: `app/validation/sql_validator.py`
- Modify: `tests/unit/test_sql_validator_objects.py`

**Interfaces:**

- Consumes: the resolved AST copy and Stage 2 table/column metadata.
- Produces: field validation plus canonical `schema.table.column` evidence.

- [ ] **Step 1: Write failing valid-column tests**

Add tests for:

- `SELECT film_id, title FROM film`;
- `SELECT f.film_id, l.name FROM film f JOIN language l ON ...`;
- a CTE that exposes `film_id`;
- a derived table that exposes `film_id`;
- the correlated query:

```sql
SELECT c.customer_id
FROM customer AS c
WHERE NOT EXISTS (
    SELECT 1
    FROM rental AS r
    WHERE r.customer_id = c.customer_id
)
```

The correlated fixture snapshot must include
`public.customer(customer_id)` and `public.rental(customer_id)`.

Assert exact sorted base references, for example:

```python
assert result.referenced_columns == (
    "public.customer.customer_id",
    "public.rental.customer_id",
)
```

- [ ] **Step 2: Write failing invalid-column tests**

Cover:

- unknown `film.film_name`;
- unknown unqualified `film_name`;
- unqualified `language_id` when both joined tables expose it;
- CTE outer reference to a column the CTE did not select;
- derived-table outer reference to a missing output column.

Every case must return:

```python
ErrorType.SCHEMA_ERROR
code == "SQL_COLUMN_INVALID"
```

and the public message must contain none of the identifiers.

- [ ] **Step 3: Run and verify failure**

Run:

```bash
.venv/bin/python -m pytest tests/unit/test_sql_validator_objects.py -v \
  -k "column or cte or derived or correlated"
```

Expected: missing/ambiguous fields pass incorrectly or no canonical field evidence is returned.

- [ ] **Step 4: Add the field issue**

In `policy.py`:

```python
COLUMN_INVALID = ValidationIssue(
    ErrorType.SCHEMA_ERROR,
    "SQL_COLUMN_INVALID",
    "The SQL statement references an invalid or ambiguous field.",
)
```

- [ ] **Step 5: Build SQLGlot schema only from the snapshot**

Create:

```python
def _schema_mapping(snapshot: SchemaSnapshot) -> dict[str, object]:
    return {
        schema_name: {
            table.table_name: {
                column.column_name: column.formatted_type
                for column in table.columns
            }
            for table in snapshot.tables
            if table.schema_name == schema_name
        }
        for schema_name in snapshot.schemas
    }
```

Do not infer fields from SQL aliases, allowed table strings, or database queries.

- [ ] **Step 6: Qualify on the resolved AST copy**

Import `qualify` from `sqlglot.optimizer.qualify` and `OptimizeError` from
`sqlglot.errors`.

Call:

```python
qualified = qualify(
    resolved_expression,
    dialect="postgres",
    schema=_schema_mapping(snapshot),
    expand_stars=False,
    infer_schema=False,
    validate_qualify_columns=True,
    quote_identifiers=False,
    identify=False,
    sql=None,
)
```

Catch only `OptimizeError` as `COLUMN_INVALID`. Do not expose its message.

- [ ] **Step 7: Extract base-column evidence**

Traverse qualified scopes. For each `scope.columns` item:

- ignore an unqualified literal/output alias;
- find `scope.sources[column.table]`;
- if the source is `exp.Table`, use its resolved Schema/table and the column name;
- if the source is a derived `Scope`, do not record the outer derived reference;
- allow correlated outer columns to be recorded by the owning outer scope;
- deduplicate and sort through `success_result()`.

After qualification and reference extraction succeed, invoke the function policy
from Task 3. This is the final runtime position of function validation.

Before returning success, serialize the original validated expression—not the qualified rewrite—with:

```python
expression.sql(
    dialect="postgres",
    unsupported_level=ErrorLevel.RAISE,
)
```

This preserves query semantics and aliases while still providing qualification evidence.

- [ ] **Step 8: Run all validation unit tests**

Run:

```bash
.venv/bin/python -m pytest \
  tests/unit/test_validation_models.py \
  tests/unit/test_sql_validator_structure.py \
  tests/unit/test_sql_validator_functions.py \
  tests/unit/test_sql_validator_objects.py -v
.venv/bin/python -m compileall -q app tests
```

Expected: all parser, structure, function, table, column, CTE, derived, and correlated tests pass.

- [ ] **Step 9: Review checkpoint and commit**

Confirm qualification receives only snapshot metadata, the AST returned by the parser is not mutated before normalized SQL is produced, and failed results expose no partial references.

```bash
git add app/validation tests/unit/test_sql_validator_objects.py
git commit -m "feat: validate SQL fields and references"
```

## Task 6: P0 Security Matrix and Live Pagila Contract

**Files:**

- Create: `tests/security/test_sql_validator_security.py`
- Create: `tests/integration/test_pagila_sql_validation.py`
- Modify: validator files only for test-proven defects

**Interfaces:**

- Consumes: complete Stage 3 validator, Stage 2 Connector, and read-only Pagila Case file.
- Produces: evidence for P0 AST/security and Pagila SQL validation.

- [ ] **Step 1: Add the complete security rejection matrix**

In `tests/security/test_sql_validator_security.py`, use exact
`(sql, error_type, code)` cases:

```python
[
    ("SELECT (", ErrorType.SYNTAX_ERROR, "SQL_PARSE_ERROR"),
    (
        "SELECT 1; SELECT 2",
        ErrorType.PERMISSION_DENIED,
        "SQL_MULTIPLE_STATEMENTS",
    ),
    (
        "INSERT INTO film(film_id) VALUES (1)",
        ErrorType.PERMISSION_DENIED,
        "SQL_NOT_READ_ONLY",
    ),
    (
        "UPDATE film SET title = 'x'",
        ErrorType.PERMISSION_DENIED,
        "SQL_NOT_READ_ONLY",
    ),
    ("DELETE FROM film", ErrorType.PERMISSION_DENIED, "SQL_NOT_READ_ONLY"),
    (
        "MERGE INTO film USING language ON true WHEN MATCHED THEN DELETE",
        ErrorType.PERMISSION_DENIED,
        "SQL_NOT_READ_ONLY",
    ),
    (
        "CREATE TABLE unsafe(id int)",
        ErrorType.PERMISSION_DENIED,
        "SQL_NOT_READ_ONLY",
    ),
    (
        "ALTER TABLE film ADD COLUMN unsafe int",
        ErrorType.PERMISSION_DENIED,
        "SQL_NOT_READ_ONLY",
    ),
    ("DROP TABLE film", ErrorType.PERMISSION_DENIED, "SQL_NOT_READ_ONLY"),
    (
        "TRUNCATE TABLE film",
        ErrorType.PERMISSION_DENIED,
        "SQL_NOT_READ_ONLY",
    ),
    ("COPY film TO STDOUT", ErrorType.PERMISSION_DENIED, "SQL_NOT_READ_ONLY"),
    ("CALL unsafe()", ErrorType.PERMISSION_DENIED, "SQL_NOT_READ_ONLY"),
    (
        "DO $$ BEGIN END $$",
        ErrorType.PERMISSION_DENIED,
        "SQL_NOT_READ_ONLY",
    ),
    (
        "SET search_path TO public",
        ErrorType.PERMISSION_DENIED,
        "SQL_NOT_READ_ONLY",
    ),
    (
        "RESET search_path",
        ErrorType.PERMISSION_DENIED,
        "SQL_NOT_READ_ONLY",
    ),
    (
        (
            "WITH changed AS (DELETE FROM film RETURNING film_id) "
            "SELECT film_id FROM changed"
        ),
        ErrorType.PERMISSION_DENIED,
        "SQL_FORBIDDEN_NODE",
    ),
    (
        "SELECT film_id INTO backup FROM film",
        ErrorType.PERMISSION_DENIED,
        "SQL_FORBIDDEN_NODE",
    ),
    (
        "SELECT film_id FROM film FOR UPDATE",
        ErrorType.PERMISSION_DENIED,
        "SQL_FORBIDDEN_NODE",
    ),
    (
        "SELECT film_id FROM film FOR SHARE",
        ErrorType.PERMISSION_DENIED,
        "SQL_FORBIDDEN_NODE",
    ),
    (
        "SELECT * FROM film",
        ErrorType.PERMISSION_DENIED,
        "SQL_WILDCARD_FORBIDDEN",
    ),
    (
        "SELECT staff_id FROM staff",
        ErrorType.PERMISSION_DENIED,
        "SQL_OBJECT_NOT_ALLOWED",
    ),
    (
        "SELECT pg_sleep(1)",
        ErrorType.PERMISSION_DENIED,
        "SQL_FUNCTION_NOT_ALLOWED",
    ),
    (
        "SELECT pg_read_file('/tmp/x')",
        ErrorType.PERMISSION_DENIED,
        "SQL_FUNCTION_NOT_ALLOWED",
    ),
    (
        "SELECT dblink('x', 'y')",
        ErrorType.PERMISSION_DENIED,
        "SQL_FUNCTION_NOT_ALLOWED",
    ),
    (
        "SELECT custom_udf(film_id) FROM film",
        ErrorType.PERMISSION_DENIED,
        "SQL_FUNCTION_NOT_ALLOWED",
    ),
]
```

For every failure assert:

- `is_valid is False`;
- `normalized_sql is None`;
- referenced tuples are empty;
- issue type/code match the expected security or syntax category;
- `repr(result)` contains no submitted SQL;
- public message contains no fixture object/function names.

- [ ] **Step 2: Run security tests and fix only observed defects**

Run:

```bash
.venv/bin/python -m pytest tests/security/test_sql_validator_security.py -v
```

Expected: all P0 dangerous SQL cases fail closed.

- [ ] **Step 3: Add Pagila Case integration helpers**

Load each JSONL object without editing it. Convert Case tables using:

```python
allowed_tables = tuple(
    f"public.{table_name}"
    for table_name in case["allowed_tables"]
)
snapshot = connector.read_metadata(("public",), allowed_tables)
```

Do not load `gold_tables` into authorization, prompt, policy, or snapshot scope.

- [ ] **Step 4: Validate all approved Pagila Gold SQL**

For `PG-MVP-001` through `PG-MVP-014` and `PG-MVP-018`:

- validate non-empty `gold_sql`;
- assert success;
- assert referenced tables are a subset of `allowed_tables`;
- assert every referenced field exists in the snapshot;
- assert no Connector `execute()` call is made by validator code.

The test may use the real Connector only for `read_metadata()`.

- [ ] **Step 5: Validate Pagila security fixtures**

Assert:

- `PG-MVP-016.fixture.model_sql` returns `PERMISSION_DENIED`;
- `PG-MVP-017.fixture.model_sql` returns `SQL_MULTIPLE_STATEMENTS`;
- with only `public.film` authorized,
  `SELECT username, email FROM staff` returns `SQL_OBJECT_NOT_ALLOWED`;
- each failed result has no SQL or references.

- [ ] **Step 6: Run Stage 3 live tests**

Start the existing pinned Pagila service without deleting its named volume, then run:

```bash
.venv/bin/python -m pytest \
  tests/integration/test_pagila_sql_validation.py -v -m integration
```

Expected: all 15 allowed Gold SQL cases and 3 permission/dangerous cases meet the validator contract.

- [ ] **Step 7: Run first- and second-stage regressions**

Run:

```bash
.venv/bin/python -m pytest tests/unit -v
.venv/bin/python -m pytest tests/security -v
.venv/bin/python -m pytest tests/integration -v -m integration
```

Expected: every Stage 1–3 unit, security, and PostgreSQL/Pagila integration test passes.

- [ ] **Step 8: Dependency and leakage review**

Run:

```bash
.venv/bin/python -m pip check
rg -n \
  'postgresql://[^[:space:]]+:[^[:space:]]+@|SQL_PARSE_ERROR.*SELECT|pg_sleep.*public_message' \
  app docs/decisions README.md \
  --glob '!tests/**'
```

Expected: dependency check exits 0; no usable DSN or SQL/object leakage appears.

- [ ] **Step 9: Review checkpoint and commit**

Review every P0 allowed/rejected item from test specification section 5 against a named test.

```bash
git add app/validation tests/security tests/integration/test_pagila_sql_validation.py
git commit -m "test: prove SQLGlot safety contract"
```

## Task 7: Stage 3 Decision Record and Final Verification

**Files:**

- Create: `docs/decisions/0003-sqlglot-safety-policy.md`
- Modify: `README.md`

**Interfaces:**

- Consumes: verified implementation and test output from Tasks 1–6.
- Produces: reproducible Stage 3 usage, policy/version decisions, evidence, and Stage 4 exclusions.

- [ ] **Step 1: Write ADR 0003**

Record:

- why SQLGlot AST fail-closed was selected over regex or database trial;
- exact SQLGlot version and upgrade rule;
- validation order;
- root/CTE rule and forbidden node types;
- AST unknown-node behavior;
- `SELECT *` versus `COUNT(*)`;
- authorization versus snapshot existence semantics;
- CTE/derived/correlated resolution;
- full `mvp-v1` function list and `TimestampTrunc`/`Case` handling;
- error type/code routing and safe-message rule;
- unit, security, and Pagila verification counts;
- explicit Stage 4 Schema Linking exclusion.

- [ ] **Step 2: Update README**

Add a successful example:

```python
result = validate_sql(
    "SELECT film_id, title FROM film",
    allowed_schemas=("public",),
    allowed_tables=("public.film",),
    snapshot=snapshot,
)
if result.is_valid:
    connector.execute(result.normalized_sql)
```

Explain that only trusted server authorization and the matching snapshot may be
passed, and callers must never execute when `is_valid` is false.

- [ ] **Step 3: Run deterministic verification**

Run fresh:

```bash
.venv/bin/python -m pytest tests/unit -v
.venv/bin/python -m pytest tests/security -v
.venv/bin/python -m compileall -q app tools tests
.venv/bin/python -m pip check
docker compose -f infrastructure/pagila/compose.yaml config --quiet
.venv/bin/python -m pytest tests/integration -v -m integration
git diff --check
```

Expected: all commands exit 0 with no failures or warnings attributable to project code.

- [ ] **Step 4: Verify protected artifacts**

Before implementation and at completion, compare:

```bash
shasum -a 256 \
  docs/Text-to-SQL项目复现规格.md \
  docs/Text-to-SQL测试与验收规格.md \
  evaluation/cases/pagila_mvp.jsonl
```

Expected hashes:

```text
191f702f0bf78706ce6bf0ac09bca98bbc096c6d45ff06696887da7484ba513b
299e306461faeacbd40c208a7020b45a3e67545e54e7ee575549760a05a0a181
049e048b821e949936c1793d441f7adcda4660f10f8d0acf63e4f766a9726c22
```

- [ ] **Step 5: Audit Stage 3 scope**

Run:

```bash
find app -maxdepth 3 -type f -print | sort
rg -n 'BM25|top_k|GenerateSQL|LangGraph|FastAPI|connector\\.execute' \
  app/validation
```

Expected: only Connector/config, Stage 2 metadata, and Stage 3 validation production modules exist; no later-stage implementation or execution call appears.

- [ ] **Step 6: Stop PostgreSQL without deleting data**

Run:

```bash
docker compose -f infrastructure/pagila/compose.yaml down
```

Expected: container and network stop while `text-to-sql-pagila_pagila-data` remains.

- [ ] **Step 7: Final review checkpoint**

Produce a Stage 3 report containing:

- dependency version;
- unit/security/integration counts;
- allowed SQL shape evidence;
- dangerous/multi-statement/lock/INTO evidence;
- authorization and field-resolution evidence;
- function default-deny evidence;
- failure-message leakage evidence;
- protected file hashes;
- Stage 4 exclusions and environment limitations.

Suggested commit:

```bash
git add README.md docs/decisions/0003-sqlglot-safety-policy.md
git commit -m "docs: record SQLGlot safety policy"
```

## Execution Order and Stop Conditions

Execute Tasks 1 through 7 in order only after explicit user authorization to start Stage 3 coding. Stop and report before changing this design if:

- SQLGlot 30.13.0 does not represent a required PostgreSQL construct with the audited AST shape;
- qualification cannot distinguish base tables from CTE/derived sources without trusting SQL text;
- a Pagila Gold SQL requires a function or AST node outside the approved main-spec allowlist;
- an allowed correlated subquery cannot be validated without disabling column checks;
- public-safe classification would require exposing an unauthorized object or SQLGlot error;
- a required action would modify one of the three protected specification/Case files.
