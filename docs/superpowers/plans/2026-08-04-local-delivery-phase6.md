# Local Delivery Phase 6 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship one local command that checks prerequisites, starts and stops the existing FastAPI and Next.js services safely, and provide the required operator/developer documentation.

**Architecture:** `app.local.launcher` owns environment validation, subprocess construction, readiness probing, browser opening, and shutdown. `app.cli` only parses arguments and maps launcher errors to an exit code. Existing ASGI lifespan cleanup remains the sole owner of application resources.

**Tech Stack:** Python 3.12+, Uvicorn, FastAPI, Node.js, npm, Next.js 16, pytest, Vitest.

## Global Constraints

- Work directly on `main`; do not create branches, worktrees, or pull requests.
- Preserve the core Text-to-SQL Workflow and all public API contracts.
- Bind both services to `127.0.0.1` by default.
- Never persist or print API keys, database passwords, or full DSNs.
- Do not stage or push `docs/Text-to-SQL原项目参考信息.md` or the user's existing `AGENTS.md` edit.
- Reuse existing phase 3–5 tests; do not duplicate equivalent coverage.

---

### Task 1: Launcher environment contract

**Files:**
- Create: `app/local/launcher.py`
- Test: `tests/unit/test_local_launcher.py`

**Interfaces:**
- Consumes: repository root, current Python executable, `PATH`, and the default Profile directory contract.
- Produces: `LaunchConfig`, `LaunchError`, `check_environment(config)`, and `ensure_local_directory(config)`.

- [x] **Step 1: Write failing environment tests**

Test that Python below 3.12, missing `node`, missing `npm`, missing `frontend/package.json`, and missing `frontend/node_modules/.bin/next` each raise a sanitized `LaunchError`; test that valid inputs create the configured local directory.

- [x] **Step 2: Run the focused test and confirm the missing module/API failure**

Run: `.venv/bin/pytest -q -p no:cacheprovider tests/unit/test_local_launcher.py`

- [x] **Step 3: Implement the minimal immutable config and environment checks**

Use `dataclass(frozen=True)`, `shutil.which`, and `Path.mkdir(parents=True, exist_ok=True)`. Do not install dependencies automatically.

- [x] **Step 4: Run the focused test to green**

Run: `.venv/bin/pytest -q -p no:cacheprovider tests/unit/test_local_launcher.py`

### Task 2: Process orchestration and graceful shutdown

**Files:**
- Modify: `app/local/launcher.py`
- Modify: `tests/unit/test_local_launcher.py`

**Interfaces:**
- Consumes: `LaunchConfig`, injectable process/browser/readiness functions.
- Produces: `LocalAppLauncher.run() -> int`, deterministic backend/frontend commands, and best-effort two-process cleanup.

- [x] **Step 1: Add failing behavior tests**

Cover backend command construction, frontend `TEXT_TO_SQL_API_URL` injection, readiness-before-browser ordering, `--no-open`, early child exit propagation, graceful terminate, timeout kill, and cleanup when startup probing fails.

- [x] **Step 2: Run the focused test and confirm behavior failures**

Run: `.venv/bin/pytest -q -p no:cacheprovider tests/unit/test_local_launcher.py`

- [x] **Step 3: Implement the smallest orchestration loop**

Start Uvicorn and Next.js with argument lists and explicit working directories. Poll HTTP health and the frontend TCP port with a shared deadline. On any exit path terminate running children, wait briefly, then kill only children still alive.

- [x] **Step 4: Run the focused test to green**

Run: `.venv/bin/pytest -q -p no:cacheprovider tests/unit/test_local_launcher.py`

### Task 3: Installable CLI entry point

**Files:**
- Create: `app/cli.py`
- Modify: `pyproject.toml`
- Create: `tests/unit/test_cli.py`
- Create: `Makefile`

**Interfaces:**
- Consumes: `LocalAppLauncher` and `LaunchConfig`.
- Produces: `text-to-sql-lite start`, optional host/port/timeout flags, `--no-open`, and `make dev` alias.

- [x] **Step 1: Write failing CLI tests**

Assert `start` maps parsed defaults and overrides into `LaunchConfig`, returns the launcher's exit code, prints sanitized `LaunchError` messages to stderr, and rejects unknown commands.

- [x] **Step 2: Run CLI tests and confirm the missing entry point failure**

Run: `.venv/bin/pytest -q -p no:cacheprovider tests/unit/test_cli.py`

- [x] **Step 3: Implement CLI and packaging**

Add `uvicorn==0.52.0` to runtime dependencies and `[project.scripts] text-to-sql-lite = "app.cli:main"`. `Makefile` invokes `.venv/bin/python -m app.cli start` so source development does not depend on editable-install path hooks.

- [x] **Step 4: Install the package and run CLI tests**

Run: `.venv/bin/python -m pip install '.[test]'`

Run: `.venv/bin/pytest -q -p no:cacheprovider tests/unit/test_cli.py tests/unit/test_local_launcher.py`

### Task 4: Delivery documentation and verification

**Files:**
- Modify: `README.md`
- Modify: `RELEASE.md`
- Create: `docs/本地安装与启动.md`
- Create: `docs/添加模型.md`
- Create: `docs/添加数据库.md`
- Create: `docs/架构说明.md`
- Create: `docs/开发交接指南.md`
- Create: `docs/常见问题.md`

**Interfaces:**
- Consumes: actual CLI flags, current Profile/API contracts, existing integration fixtures.
- Produces: one novice entry path plus operator and maintainer references with commands that match the repository.

- [x] **Step 1: Write the seven required documents against actual behavior**

Document installation, first start, model/database Profile semantics, allowlist safety, query path, shutdown, PostgreSQL/MySQL integration commands, test tiers, credential limitations, and troubleshooting. Mark browser data-source setup as a remaining phase 5 slice if it is not present in code.

- [x] **Step 2: Run one targeted verification batch**

Run: `.venv/bin/pytest -q -p no:cacheprovider tests/unit/test_cli.py tests/unit/test_local_launcher.py tests/unit/test_connector_factory.py tests/unit/test_profile_store.py tests/unit/test_runtime_registry.py tests/unit/test_model_runtime_registry.py tests/unit/test_workflow_context_factory.py`

- [x] **Step 3: Run one complete local verification batch**

Run Python unit/security once, then frontend `npm test`, `npm run typecheck`, `npm run lint`, and `npm run build` once each. Do not rerun successful suites unless a subsequent edit can affect them.

- [x] **Step 4: Review scope, commit, and push**

Confirm `origin` is `https://github.com/lingyunjie321/text-to-sql-lite.git`, inspect the staged diff, exclude `AGENTS.md` and the historical reference document, commit to `main`, and run `git push origin main`.
