from __future__ import annotations

import os
from collections.abc import Iterable
from pathlib import Path


def load_env_files(paths: Iterable[str | Path] = (".env.local", ".env")) -> None:
    """加载本地 env 文件，已有环境变量保持优先。"""
    for path in paths:
        env_path = Path(path)
        if not env_path.exists():
            continue

        for raw_line in env_path.read_text(encoding="utf-8").splitlines():
            parsed = _parse_env_line(raw_line)
            if parsed is None:
                continue

            key, value = parsed
            if key not in os.environ:
                os.environ[key] = value


def _parse_env_line(raw_line: str) -> tuple[str, str] | None:
    """解析一行简单 KEY=VALUE 配置。"""
    line = raw_line.strip()
    if not line or line.startswith("#"):
        return None
    if line.startswith("export "):
        line = line.removeprefix("export ").strip()
    if "=" not in line:
        return None

    key, raw_value = line.split("=", 1)
    key = key.strip()
    if not key:
        return None

    value = raw_value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1]
    return key, value
