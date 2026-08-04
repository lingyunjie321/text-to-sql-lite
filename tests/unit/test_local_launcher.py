from __future__ import annotations

import subprocess
import os
import signal
import sys
from pathlib import Path
from typing import Any

import pytest


class _FakeProcess:
    pid = 0

    def __init__(
        self,
        polls: list[int | None] | None = None,
        *,
        wait_times_out: bool = False,
        terminate_error: OSError | None = None,
    ) -> None:
        self._polls = list(polls or [None])
        self._last_poll: int | None = None
        self.wait_times_out = wait_times_out
        self.terminate_error = terminate_error
        self.terminated = False
        self.killed = False
        self.wait_calls: list[float | None] = []

    def poll(self) -> int | None:
        if self._polls:
            self._last_poll = self._polls.pop(0)
        return self._last_poll

    def terminate(self) -> None:
        self.terminated = True
        if self.terminate_error is not None:
            raise self.terminate_error

    def kill(self) -> None:
        self.killed = True

    def wait(self, timeout: float | None = None) -> int:
        self.wait_calls.append(timeout)
        if self.wait_times_out and not self.killed:
            raise subprocess.TimeoutExpired("child", timeout)
        return 0


def _project(tmp_path: Path, *, with_next: bool = True) -> Path:
    root = tmp_path / "project"
    frontend = root / "frontend"
    frontend.mkdir(parents=True)
    (frontend / "package.json").write_text("{}", encoding="utf-8")
    if with_next:
        next_binary = frontend / "node_modules" / ".bin" / "next"
        next_binary.parent.mkdir(parents=True)
        next_binary.write_text("", encoding="utf-8")
    return root


def test_environment_rejects_unsupported_python(tmp_path: Path) -> None:
    from app.local.launcher import LaunchConfig, LaunchError, check_environment

    config = LaunchConfig(project_root=_project(tmp_path))

    with pytest.raises(LaunchError, match="Python 3.12"):
        check_environment(
            config,
            python_version=(3, 11),
            which=lambda name: f"/usr/bin/{name}",
            node_version=lambda path: "v24.0.0",
        )


@pytest.mark.parametrize("missing", ["node", "npm"])
def test_environment_rejects_missing_node_tools(
    tmp_path: Path,
    missing: str,
) -> None:
    from app.local.launcher import LaunchConfig, LaunchError, check_environment

    config = LaunchConfig(project_root=_project(tmp_path))

    with pytest.raises(LaunchError, match=missing):
        check_environment(
            config,
            python_version=(3, 12),
            which=lambda name: None if name == missing else f"/usr/bin/{name}",
            node_version=lambda path: "v24.0.0",
        )


def test_environment_requires_frontend_dependencies(tmp_path: Path) -> None:
    from app.local.launcher import LaunchConfig, LaunchError, check_environment

    config = LaunchConfig(project_root=_project(tmp_path, with_next=False))

    with pytest.raises(LaunchError, match="npm install"):
        check_environment(
            config,
            python_version=(3, 12),
            which=lambda name: f"/usr/bin/{name}",
            node_version=lambda path: "v24.0.0",
        )


def test_environment_requires_frontend_project(tmp_path: Path) -> None:
    from app.local.launcher import LaunchConfig, LaunchError, check_environment

    root = tmp_path / "project"
    root.mkdir()
    config = LaunchConfig(project_root=root)

    with pytest.raises(LaunchError, match="frontend/package.json"):
        check_environment(
            config,
            python_version=(3, 12),
            which=lambda name: f"/usr/bin/{name}",
            node_version=lambda path: "v24.0.0",
        )


@pytest.mark.parametrize("version", ["v18.20.0", "v20.8.9", "invalid"])
def test_environment_rejects_unsupported_node_version(
    tmp_path: Path,
    version: str,
) -> None:
    from app.local.launcher import LaunchConfig, LaunchError, check_environment

    with pytest.raises(LaunchError, match="Node.js 20.9"):
        check_environment(
            LaunchConfig(project_root=_project(tmp_path)),
            python_version=(3, 12),
            which=lambda name: f"/usr/bin/{name}",
            node_version=lambda path: version,
        )


def test_ensure_local_directory_creates_config_parent(tmp_path: Path) -> None:
    from app.local.launcher import LaunchConfig, ensure_local_directory

    local_directory = tmp_path / "local" / "profiles"
    config = LaunchConfig(
        project_root=_project(tmp_path),
        local_directory=local_directory,
    )

    ensure_local_directory(config)

    assert local_directory.is_dir()


def test_ensure_local_directory_hides_filesystem_error(tmp_path: Path) -> None:
    from app.local.launcher import LaunchConfig, LaunchError, ensure_local_directory

    blocked = tmp_path / "private-config-path"
    blocked.write_text("not a directory", encoding="utf-8")

    with pytest.raises(LaunchError) as captured:
        ensure_local_directory(
            LaunchConfig(project_root=_project(tmp_path), local_directory=blocked)
        )

    assert str(blocked) not in str(captured.value)


def test_launcher_builds_commands_injects_backend_url_and_opens_browser(
    tmp_path: Path,
) -> None:
    from app.local.launcher import LaunchConfig, LocalAppLauncher

    root = _project(tmp_path)
    config = LaunchConfig(
        project_root=root,
        local_directory=tmp_path / "local",
        backend_port=8123,
        frontend_port=3456,
        startup_timeout_seconds=2,
    )
    backend = _FakeProcess([None, None, 0])
    frontend = _FakeProcess([None, None, None])
    processes = iter([backend, frontend])
    calls: list[tuple[list[str], Path, dict[str, str]]] = []
    events: list[str] = []

    def spawn(
        command: list[str],
        *,
        cwd: Path,
        env: dict[str, str],
        start_new_session: bool,
    ) -> _FakeProcess:
        assert start_new_session is True
        calls.append((command, cwd, env))
        return next(processes)

    launcher = LocalAppLauncher(
        config,
        process_factory=spawn,
        backend_ready=lambda url, timeout: events.append(f"backend:{url}") or True,
        frontend_ready=lambda host, port, timeout: events.append(
            f"frontend:{host}:{port}"
        )
        or True,
        browser_open=lambda url: events.append(f"browser:{url}") or True,
        sleep=lambda seconds: None,
    )

    assert launcher.run() == 0
    assert calls[0][0][-6:] == [
        "--host",
        "127.0.0.1",
        "--port",
        "8123",
        "--lifespan",
        "on",
    ]
    assert calls[0][1] == root
    assert calls[1][0] == [
        "npm",
        "run",
        "dev",
        "--",
        "--hostname",
        "127.0.0.1",
        "--port",
        "3456",
    ]
    assert calls[1][1] == root / "frontend"
    assert calls[1][2]["TEXT_TO_SQL_API_URL"] == "http://127.0.0.1:8123"
    assert events == [
        "backend:http://127.0.0.1:8123/health",
        "frontend:127.0.0.1:3456",
        "browser:http://127.0.0.1:3456",
    ]
    assert not backend.terminated
    assert frontend.terminated


def test_launcher_no_open_skips_browser(tmp_path: Path) -> None:
    from app.local.launcher import LaunchConfig, LocalAppLauncher

    processes = iter([_FakeProcess([None, 0]), _FakeProcess([None, None])])
    opened: list[str] = []
    launcher = LocalAppLauncher(
        LaunchConfig(
            project_root=_project(tmp_path),
            local_directory=tmp_path / "local",
            open_browser=False,
        ),
        process_factory=lambda command, **kwargs: next(processes),
        backend_ready=lambda url, timeout: True,
        frontend_ready=lambda host, port, timeout: True,
        browser_open=lambda url: opened.append(url) or True,
        sleep=lambda seconds: None,
    )

    assert launcher.run() == 0
    assert opened == []


def test_launcher_propagates_early_child_exit_and_cleans_both(
    tmp_path: Path,
) -> None:
    from app.local.launcher import ChildProcessExit, LaunchConfig, LocalAppLauncher

    backend = _FakeProcess([7])
    frontend = _FakeProcess([None])
    processes = iter([backend, frontend])
    launcher = LocalAppLauncher(
        LaunchConfig(
            project_root=_project(tmp_path),
            local_directory=tmp_path / "local",
        ),
        process_factory=lambda command, **kwargs: next(processes),
        backend_ready=lambda url, timeout: False,
        frontend_ready=lambda host, port, timeout: False,
        sleep=lambda seconds: None,
    )

    with pytest.raises(ChildProcessExit, match="后端进程.*7") as captured:
        launcher.run()

    assert captured.value.exit_code == 7
    assert frontend.terminated


def test_launcher_kills_child_that_ignores_graceful_shutdown(
    tmp_path: Path,
) -> None:
    from app.local.launcher import LaunchConfig, LaunchError, LocalAppLauncher

    backend = _FakeProcess([1])
    frontend = _FakeProcess([None], wait_times_out=True)
    processes = iter([backend, frontend])
    launcher = LocalAppLauncher(
        LaunchConfig(
            project_root=_project(tmp_path),
            local_directory=tmp_path / "local",
            shutdown_timeout_seconds=0.1,
        ),
        process_factory=lambda command, **kwargs: next(processes),
        backend_ready=lambda url, timeout: False,
        frontend_ready=lambda host, port, timeout: False,
        sleep=lambda seconds: None,
    )

    with pytest.raises(LaunchError):
        launcher.run()

    assert frontend.terminated
    assert frontend.killed


def test_launcher_times_out_and_cleans_both_children(tmp_path: Path) -> None:
    from app.local.launcher import LaunchConfig, LaunchError, LocalAppLauncher

    backend = _FakeProcess([None, None])
    frontend = _FakeProcess([None, None])
    processes = iter([backend, frontend])
    clock = iter([0.0, 2.0])
    launcher = LocalAppLauncher(
        LaunchConfig(
            project_root=_project(tmp_path),
            local_directory=tmp_path / "local",
            startup_timeout_seconds=1.0,
        ),
        process_factory=lambda command, **kwargs: next(processes),
        backend_ready=lambda url, timeout: False,
        frontend_ready=lambda host, port, timeout: False,
        monotonic=lambda: next(clock),
        sleep=lambda seconds: None,
    )

    with pytest.raises(LaunchError, match="启动超时"):
        launcher.run()

    assert backend.terminated
    assert frontend.terminated


def test_launcher_cleans_backend_when_frontend_spawn_fails(
    tmp_path: Path,
) -> None:
    from app.local.launcher import LaunchConfig, LaunchError, LocalAppLauncher

    backend = _FakeProcess([None])
    calls = 0

    def spawn(command: list[str], **kwargs: Any) -> _FakeProcess:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("private process error")
        return backend

    launcher = LocalAppLauncher(
        LaunchConfig(
            project_root=_project(tmp_path),
            local_directory=tmp_path / "local",
        ),
        process_factory=spawn,
    )

    with pytest.raises(LaunchError) as captured:
        launcher.run()

    assert "无法启动前端进程" in str(captured.value)
    assert "private" not in str(captured.value)
    assert backend.terminated


def test_launcher_continues_shutdown_when_one_terminate_fails(
    tmp_path: Path,
) -> None:
    from app.local.launcher import LaunchConfig, LaunchError, LocalAppLauncher

    backend = _FakeProcess([1, None])
    frontend = _FakeProcess(
        [None, None],
        terminate_error=ProcessLookupError("already gone"),
    )
    processes = iter([backend, frontend])
    launcher = LocalAppLauncher(
        LaunchConfig(
            project_root=_project(tmp_path),
            local_directory=tmp_path / "local",
        ),
        process_factory=lambda command, **kwargs: next(processes),
        backend_ready=lambda url, timeout: False,
        frontend_ready=lambda host, port, timeout: False,
        sleep=lambda seconds: None,
    )

    with pytest.raises(LaunchError):
        launcher.run()

    assert frontend.terminated
    assert backend.terminated


@pytest.mark.skipif(os.name != "posix", reason="POSIX process groups only")
def test_spawned_process_owns_group_and_group_signal_stops_it() -> None:
    from app.local.launcher import _signal_process_group, _spawn_process

    process = _spawn_process(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        cwd=Path.cwd(),
        env=dict(os.environ),
        start_new_session=True,
    )
    try:
        assert os.getpgid(process.pid) == process.pid
        _signal_process_group(process, signal.SIGTERM)
        assert process.wait(timeout=5) < 0
    finally:
        if process.poll() is None:
            _signal_process_group(process, signal.SIGKILL)
            process.wait(timeout=5)
