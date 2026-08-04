"""Command line entry point for the local Text-to-SQL tool."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from app.local.launcher import (
    ChildProcessExit,
    LaunchConfig,
    LaunchError,
    LocalAppLauncher,
)


def project_root() -> Path:
    active_directory = Path.cwd()
    if (
        (active_directory / "pyproject.toml").is_file()
        and (active_directory / "frontend").is_dir()
    ):
        return active_directory
    return Path(__file__).resolve().parents[1]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="text-to-sql-lite")
    subparsers = parser.add_subparsers(dest="command", required=True)
    start = subparsers.add_parser("start", help="启动本地后端和前端")
    start.add_argument("--backend-host", default="127.0.0.1")
    start.add_argument("--backend-port", type=int, default=8000)
    start.add_argument("--frontend-host", default="127.0.0.1")
    start.add_argument("--frontend-port", type=int, default=3000)
    start.add_argument("--startup-timeout", type=float, default=60.0)
    start.add_argument("--no-open", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    config = LaunchConfig(
        project_root=project_root(),
        backend_host=args.backend_host,
        backend_port=args.backend_port,
        frontend_host=args.frontend_host,
        frontend_port=args.frontend_port,
        startup_timeout_seconds=args.startup_timeout,
        open_browser=not args.no_open,
    )
    try:
        return LocalAppLauncher(config).run()
    except ChildProcessExit as error:
        print(f"启动失败：{error}", file=sys.stderr)
        return error.exit_code
    except LaunchError as error:
        print(f"启动失败：{error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
