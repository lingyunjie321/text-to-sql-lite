from __future__ import annotations

from pathlib import Path


def test_project_root_prefers_active_repository(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from app import cli

    (tmp_path / "pyproject.toml").write_text("", encoding="utf-8")
    (tmp_path / "frontend").mkdir()
    monkeypatch.chdir(tmp_path)

    assert cli.project_root() == tmp_path


def test_start_uses_safe_defaults(monkeypatch, tmp_path: Path) -> None:
    from app import cli

    captured = []

    class _Launcher:
        def __init__(self, config) -> None:
            captured.append(config)

        def run(self) -> int:
            return 0

    monkeypatch.setattr(cli, "LocalAppLauncher", _Launcher)
    monkeypatch.setattr(cli, "project_root", lambda: tmp_path)

    assert cli.main(["start"]) == 0
    config = captured[0]
    assert config.project_root == tmp_path
    assert config.backend_host == "127.0.0.1"
    assert config.backend_port == 8000
    assert config.frontend_host == "127.0.0.1"
    assert config.frontend_port == 3000
    assert config.open_browser is True


def test_start_maps_cli_overrides(monkeypatch, tmp_path: Path) -> None:
    from app import cli

    captured = []

    class _Launcher:
        def __init__(self, config) -> None:
            captured.append(config)

        def run(self) -> int:
            return 9

    monkeypatch.setattr(cli, "LocalAppLauncher", _Launcher)
    monkeypatch.setattr(cli, "project_root", lambda: tmp_path)

    result = cli.main(
        [
            "start",
            "--backend-port",
            "8100",
            "--frontend-port",
            "3100",
            "--startup-timeout",
            "15",
            "--no-open",
        ]
    )

    assert result == 9
    config = captured[0]
    assert config.backend_port == 8100
    assert config.frontend_port == 3100
    assert config.startup_timeout_seconds == 15
    assert config.open_browser is False


def test_start_reports_sanitized_launch_error(
    monkeypatch,
    capsys,
    tmp_path: Path,
) -> None:
    from app import cli
    from app.local.launcher import LaunchError

    class _Launcher:
        def __init__(self, config) -> None:
            del config

        def run(self) -> int:
            raise LaunchError("缺少 npm，请先安装 Node.js。")

    monkeypatch.setattr(cli, "LocalAppLauncher", _Launcher)
    monkeypatch.setattr(cli, "project_root", lambda: tmp_path)

    assert cli.main(["start"]) == 2
    assert capsys.readouterr().err == "启动失败：缺少 npm，请先安装 Node.js。\n"


def test_start_preserves_early_child_exit_code(monkeypatch, capsys, tmp_path: Path) -> None:
    from app import cli
    from app.local.launcher import ChildProcessExit

    class _Launcher:
        def __init__(self, config) -> None:
            del config

        def run(self) -> int:
            raise ChildProcessExit("前端进程退出。", exit_code=9)

    monkeypatch.setattr(cli, "LocalAppLauncher", _Launcher)
    monkeypatch.setattr(cli, "project_root", lambda: tmp_path)

    assert cli.main(["start"]) == 9
    assert capsys.readouterr().err == "启动失败：前端进程退出。\n"
