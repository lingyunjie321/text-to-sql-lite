from pathlib import Path

from text_to_sql_demo.config.models import SqliteDiscoveryConfig
from text_to_sql_demo.runtime.sqlite_discovery import discover_sqlite_databases


def test_discover_sqlite_databases_returns_only_visible_db_files(tmp_path: Path) -> None:
    """自动发现只暴露业务 SQLite 文件，并生成稳定的 preset_id。"""
    (tmp_path / "sales.db").touch()
    (tmp_path / "northwind.db").touch()
    (tmp_path / "metadata.db").touch()
    (tmp_path / ".hidden.db").touch()
    (tmp_path / ".DS_Store").touch()
    (tmp_path / "notes.txt").touch()

    discovered = discover_sqlite_databases(
        SqliteDiscoveryConfig(
            enabled=True,
            directory=str(tmp_path),
            exclude_files=["metadata.db"],
        )
    )

    assert [item.preset_id for item in discovered] == [
        "sqlite_file_northwind",
        "sqlite_file_sales",
    ]
    assert [item.display_name for item in discovered] == ["northwind.db", "sales.db"]
    assert discovered[0].database_url == f"sqlite:///{tmp_path / 'northwind.db'}"
    assert discovered[1].read_only is True


def test_discover_sqlite_databases_skips_configured_paths(tmp_path: Path) -> None:
    """已在 workflow 中配置的 SQLite 文件不应重复出现在自动发现预设里。"""
    demo_path = tmp_path / "demo.db"
    demo_path.touch()
    extra_path = tmp_path / "extra.db"
    extra_path.touch()

    discovered = discover_sqlite_databases(
        SqliteDiscoveryConfig(enabled=True, directory=str(tmp_path)),
        configured_sqlite_paths={demo_path},
    )

    assert [item.preset_id for item in discovered] == ["sqlite_file_extra"]


def test_discover_sqlite_databases_returns_empty_when_disabled(tmp_path: Path) -> None:
    """关闭自动发现后，即使目录中有数据库也不生成预设。"""
    (tmp_path / "sales.db").touch()

    discovered = discover_sqlite_databases(
        SqliteDiscoveryConfig(enabled=False, directory=str(tmp_path))
    )

    assert discovered == []
