from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from text_to_sql_demo.config.models import DatabaseConnectionConfig, SqliteDiscoveryConfig


@dataclass(frozen=True)
class DiscoveredSQLiteDatabase:
    """自动发现到的本地 SQLite 数据库预设。"""

    preset_id: str
    display_name: str
    database_url: str
    path: Path
    read_only: bool


def discover_sqlite_databases(
    config: SqliteDiscoveryConfig,
    *,
    configured_sqlite_paths: set[Path] | None = None,
    reserved_preset_ids: set[str] | None = None,
    cwd: Path | None = None,
) -> list[DiscoveredSQLiteDatabase]:
    """扫描本地目录，生成可给前端选择的 SQLite 预设。"""
    if not config.enabled:
        return []

    directory = _resolve_path(config.directory, cwd=cwd)
    if not directory.exists() or not directory.is_dir():
        return []

    configured_paths = {
        _normalize_path(path)
        for path in (configured_sqlite_paths or set())
    }
    excluded_names = set(config.exclude_files)
    used_ids = set(reserved_preset_ids or set())
    discovered: list[DiscoveredSQLiteDatabase] = []

    for database_path in sorted(directory.iterdir(), key=lambda item: item.name.lower()):
        if not _is_discoverable_db_file(database_path, excluded_names):
            continue

        normalized_path = _normalize_path(database_path)
        if normalized_path in configured_paths:
            continue

        preset_id = _unique_preset_id(database_path.stem, used_ids)
        used_ids.add(preset_id)
        discovered.append(
            DiscoveredSQLiteDatabase(
                preset_id=preset_id,
                display_name=database_path.name,
                database_url=f"sqlite:///{normalized_path}",
                path=normalized_path,
                read_only=config.read_only,
            )
        )

    return discovered


def configured_sqlite_paths(
    connections: dict[str, DatabaseConnectionConfig],
    *,
    cwd: Path | None = None,
) -> set[Path]:
    """提取 workflow 中已经声明的 SQLite 文件路径，用于自动发现去重。"""
    paths: set[Path] = set()
    for connection in connections.values():
        if connection.driver != "sqlite":
            continue

        if connection.url_env:
            env_value = os.getenv(connection.url_env)
            if env_value:
                path = sqlite_path_from_url(env_value, cwd=cwd)
                if path is not None:
                    paths.add(path)

        if connection.fallback_url:
            path = sqlite_path_from_url(connection.fallback_url, cwd=cwd)
            if path is not None:
                paths.add(path)

    return paths


def sqlite_path_from_url(database_url: str, *, cwd: Path | None = None) -> Path | None:
    """从 sqlite:/// URL 中解析本地路径；非本地 SQLite URL 返回 None。"""
    prefix = "sqlite:///"
    if not database_url.startswith(prefix) or database_url == "sqlite:///:memory:":
        return None

    raw_path = database_url.removeprefix(prefix)
    return _resolve_path(raw_path, cwd=cwd)


def _is_discoverable_db_file(path: Path, excluded_names: set[str]) -> bool:
    return (
        path.is_file()
        and path.suffix.lower() == ".db"
        and not path.name.startswith(".")
        and path.name not in excluded_names
    )


def _resolve_path(path_value: str | Path, *, cwd: Path | None = None) -> Path:
    path = Path(path_value)
    if not path.is_absolute():
        path = (cwd or Path.cwd()) / path
    return _normalize_path(path)


def _normalize_path(path: Path) -> Path:
    return path.expanduser().resolve(strict=False)


def _unique_preset_id(stem: str, used_ids: set[str]) -> str:
    slug = re.sub(r"[^0-9a-zA-Z]+", "_", stem).strip("_").lower() or "database"
    base_id = f"sqlite_file_{slug}"
    preset_id = base_id
    index = 2
    while preset_id in used_ids:
        preset_id = f"{base_id}_{index}"
        index += 1
    return preset_id
