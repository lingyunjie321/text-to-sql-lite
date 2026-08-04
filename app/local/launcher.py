"""Local FastAPI and Next.js process orchestration."""

from __future__ import annotations

import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import time
import webbrowser
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol
from urllib.request import urlopen

from app.config import default_profile_database_path


class LaunchError(RuntimeError):
    """A safe, actionable local-launch failure."""


class ChildProcessExit(LaunchError):
    """A child process exited before both services became ready."""

    def __init__(self, message: str, *, exit_code: int) -> None:
        super().__init__(message)
        self.exit_code = exit_code


class ChildProcess(Protocol):
    pid: int

    def poll(self) -> int | None: ...

    def terminate(self) -> None: ...

    def kill(self) -> None: ...

    def wait(self, timeout: float | None = None) -> int: ...


ProcessFactory = Callable[..., ChildProcess]
BackendProbe = Callable[[str, float], bool]
FrontendProbe = Callable[[str, int, float], bool]


def _default_project_root() -> Path:
    return Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class LaunchConfig:
    project_root: Path = field(default_factory=_default_project_root)
    local_directory: Path = field(
        default_factory=lambda: default_profile_database_path().parent
    )
    backend_host: str = "127.0.0.1"
    backend_port: int = 8000
    frontend_host: str = "127.0.0.1"
    frontend_port: int = 3000
    startup_timeout_seconds: float = 60.0
    shutdown_timeout_seconds: float = 5.0
    open_browser: bool = True


def check_environment(
    config: LaunchConfig,
    *,
    python_version: tuple[int, int] | Sequence[int] | None = None,
    which: Callable[[str], str | None] | None = None,
    node_version: Callable[[str], str] | None = None,
) -> None:
    """Fail before spawning when the local runtime is incomplete."""

    active_python = tuple(python_version or sys.version_info[:2])
    find_command = which or shutil.which
    if active_python < (3, 12):
        raise LaunchError("需要 Python 3.12 或更高版本。")
    commands: dict[str, str] = {}
    for command in ("node", "npm"):
        path = find_command(command)
        if path is None:
            raise LaunchError(f"缺少 {command}，请先安装 Node.js。")
        commands[command] = path

    get_node_version = node_version or _read_node_version
    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", get_node_version(commands["node"]).strip())
    if match is None or tuple(map(int, match.groups())) < (20, 9, 0):
        raise LaunchError("需要 Node.js 20.9.0 或更高版本。")

    frontend = config.project_root / "frontend"
    if not (frontend / "package.json").is_file():
        raise LaunchError("未找到 frontend/package.json，请从仓库根目录安装并启动。")
    if not (frontend / "node_modules" / ".bin" / "next").exists():
        raise LaunchError("前端依赖未安装，请先在 frontend 目录运行 npm install。")


def ensure_local_directory(config: LaunchConfig) -> None:
    """Create the non-secret local application directory."""

    try:
        config.local_directory.mkdir(parents=True, exist_ok=True)
    except OSError:
        raise LaunchError("无法创建本地配置目录，请检查目录权限。") from None


def _read_node_version(node_path: str) -> str:
    try:
        result = subprocess.run(
            [node_path, "--version"],
            capture_output=True,
            check=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        raise LaunchError("无法读取 Node.js 版本，请检查 Node.js 安装。") from None
    return result.stdout


def _spawn_process(
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    start_new_session: bool,
) -> ChildProcess:
    return subprocess.Popen(
        command,
        cwd=cwd,
        env=env,
        start_new_session=start_new_session,
    )


def _signal_process_group(process: ChildProcess, signal_number: int) -> None:
    if os.name == "posix" and process.pid > 0:
        os.killpg(process.pid, signal_number)
    elif signal_number == signal.SIGTERM:
        process.terminate()
    else:
        process.kill()


def _backend_ready(url: str, timeout: float) -> bool:
    try:
        with urlopen(url, timeout=timeout) as response:  # noqa: S310
            return 200 <= response.status < 300
    except OSError:
        return False


def _frontend_ready(host: str, port: int, timeout: float) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


class LocalAppLauncher:
    """Own both local web processes and stop them as one unit."""

    def __init__(
        self,
        config: LaunchConfig,
        *,
        process_factory: ProcessFactory = _spawn_process,
        backend_ready: BackendProbe = _backend_ready,
        frontend_ready: FrontendProbe = _frontend_ready,
        browser_open: Callable[[str], bool] = webbrowser.open,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        environ: Mapping[str, str] | None = None,
    ) -> None:
        self._config = config
        self._process_factory = process_factory
        self._backend_ready = backend_ready
        self._frontend_ready = frontend_ready
        self._browser_open = browser_open
        self._monotonic = monotonic
        self._sleep = sleep
        self._environ = dict(os.environ if environ is None else environ)

    def run(self) -> int:
        check_environment(self._config)
        ensure_local_directory(self._config)
        processes: list[tuple[str, ChildProcess]] = []
        previous_sigterm = self._install_sigterm_handler()
        try:
            backend = self._start_backend()
            processes.append(("后端", backend))
            try:
                frontend = self._start_frontend()
            except OSError:
                raise LaunchError("无法启动前端进程，请检查 npm 和端口配置。") from None
            processes.append(("前端", frontend))
            self._wait_until_ready(processes)
            if self._config.open_browser:
                self._browser_open(self._frontend_url)
            return self._monitor(processes)
        except KeyboardInterrupt:
            return 0
        except OSError:
            raise LaunchError("无法启动后端进程，请检查 Python 环境和端口配置。") from None
        finally:
            self._stop_processes(processes)
            self._restore_sigterm_handler(previous_sigterm)

    @property
    def _backend_url(self) -> str:
        return f"http://{self._config.backend_host}:{self._config.backend_port}"

    @property
    def _frontend_url(self) -> str:
        return f"http://{self._config.frontend_host}:{self._config.frontend_port}"

    def _start_backend(self) -> ChildProcess:
        command = [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            self._config.backend_host,
            "--port",
            str(self._config.backend_port),
            "--lifespan",
            "on",
        ]
        return self._process_factory(
            command,
            cwd=self._config.project_root,
            env=dict(self._environ),
            start_new_session=True,
        )

    def _start_frontend(self) -> ChildProcess:
        command = [
            "npm",
            "run",
            "dev",
            "--",
            "--hostname",
            self._config.frontend_host,
            "--port",
            str(self._config.frontend_port),
        ]
        env = dict(self._environ)
        env["TEXT_TO_SQL_API_URL"] = self._backend_url
        return self._process_factory(
            command,
            cwd=self._config.project_root / "frontend",
            env=env,
            start_new_session=True,
        )

    def _wait_until_ready(
        self,
        processes: list[tuple[str, ChildProcess]],
    ) -> None:
        deadline = self._monotonic() + self._config.startup_timeout_seconds
        while True:
            self._raise_if_exited(processes)
            backend_ok = self._backend_ready(
                f"{self._backend_url}/health",
                0.5,
            )
            frontend_ok = self._frontend_ready(
                self._config.frontend_host,
                self._config.frontend_port,
                0.5,
            )
            if backend_ok and frontend_ok:
                return
            if self._monotonic() >= deadline:
                raise LaunchError("本地服务启动超时，请检查端口占用和服务输出。")
            self._sleep(0.1)

    def _monitor(self, processes: list[tuple[str, ChildProcess]]) -> int:
        while True:
            for _, process in processes:
                exit_code = process.poll()
                if exit_code is not None:
                    return exit_code
            self._sleep(0.2)

    @staticmethod
    def _raise_if_exited(processes: list[tuple[str, ChildProcess]]) -> None:
        for name, process in processes:
            exit_code = process.poll()
            if exit_code is not None:
                raise ChildProcessExit(
                    f"{name}进程在服务就绪前退出，退出码 {exit_code}。",
                    exit_code=exit_code,
                )

    def _stop_processes(
        self,
        processes: list[tuple[str, ChildProcess]],
    ) -> None:
        running: list[ChildProcess] = []
        for _, process in reversed(processes):
            if process.poll() is None:
                try:
                    _signal_process_group(process, signal.SIGTERM)
                except OSError:
                    continue
                else:
                    running.append(process)
        for process in running:
            try:
                process.wait(timeout=self._config.shutdown_timeout_seconds)
            except subprocess.TimeoutExpired:
                try:
                    _signal_process_group(process, signal.SIGKILL)
                except OSError:
                    continue
                process.wait()

    @staticmethod
    def _install_sigterm_handler() -> object | None:
        try:
            previous = signal.getsignal(signal.SIGTERM)

            def stop(signum: int, frame: object) -> None:
                del signum, frame
                raise KeyboardInterrupt

            signal.signal(signal.SIGTERM, stop)
            return previous
        except ValueError:
            return None

    @staticmethod
    def _restore_sigterm_handler(previous: object | None) -> None:
        if previous is None:
            return
        signal.signal(signal.SIGTERM, previous)
