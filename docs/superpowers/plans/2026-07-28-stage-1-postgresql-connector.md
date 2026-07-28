# Stage 1 Pagila and PostgreSQL Connector Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a reproducible PostgreSQL 16.14 + Pagila environment and a tested psycopg 3 connector that performs bounded, read-only execution with normalized results and errors.

**Architecture:** A small Pydantic settings object validates one Pagila datasource. A synchronous `PostgreSQLConnector` owns one psycopg connection pool, executes each SQL string in a database-enforced read-only transaction, and returns driver-independent result models or a normalized connector exception. Docker Compose initializes a checksum-verified Pagila snapshot and a separate read-only application role.

**Tech Stack:** Python 3.12, psycopg 3.3.4, psycopg-pool 3.3.1, pydantic-settings 2.14.2, pytest 9.1.1, Docker Compose 5, PostgreSQL 16.14.

## Global Constraints

- Read `AGENTS.md`, the main specification's `# MVP 编码入口`, sections 6, 10, 13, 15–17, and test specification sections 1, 6, 10–11 before execution.
- PostgreSQL is exactly `postgres:16.14-bookworm@sha256:92620daddcd947f8d5ab5ba66e848702fe443d87fed30c4cea8e389fd78dfc55`.
- Pagila is commit `fef9675714cfba1756df4719b5e36075a7ddf90e` from `https://github.com/devrimgunduz/pagila`.
- Pagila archive SHA-256 is `6d0cf172e5d1896b5a279452060fb4cf9b2ca820366c712156fa1e656af4df88`.
- `pagila-schema.sql` SHA-256 is `8ce358e4c8014087b85296694a0893887bd7a4190e3ce407f2721b86b98e5707`.
- `pagila-data.sql` SHA-256 is `fb81bec377687c83e11d2a24916ae28656d85550bf0ada798305bf7e2af9823b`.
- Database credentials come only from environment variables; code, committed configuration, exceptions, and logs never contain usable credentials.
- Connector defaults are a 30-second PostgreSQL `statement_timeout` and 1000 returned rows, with one extra row read only to compute `truncated`.
- Only SQLSTATE class `08` connection failures retry the same Connector call. Authentication, permission, pool timeout, SQL, resource, and query timeout failures do not retry.
- Schema introspection belongs to Stage 2 and must not be added here.
- Do not modify `docs/Text-to-SQL项目复现规格.md`, `docs/Text-to-SQL测试与验收规格.md`, or `evaluation/cases/pagila_mvp.jsonl`.
- Execute this plan on an isolated `codex/` branch in the existing Git repository. Use each task's suggested commit only after its verification checkpoint passes.

---

## File Map

| Path | Responsibility |
|---|---|
| `pyproject.toml` | Python version, exact direct dependencies, pytest configuration |
| `.gitignore` | Local environment, Python artifacts, downloaded Pagila SQL, database state |
| `.env.example` | Credential variable names with empty values and safe non-secret defaults |
| `app/config.py` | Validated database settings and secret-safe DSN access |
| `app/connectors/models.py` | Driver-independent result and column models |
| `app/connectors/errors.py` | Error types, stable SQLSTATE mapping, public-safe connector exception |
| `app/connectors/postgresql.py` | Pool lifecycle, connection test, read-only execution, retry boundary |
| `infrastructure/pagila/manifest.json` | Machine-readable locked Pagila source and hashes |
| `tools/__init__.py` | Makes the fixture utility importable in unit tests |
| `tools/fetch_pagila.py` | Download and verify only the two required Pagila SQL files |
| `infrastructure/pagila/compose.yaml` | Pinned PostgreSQL service and initialization mounts |
| `infrastructure/pagila/init/03-create-readonly-role.sh` | Read-only application role and grants |
| `tests/unit/test_config.py` | Settings validation and secret redaction |
| `tests/unit/test_connector_models.py` | Value normalization and bounded result construction |
| `tests/unit/test_connector_errors.py` | SQLSTATE mapping, retry flags, and message redaction |
| `tests/unit/test_pagila_fixture.py` | Offline archive and SQL checksum verification |
| `tests/unit/test_postgresql_connector.py` | Retry loop and pool lifecycle with test doubles |
| `tests/integration/conftest.py` | Required live Pagila settings fixture |
| `tests/integration/test_postgresql_connector.py` | Stage 1 live Connector contract |
| `docs/decisions/0001-pagila-postgresql-baseline.md` | Version lock, checksums, roles, and verification evidence |
| `README.md` | Local bootstrap, test, and teardown commands |

## Task 1: Project Foundation and Validated Database Settings

**Files:**

- Create: `pyproject.toml`
- Create: `.gitignore`
- Create: `.env.example`
- Create: `app/__init__.py`
- Create: `app/config.py`
- Create: `tests/unit/test_config.py`

**Interfaces:**

- Consumes: environment variables with prefix `TEXT_TO_SQL_DATABASE_`.
- Produces: `DatabaseSettings`, `DatabaseSettings.dsn_value`, and `load_database_settings(env_file: Path | None = None) -> DatabaseSettings`.

- [x] **Step 1: Add the minimal package and dependency configuration**

Use this dependency set in `pyproject.toml`:

```toml
[build-system]
requires = ["setuptools>=75"]
build-backend = "setuptools.build_meta"

[project]
name = "text-to-sql-agent"
version = "0.1.0"
requires-python = ">=3.12,<3.15"
dependencies = [
  "psycopg[binary]==3.3.4",
  "psycopg-pool==3.3.1",
  "pydantic-settings==2.14.2",
]

[project.optional-dependencies]
test = ["pytest==9.1.1"]

[tool.pytest.ini_options]
testpaths = ["tests"]
markers = [
  "integration: requires the pinned PostgreSQL/Pagila service",
]
```

Create `app/__init__.py`. Ignore `.venv/`, `.env`, Python caches, pytest caches,
coverage output, and `tests/fixtures/pagila/upstream/`. Do not ignore the three
protected specification files.

- [x] **Step 2: Write failing configuration tests**

Create tests for a valid DSN, a missing DSN, malformed PostgreSQL conninfo, non-positive pool settings, `min_pool_size > max_pool_size`, and secret-safe `repr`.

```python
import pytest
from pydantic import ValidationError

from app.config import DatabaseSettings


def test_database_settings_load_valid_pagila_dsn() -> None:
    settings = DatabaseSettings(
        dsn="postgresql://reader:secret@127.0.0.1:55432/pagila"
    )

    assert settings.datasource_id == "pagila"
    assert settings.statement_timeout_seconds == 30
    assert settings.max_result_rows == 1000
    assert settings.dsn_value.endswith("/pagila")
    assert "secret" not in repr(settings)


def test_database_settings_reject_inverted_pool_bounds() -> None:
    with pytest.raises(ValidationError):
        DatabaseSettings(
            dsn="postgresql://reader:secret@127.0.0.1:55432/pagila",
            min_pool_size=3,
            max_pool_size=2,
        )
```

- [x] **Step 3: Run the test and verify the expected failure**

Run:

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e '.[test]'
.venv/bin/pytest tests/unit/test_config.py -v
```

Expected before implementation: collection fails with `ModuleNotFoundError: No module named 'app.config'`.

- [x] **Step 4: Implement strict settings**

Implement the following shape in `app/config.py`:

```python
from pathlib import Path
from typing import Self

from psycopg.conninfo import conninfo_to_dict
from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class DatabaseSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="TEXT_TO_SQL_DATABASE_",
        extra="ignore",
    )

    datasource_id: str = "pagila"
    dsn: SecretStr
    min_pool_size: int = Field(default=1, ge=1)
    max_pool_size: int = Field(default=4, ge=1)
    pool_timeout_seconds: float = Field(default=5.0, gt=0)
    statement_timeout_seconds: int = Field(default=30, ge=1, le=30)
    max_result_rows: int = Field(default=1000, ge=1, le=1000)
    connection_retry_count: int = Field(default=1, ge=0, le=3)

    @property
    def dsn_value(self) -> str:
        return self.dsn.get_secret_value()

    @model_validator(mode="after")
    def validate_database(self) -> Self:
        if self.min_pool_size > self.max_pool_size:
            raise ValueError("min_pool_size cannot exceed max_pool_size")
        conninfo = conninfo_to_dict(self.dsn_value)
        if conninfo.get("dbname") != "pagila":
            raise ValueError("Stage 1 datasource must use the pagila database")
        return self


def load_database_settings(
    env_file: Path | None = None,
) -> DatabaseSettings:
    return DatabaseSettings(_env_file=env_file)
```

Catch the psycopg conninfo parsing exception in the validator and raise one
stable `ValueError("dsn must be valid PostgreSQL conninfo")` without echoing input.

`.env.example` must contain variable names and empty credential fields:

```dotenv
PAGILA_POSTGRES_PASSWORD=
PAGILA_APP_USER=text_to_sql_reader
PAGILA_APP_PASSWORD=
PAGILA_HOST_PORT=55432
TEXT_TO_SQL_DATABASE_DATASOURCE_ID=pagila
TEXT_TO_SQL_DATABASE_DSN=
TEXT_TO_SQL_DATABASE_MIN_POOL_SIZE=1
TEXT_TO_SQL_DATABASE_MAX_POOL_SIZE=4
TEXT_TO_SQL_DATABASE_POOL_TIMEOUT_SECONDS=5
TEXT_TO_SQL_DATABASE_STATEMENT_TIMEOUT_SECONDS=30
TEXT_TO_SQL_DATABASE_MAX_RESULT_ROWS=1000
TEXT_TO_SQL_DATABASE_CONNECTION_RETRY_COUNT=1
```

- [x] **Step 5: Run the focused tests**

Run:

```bash
.venv/bin/pytest tests/unit/test_config.py -v
```

Expected: all settings tests pass and no assertion output contains a password.

- [x] **Step 6: Review checkpoint**

Check:

```bash
rg -n "secret@|password *= *['\"]|api[_-]?key" app pyproject.toml .env.example
```

Expected: only test fixtures use the literal word `secret`; no usable credential is committed.

Suggested commit after this task's verification passes:

```bash
git add pyproject.toml .gitignore .env.example app/__init__.py app/config.py tests/unit/test_config.py
git commit -m "chore: bootstrap validated database configuration"
```

## Task 2: Driver-Independent Results and Error Normalization

**Files:**

- Create: `app/connectors/__init__.py`
- Create: `app/connectors/models.py`
- Create: `app/connectors/errors.py`
- Create: `tests/unit/test_connector_models.py`
- Create: `tests/unit/test_connector_errors.py`

**Interfaces:**

- Consumes: psycopg exceptions, pool exceptions, PostgreSQL values and cursor metadata.
- Produces: `ResultColumn`, `ExecutionResult`, `normalize_value(value)`, `ErrorType`, `DatabaseError`, `PostgreSQLConnectorError`, and `normalize_database_error(error)`.

- [x] **Step 1: Write failing result normalization tests**

Cover `None`, booleans, integers, floats, strings, `Decimal`, `date`, `time`,
naive and aware `datetime`, UUID, enum values, dictionaries, arrays, and nested combinations.

```python
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from app.connectors.models import normalize_value


def test_normalize_value_preserves_json_precision_and_timezone() -> None:
    value = {
        "amount": Decimal("10.20"),
        "at": datetime(2026, 7, 28, 8, 30, tzinfo=timezone.utc),
        "id": UUID("12345678-1234-5678-1234-567812345678"),
        "items": [None, Decimal("0.01")],
    }

    assert normalize_value(value) == {
        "amount": "10.20",
        "at": "2026-07-28T08:30:00+00:00",
        "id": "12345678-1234-5678-1234-567812345678",
        "items": [None, "0.01"],
    }
```

- [x] **Step 2: Write failing SQLSTATE mapping and redaction tests**

Parameterize the required mapping:

```python
import pytest

from app.connectors.errors import ErrorType, classify_sqlstate


@pytest.mark.parametrize(
    ("sqlstate", "expected"),
    [
        ("42601", ErrorType.SYNTAX_ERROR),
        ("42P01", ErrorType.SCHEMA_ERROR),
        ("42703", ErrorType.SCHEMA_ERROR),
        ("42702", ErrorType.SCHEMA_ERROR),
        ("42501", ErrorType.PERMISSION_DENIED),
        ("25006", ErrorType.PERMISSION_DENIED),
        ("28P01", ErrorType.PERMISSION_DENIED),
        ("08006", ErrorType.CONNECTION_ERROR),
        ("57014", ErrorType.TIMEOUT),
        ("53000", ErrorType.RESOURCE_RISK),
        ("XX000", ErrorType.UNKNOWN),
    ],
)
def test_classify_sqlstate(sqlstate: str, expected: ErrorType) -> None:
    assert classify_sqlstate(sqlstate) is expected
```

Build one fake exception with a `sqlstate` attribute and a message containing a DSN/password.
Assert the normalized public message and `repr` contain neither sensitive substring.

- [x] **Step 3: Run tests and verify they fail**

Run:

```bash
.venv/bin/pytest tests/unit/test_connector_models.py tests/unit/test_connector_errors.py -v
```

Expected before implementation: collection fails because `app.connectors` does not exist.

- [x] **Step 4: Implement result models and recursive normalization**

Use immutable column metadata and a mutable list-of-lists response compatible with the future API:

```python
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
from enum import Enum
from typing import TypeAlias
from uuid import UUID

JsonValue: TypeAlias = (
    None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
)


@dataclass(frozen=True, slots=True)
class ResultColumn:
    name: str
    type_oid: int


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    columns: tuple[ResultColumn, ...]
    rows: list[list[JsonValue]]
    returned_row_count: int
    truncated: bool
    execution_time_ms: float
```

`normalize_value()` must recurse through mappings, lists, and tuples. Convert
`Decimal` with `str()`, temporal values with `isoformat()`, UUID with `str()`,
and enum instances through their `.value`. Preserve already valid JSON primitives.
Raise `TypeError("unsupported PostgreSQL result type: <type name>")` for unsupported
objects without including the value.

- [x] **Step 5: Implement stable errors**

Define every `ErrorType` value from main specification section 6. Use this public-safe shape:

```python
@dataclass(frozen=True, slots=True)
class DatabaseError:
    sqlstate: str | None
    error_type: ErrorType
    code: str
    retryable: bool
    public_message: str


class PostgreSQLConnectorError(RuntimeError):
    def __init__(self, details: DatabaseError) -> None:
        super().__init__(details.public_message)
        self.details = details
```

Use constant public messages and stable codes:

| ErrorType | Code | Public message |
|---|---|---|
| `SYNTAX_ERROR` | `DB_SYNTAX_ERROR` | `The SQL syntax is invalid.` |
| `SCHEMA_ERROR` | `DB_SCHEMA_ERROR` | `The SQL references an invalid database object.` |
| `PERMISSION_DENIED` | `DB_PERMISSION_DENIED` | `The database operation is not permitted.` |
| `CONNECTION_ERROR` | `DB_CONNECTION_ERROR` | `The database connection failed.` |
| `TIMEOUT` | `DB_TIMEOUT` | `The database query timed out.` |
| `RESOURCE_RISK` | `DB_RESOURCE_RISK` | `The database rejected the query for resource safety.` |
| `UNKNOWN` | `DB_UNKNOWN` | `The database operation failed.` |

Only SQLSTATE class `08` and a psycopg `OperationalError` without SQLSTATE are
retryable. `PoolTimeout`, `28P01`, `42501`, `25006`, `57014`, and class `53`
are never retryable.

- [x] **Step 6: Run the focused tests**

Run:

```bash
.venv/bin/pytest tests/unit/test_connector_models.py tests/unit/test_connector_errors.py -v
```

Expected: all normalization, mapping, retryability, and redaction tests pass.

- [x] **Step 7: Review checkpoint**

Run:

```bash
.venv/bin/python -m compileall -q app
```

Expected: exit code 0.

Suggested commit after this task's verification passes:

```bash
git add app/connectors tests/unit/test_connector_models.py tests/unit/test_connector_errors.py
git commit -m "feat: add connector result and error contracts"
```

## Task 3: Verified Pagila Fixture Acquisition

**Files:**

- Create: `infrastructure/pagila/manifest.json`
- Create: `tools/__init__.py`
- Create: `tools/fetch_pagila.py`
- Create: `tests/unit/test_pagila_fixture.py`
- Modify: `.gitignore`

**Interfaces:**

- Consumes: a locked GitHub archive URL and SHA-256 manifest.
- Produces: `load_manifest(path)`, `extract_verified_archive(archive_path, target_dir, manifest)`, `fetch_pagila(manifest_path, target_dir)`, and verified local files under `tests/fixtures/pagila/upstream/`.

- [x] **Step 1: Write offline failing tests for the fixture tool**

Build a small tar.gz inside pytest's `tmp_path` with two members using the exact
archive member naming convention. Test:

- valid archive and member hashes write both files;
- archive hash mismatch writes nothing;
- member hash mismatch writes nothing;
- a missing member writes nothing;
- an existing valid target is reused;
- an existing corrupt target is replaced only after full verification.

Core assertion:

```python
outputs = extract_verified_archive(archive_path, output_dir, manifest)

assert outputs.schema.read_bytes() == schema_bytes
assert outputs.data.read_bytes() == data_bytes
assert not list(output_dir.glob("*.tmp"))
```

- [x] **Step 2: Run the fixture tests and verify failure**

Run:

```bash
.venv/bin/pytest tests/unit/test_pagila_fixture.py -v
```

Expected before implementation: import fails for `tools.fetch_pagila`.

- [x] **Step 3: Add the exact machine-readable manifest**

Use:

```json
{
  "source": "https://github.com/devrimgunduz/pagila",
  "tag": "pagila-v3.1.0",
  "commit": "fef9675714cfba1756df4719b5e36075a7ddf90e",
  "archive_url": "https://github.com/devrimgunduz/pagila/archive/fef9675714cfba1756df4719b5e36075a7ddf90e.tar.gz",
  "archive_sha256": "6d0cf172e5d1896b5a279452060fb4cf9b2ca820366c712156fa1e656af4df88",
  "files": {
    "pagila-schema.sql": {
      "member": "pagila-fef9675714cfba1756df4719b5e36075a7ddf90e/pagila-schema.sql",
      "sha256": "8ce358e4c8014087b85296694a0893887bd7a4190e3ce407f2721b86b98e5707"
    },
    "pagila-data.sql": {
      "member": "pagila-fef9675714cfba1756df4719b5e36075a7ddf90e/pagila-data.sql",
      "sha256": "fb81bec377687c83e11d2a24916ae28656d85550bf0ada798305bf7e2af9823b"
    }
  }
}
```

- [x] **Step 4: Implement safe download and extraction**

The tool must:

1. load and validate all manifest keys;
2. download into a temporary file in the target directory;
3. verify archive SHA-256 before opening it;
4. call `TarFile.extractfile()` only for the two exact members;
5. verify both member hashes in memory or temporary files;
6. atomically replace final files only after both pass;
7. remove temporary files in `finally`;
8. print only source/version/path information, never environment values.

Expose this data shape:

```python
@dataclass(frozen=True, slots=True)
class PagilaFiles:
    schema: Path
    data: Path
```

CLI behavior:

```bash
.venv/bin/python tools/fetch_pagila.py \
  --manifest infrastructure/pagila/manifest.json \
  --output tests/fixtures/pagila/upstream
```

- [x] **Step 5: Run offline unit tests**

Run:

```bash
.venv/bin/pytest tests/unit/test_pagila_fixture.py -v
```

Expected: all tests pass without network access.

- [x] **Step 6: Fetch the real locked fixture and verify hashes**

Run the CLI command from Step 4, then:

```bash
shasum -a 256 \
  tests/fixtures/pagila/upstream/pagila-schema.sql \
  tests/fixtures/pagila/upstream/pagila-data.sql
```

Expected:

```text
8ce358e4c8014087b85296694a0893887bd7a4190e3ce407f2721b86b98e5707  tests/fixtures/pagila/upstream/pagila-schema.sql
fb81bec377687c83e11d2a24916ae28656d85550bf0ada798305bf7e2af9823b  tests/fixtures/pagila/upstream/pagila-data.sql
```

- [x] **Step 7: Review checkpoint**

Run:

```bash
find tests/fixtures/pagila/upstream -maxdepth 1 -type f -print
```

Expected: only the two ignored SQL files are present.

Suggested commit after this task's verification passes:

```bash
git add .gitignore infrastructure/pagila/manifest.json tools/__init__.py tools/fetch_pagila.py tests/unit/test_pagila_fixture.py
git commit -m "build: lock and verify Pagila fixture"
```

## Task 4: PostgreSQL 16.14 Compose Environment and Read-Only Role

**Files:**

- Create: `infrastructure/pagila/compose.yaml`
- Create: `infrastructure/pagila/init/03-create-readonly-role.sh`

**Interfaces:**

- Consumes: verified fixture files and `PAGILA_POSTGRES_PASSWORD`, `PAGILA_APP_USER`, `PAGILA_APP_PASSWORD`, `PAGILA_HOST_PORT`.
- Produces: a healthy `pagila-postgres` service with the Pagila schema/data and a login role whose default transactions are read-only.

- [x] **Step 1: Establish the failing infrastructure checks**

Run:

```bash
docker compose -f infrastructure/pagila/compose.yaml config
```

Expected before implementation: failure because the Compose file does not exist.

- [x] **Step 2: Add pinned Compose configuration**

The database service must use:

```yaml
name: text-to-sql-pagila

services:
  postgres:
    image: postgres:16.14-bookworm@sha256:92620daddcd947f8d5ab5ba66e848702fe443d87fed30c4cea8e389fd78dfc55
    container_name: text-to-sql-pagila-postgres
    environment:
      POSTGRES_DB: pagila
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: ${PAGILA_POSTGRES_PASSWORD:?PAGILA_POSTGRES_PASSWORD is required}
      PAGILA_APP_USER: ${PAGILA_APP_USER:?PAGILA_APP_USER is required}
      PAGILA_APP_PASSWORD: ${PAGILA_APP_PASSWORD:?PAGILA_APP_PASSWORD is required}
    ports:
      - "${PAGILA_HOST_PORT:-55432}:5432"
    volumes:
      - pagila-data:/var/lib/postgresql/data
      - ../../tests/fixtures/pagila/upstream/pagila-schema.sql:/docker-entrypoint-initdb.d/01-pagila-schema.sql:ro
      - ../../tests/fixtures/pagila/upstream/pagila-data.sql:/docker-entrypoint-initdb.d/02-pagila-data.sql:ro
      - ./init/03-create-readonly-role.sh:/docker-entrypoint-initdb.d/03-create-readonly-role.sh:ro
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U $$POSTGRES_USER -d $$POSTGRES_DB"]
      interval: 2s
      timeout: 5s
      retries: 30
      start_period: 10s

volumes:
  pagila-data:
```

- [x] **Step 3: Add the idempotent role initialization script**

The executable shell script must run `psql --set ON_ERROR_STOP=1`, pass both role
values through psql variables, use `format('%I', ...)` for identifiers and
`format('%L', ...)` for the password, and execute these effective statements:

```sql
CREATE ROLE <app role> LOGIN;
ALTER ROLE <app role> PASSWORD <environment password>;
ALTER ROLE <app role> SET default_transaction_read_only = on;
GRANT CONNECT ON DATABASE pagila TO <app role>;
GRANT USAGE ON SCHEMA public TO <app role>;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO <app role>;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT ON TABLES TO <app role>;
```

The create statement must be guarded by `pg_roles` so rerunning the script does
not fail. Run:

```bash
chmod +x infrastructure/pagila/init/03-create-readonly-role.sh
```

- [x] **Step 4: Render Compose with ephemeral local-only secrets**

Keep the following environment variables in the same terminal session:

```bash
export PAGILA_POSTGRES_PASSWORD="$(openssl rand -hex 24)"
export PAGILA_APP_USER="text_to_sql_reader"
export PAGILA_APP_PASSWORD="$(openssl rand -hex 24)"
export PAGILA_HOST_PORT="55432"
export TEXT_TO_SQL_DATABASE_DSN="postgresql://${PAGILA_APP_USER}:${PAGILA_APP_PASSWORD}@127.0.0.1:${PAGILA_HOST_PORT}/pagila"
```

Then run:

```bash
docker compose -f infrastructure/pagila/compose.yaml config --quiet
```

Expected: exit code 0 and no environment value printed.

- [x] **Step 5: Initialize PostgreSQL and Pagila**

Run:

```bash
docker compose -f infrastructure/pagila/compose.yaml up -d --wait
```

Expected: service becomes healthy without changing the pinned image or Pagila files.

- [x] **Step 6: Prove the fixed versions, dataset, and role**

Run:

```bash
docker compose -f infrastructure/pagila/compose.yaml exec -T postgres \
  psql -U postgres -d pagila -Atc "SHOW server_version; SELECT COUNT(*) FROM film;"
docker compose -f infrastructure/pagila/compose.yaml exec -T postgres \
  psql -U "${PAGILA_APP_USER}" -d pagila -Atc \
  "SHOW default_transaction_read_only; SELECT COUNT(*) FROM film;"
```

Expected:

- server version begins with `16.14`;
- film count is `1000`;
- the application role reports `on`;
- the application role can read `film`.

- [x] **Step 7: Prove database-side write rejection**

Run:

```bash
docker compose -f infrastructure/pagila/compose.yaml exec -T postgres \
  psql -v ON_ERROR_STOP=1 -U "${PAGILA_APP_USER}" -d pagila \
  -c "INSERT INTO actor(first_name, last_name) VALUES ('SHOULD', 'FAIL');"
```

Expected: non-zero exit with insufficient privilege or read-only transaction; the actor count does not change.

- [x] **Step 8: Review checkpoint**

Run:

```bash
docker compose -f infrastructure/pagila/compose.yaml ps
docker image inspect \
  'postgres:16.14-bookworm@sha256:92620daddcd947f8d5ab5ba66e848702fe443d87fed30c4cea8e389fd78dfc55' \
  --format '{{index .RepoDigests 0}}'
```

Expected: the service is healthy and the digest is the locked PostgreSQL image digest.

Suggested commit after this task's verification passes:

```bash
git add infrastructure/pagila/compose.yaml infrastructure/pagila/init/03-create-readonly-role.sh
git commit -m "build: add pinned Pagila PostgreSQL environment"
```

## Task 5: Connection Pool, Health Check, and Bounded Read-Only Execution

**Files:**

- Create: `app/connectors/postgresql.py`
- Create: `tests/unit/test_postgresql_connector.py`
- Create: `tests/integration/conftest.py`
- Create: `tests/integration/test_postgresql_connector.py`

**Interfaces:**

- Consumes: `DatabaseSettings`, psycopg `ConnectionPool`, SQL text.
- Produces: `PostgreSQLConnector.open()`, `.close()`, `.check_connection()`, `.execute(sql: str) -> ExecutionResult`, and context-manager support.

- [x] **Step 1: Write failing unit tests for lifecycle and the exact SQL retry boundary**

Use a test double pool to assert:

- the pool is created closed;
- `open()` performs a connection check before opening the pool;
- `close()` is idempotent;
- context manager entry opens and exit closes;
- `execute()` passes the identical SQL string to `_execute_once()` on retry.

Core retry assertion:

```python
sql = "SELECT film_id FROM film"
connector._execute_once = Mock(
    side_effect=[
        psycopg.OperationalError("server closed unexpectedly"),
        expected_result,
    ]
)

assert connector.execute(sql) is expected_result
assert connector._execute_once.call_args_list == [call(sql), call(sql)]
```

- [x] **Step 2: Write the first live integration tests**

`tests/integration/conftest.py` must fail with a clear message if
`TEXT_TO_SQL_DATABASE_DSN` is absent; live tests must not silently skip.

Add tests for:

```python
@pytest.mark.integration
def test_pagila_select(connector: PostgreSQLConnector) -> None:
    result = connector.execute(
        "SELECT film_id, title, rental_rate FROM film ORDER BY film_id LIMIT 3"
    )

    assert [column.name for column in result.columns] == [
        "film_id",
        "title",
        "rental_rate",
    ]
    assert result.returned_row_count == 3
    assert result.truncated is False
    assert result.rows[0][0] == 1
```

Also add CTE, aggregation, and empty-result tests.

- [x] **Step 3: Run tests and verify failure**

Run:

```bash
.venv/bin/pytest tests/unit/test_postgresql_connector.py -v
.venv/bin/pytest tests/integration/test_postgresql_connector.py -v
```

Expected before implementation: import fails for `app.connectors.postgresql`.

- [x] **Step 4: Implement lazy pool lifecycle and connection test**

Use a synchronous `psycopg_pool.ConnectionPool` with `open=False`, the exact
settings bounds, and `kwargs={"autocommit": False}`. `check_connection()` must
use a direct `psycopg.connect()` call so authentication SQLSTATE `28P01` is not
lost behind a pool wait timeout:

```python
def check_connection(self) -> None:
    try:
        with psycopg.connect(
            self._settings.dsn_value,
            connect_timeout=max(1, int(self._settings.pool_timeout_seconds)),
        ) as connection:
            connection.execute("SELECT 1")
    except Exception as error:
        raise normalize_database_error(error) from None
```

`open()` calls `check_connection()`, opens the pool, and waits up to
`pool_timeout_seconds`. Convert pool startup errors through the same normalizer.

- [x] **Step 5: Implement one bounded read-only execution**

`_execute_once(sql)` must:

```python
with self._pool.connection() as connection:
    with connection.transaction():
        connection.execute("SET TRANSACTION READ ONLY")
        connection.execute(
            "SELECT set_config('statement_timeout', %s, true)",
            (f"{self._settings.statement_timeout_seconds}s",),
        )
        started = time.perf_counter()
        cursor = connection.execute(sql)
        raw_rows = cursor.fetchmany(self._settings.max_result_rows + 1)
```

If `cursor.description is None`, raise a public-safe `UNKNOWN` connector error;
this stage never invents an empty result for a non-result statement.

Build columns from `description.name` and `description.type_code`, set
`truncated = len(raw_rows) > max_result_rows`, slice before normalization,
and calculate `execution_time_ms` using `time.perf_counter()`.

- [x] **Step 6: Implement the public retry loop**

`execute(sql)` calls `_execute_once(sql)`, normalizes any driver/pool exception,
and retries only when `details.retryable` is true and fewer than
`connection_retry_count` retries have occurred. It does not alter SQL or sleep.

If `_execute_once()` already raised `PostgreSQLConnectorError`, preserve its
details rather than normalizing it again.

- [x] **Step 7: Run focused unit and live tests**

Run:

```bash
.venv/bin/pytest tests/unit/test_postgresql_connector.py -v
.venv/bin/pytest tests/integration/test_postgresql_connector.py \
  -v -k 'select or cte or aggregation or empty'
```

Expected: all selected tests pass.

- [x] **Step 8: Review checkpoint**

Run:

```bash
.venv/bin/python -m compileall -q app tests
```

Expected: exit code 0.

Suggested commit after this task's verification passes:

```bash
git add app/connectors/postgresql.py tests/unit/test_postgresql_connector.py tests/integration
git commit -m "feat: execute bounded read-only PostgreSQL queries"
```

## Task 6: Timeout, Truncation, Types, Error Paths, and Retry Proofs

**Files:**

- Modify: `tests/unit/test_postgresql_connector.py`
- Modify: `tests/integration/test_postgresql_connector.py`
- Modify: `app/connectors/postgresql.py`
- Modify: `app/connectors/errors.py`

**Interfaces:**

- Consumes: the Task 5 Connector interface.
- Produces: complete Stage 1 execution behavior for timeout, connection safety, pool exhaustion, type normalization, and error routing.

- [x] **Step 1: Add failing truncation and type integration tests**

Add:

```python
@pytest.mark.integration
def test_result_limit_reads_one_extra_row(
    connector: PostgreSQLConnector,
) -> None:
    result = connector.execute("SELECT n FROM generate_series(1, 1001) AS n")

    assert result.returned_row_count == 1000
    assert len(result.rows) == 1000
    assert result.rows[-1] == [1000]
    assert result.truncated is True
```

Use one PostgreSQL query containing `NULL`, `numeric`, `date`, `time`,
`timestamptz`, `jsonb`, UUID, and an array. Assert the exact normalized JSON values.

- [x] **Step 2: Add failing timeout and connection reuse integration tests**

Create settings identical to the session settings except
`statement_timeout_seconds=1`, then:

```python
with PostgreSQLConnector(timeout_settings) as timeout_connector:
    with pytest.raises(PostgreSQLConnectorError) as caught:
        timeout_connector.execute("SELECT pg_sleep(2)")
    assert caught.value.details.error_type is ErrorType.TIMEOUT
    assert caught.value.details.sqlstate == "57014"

    recovery = timeout_connector.execute("SELECT 1")
    assert recovery.rows == [[1]]
```

This proves PostgreSQL canceled the query and the pool returned a usable
connection after transaction rollback. If the recovery query fails because the
driver cannot restore the connection, assert through a pool counter that the
old connection was discarded and a new connection was created.

- [x] **Step 3: Add failing write, authentication, refusal, and pool timeout tests**

Required assertions:

- `INSERT INTO actor(...)` returns `PERMISSION_DENIED` with SQLSTATE `25006` or `42501`;
- wrong password in `check_connection()` returns `PERMISSION_DENIED`, SQLSTATE `28P01`, and `retryable=False`;
- an unused localhost port returns `CONNECTION_ERROR` and never leaks conninfo;
- exhausting a one-connection pool returns `CONNECTION_ERROR` with `retryable=False`;
- actor count is unchanged after the write test.

- [x] **Step 4: Add deterministic unit tests for retry counts**

Parameterize zero, one, and three configured retries. Assert:

- class `08` succeeds after the configured number of failures;
- class `08` stops after the budget;
- syntax, schema, permission, timeout, resource, unknown, authentication, and
  pool timeout errors call `_execute_once()` exactly once;
- every retry receives the exact original SQL string.

- [x] **Step 5: Run the new tests and observe precise failures**

Run:

```bash
.venv/bin/pytest tests/unit/test_postgresql_connector.py -v
.venv/bin/pytest tests/integration/test_postgresql_connector.py \
  -v -k 'limit or type or timeout or write or authentication or refused or pool'
```

Expected: new tests fail only where Connector behavior is still missing; existing
Task 5 tests remain green.

- [x] **Step 6: Make the smallest Connector corrections**

Keep changes inside `postgresql.py` and `errors.py`:

- ensure pool acquisition `PoolTimeout` maps to non-retryable connection failure;
- ensure `28P01` and `25006` map to non-retryable permission failure;
- let the transaction context roll back query cancellation before pool return;
- if psycopg marks a connection broken, close it so the pool replaces it;
- normalize only the first 1000 rows after reading row 1001;
- preserve constant public messages for every failure.

Do not add client-side HTTP timeout behavior, SQL rewriting, schema validation, or
workflow counters.

- [x] **Step 7: Run the full Stage 1 test suites**

Run:

```bash
.venv/bin/pytest tests/unit -v
.venv/bin/pytest tests/integration -v -m integration
```

Expected: both commands pass. Timeout tests finish in a few seconds by overriding
the validated setting to one second; production default remains 30 seconds.

- [x] **Step 8: Review checkpoint**

Run:

```bash
docker compose -f infrastructure/pagila/compose.yaml exec -T postgres \
  psql -U postgres -d pagila -Atc \
  "SELECT COUNT(*) FROM pg_stat_activity WHERE datname = 'pagila' AND state = 'active' AND pid <> pg_backend_pid() AND query LIKE '%pg_sleep%';"
```

Expected: `0`.

Suggested commit after this task's verification passes:

```bash
git add app/connectors tests/unit/test_postgresql_connector.py tests/integration/test_postgresql_connector.py
git commit -m "test: complete stage one connector contract"
```

## Task 7: Baseline Documentation and Final Stage Verification

**Files:**

- Create: `docs/decisions/0001-pagila-postgresql-baseline.md`
- Create: `README.md`

**Interfaces:**

- Consumes: verified implementation and test outputs from Tasks 1–6.
- Produces: reproducible developer instructions and an explicit statement of Stage 1 completion versus Stage 2 exclusions.

- [x] **Step 1: Write the baseline decision record**

Record:

- PostgreSQL image tag and multi-architecture digest;
- Pagila source, tag, commit, archive SHA-256, schema SHA-256, and data SHA-256;
- why `pagila-data.sql` is used instead of `pagila-insert-data.sql`;
- administrator versus read-only role responsibilities;
- Python and direct dependency versions;
- the exact Connector defaults and SQLSTATE mapping table;
- successful PostgreSQL version and `film` count evidence;
- that Schema introspection and the remaining Connector Contract metadata tests are Stage 2.

- [x] **Step 2: Write runnable README instructions**

Document this order:

1. create Python 3.12 environment and install `.[test]`;
2. fetch and verify Pagila;
3. export ephemeral local-only database credentials;
4. start Compose and wait for health;
5. export `TEXT_TO_SQL_DATABASE_DSN`;
6. run unit tests;
7. run integration tests;
8. stop Compose without deleting data;
9. optionally delete the named development volume only after an explicit user decision.

Do not document a destructive volume deletion as part of the normal teardown command.

- [x] **Step 3: Run all deterministic checks**

Run:

```bash
.venv/bin/pytest tests/unit -v
.venv/bin/python -m compileall -q app tools tests
docker compose -f infrastructure/pagila/compose.yaml config --quiet
.venv/bin/pytest tests/integration -v -m integration
```

Expected: every command exits 0.

- [x] **Step 4: Verify protected files are byte-for-byte unchanged**

Run:

```bash
shasum -a 256 \
  docs/Text-to-SQL项目复现规格.md \
  docs/Text-to-SQL测试与验收规格.md \
  evaluation/cases/pagila_mvp.jsonl
```

Expected:

```text
191f702f0bf78706ce6bf0ac09bca98bbc096c6d45ff06696887da7484ba513b  docs/Text-to-SQL项目复现规格.md
299e306461faeacbd40c208a7020b45a3e67545e54e7ee575549760a05a0a181  docs/Text-to-SQL测试与验收规格.md
049e048b821e949936c1793d441f7adcda4660f10f8d0acf63e4f766a9726c22  evaluation/cases/pagila_mvp.jsonl
```

- [x] **Step 5: Audit scope and secret safety**

Run:

```bash
rg -n 'postgresql://[^[:space:]]+:[^[:space:]]+@|PAGILA_.*PASSWORD=.+|TEXT_TO_SQL_DATABASE_DSN=.+' \
  --glob '!tests/**' \
  --glob '!.env'
find app -maxdepth 3 -type f -print | sort
```

Expected:

- the credential scan finds no usable secret;
- `app/` contains only configuration and connector files;
- no Schema Linking, SQL generation, validation, workflow, or API module exists.

- [x] **Step 6: Stop the service without deleting the named volume**

Run:

```bash
docker compose -f infrastructure/pagila/compose.yaml down
```

Expected: containers and network stop; the named Pagila data volume remains recoverable.

- [x] **Step 7: Final review checkpoint**

Produce a Stage 1 report with:

- unit test count and result;
- integration test count and result;
- PostgreSQL/Pagila version evidence;
- timeout/cancellation proof;
- read-only write rejection proof;
- 1000-row truncation proof;
- explicit Stage 2 metadata exclusions;
- any environment-specific limitation.

Suggested commit after this task's verification passes:

```bash
git add README.md docs/decisions/0001-pagila-postgresql-baseline.md
git commit -m "docs: record stage one Pagila baseline"
```

## Execution Order and Stop Conditions

Execute Tasks 1 through 7 in order. Stop and report before changing the selected
baseline only if:

- Pagila commit `fef9675714cfba1756df4719b5e36075a7ddf90e` cannot initialize on PostgreSQL 16.14;
- psycopg 3.3.4 or psycopg-pool 3.3.1 has an irreconcilable conflict with Python 3.12;
- PostgreSQL cannot prove cancellation or safe connection disposal after timeout;
- the database cannot enforce read-only behavior for the application role;
- a required action would modify one of the three protected specification/Case files.
