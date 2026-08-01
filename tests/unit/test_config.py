import importlib
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.config import (
    DatabaseSettings,
    load_database_settings,
    load_datasources_from_file,
)


def test_database_settings_load_valid_pagila_dsn() -> None:
    settings = DatabaseSettings(
        dsn="postgresql://reader:secret@127.0.0.1:55432/pagila"
    )

    assert settings.datasource_id == "pagila"
    assert settings.statement_timeout_seconds == 30
    assert settings.max_result_rows == 1000
    assert settings.dsn_value.endswith("/pagila")
    assert "secret" not in repr(settings)


def test_database_settings_reject_missing_dsn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("TEXT_TO_SQL_DATABASE_DSN", raising=False)

    with pytest.raises(ValidationError):
        DatabaseSettings()


def test_database_settings_reject_malformed_conninfo() -> None:
    with pytest.raises(ValidationError, match="dsn must be a valid PostgreSQL connection string"):
        DatabaseSettings(dsn="not a valid dsn with password=secret")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("min_pool_size", 0),
        ("max_pool_size", 0),
        ("pool_timeout_seconds", 0),
        ("statement_timeout_seconds", 0),
        ("max_result_rows", 0),
        ("connection_retry_count", -1),
    ],
)
def test_database_settings_reject_non_positive_limits(
    field: str, value: int
) -> None:
    with pytest.raises(ValidationError):
        DatabaseSettings(
            dsn="postgresql://reader:secret@127.0.0.1:55432/pagila",
            **{field: value},
        )


def test_database_settings_reject_inverted_pool_bounds() -> None:
    with pytest.raises(ValidationError, match="min_pool_size cannot exceed"):
        DatabaseSettings(
            dsn="postgresql://reader:secret@127.0.0.1:55432/pagila",
            min_pool_size=3,
            max_pool_size=2,
        )


def test_database_settings_reject_non_postgresql_dsn() -> None:
    """PostgreSQL type requires a postgresql:// DSN prefix."""
    with pytest.raises(ValidationError, match="dsn must be a valid PostgreSQL connection string"):
        DatabaseSettings(
            type="postgresql",
            dsn="mysql://reader:secret@127.0.0.1:3306/other",
        )


def test_load_database_settings_reads_explicit_env_file(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "TEXT_TO_SQL_DATABASE_DSN="
        "postgresql://reader:secret@127.0.0.1:55432/pagila\n",
        encoding="utf-8",
    )

    settings = load_database_settings(env_file)

    assert settings.datasource_id == "pagila"
    assert "secret" not in repr(settings)


def test_datasource_file_uses_explicit_allowlist_fields_and_config_package(
    tmp_path: Path,
) -> None:
    database_config = importlib.import_module("app.config.database")
    datasource_file = tmp_path / "datasources.json"
    datasource_file.write_text(
        """
        {
          "datasources": {
            "mysql_analytics": {
              "type": "mysql",
              "host": "127.0.0.1",
              "port": 3306,
              "database": "analytics",
              "username": "reader",
              "password": "secret",
              "allowed_schemas": ["analytics"],
              "allowed_tables": ["analytics.orders"]
            }
          }
        }
        """,
        encoding="utf-8",
    )

    settings = load_datasources_from_file(datasource_file)["mysql_analytics"]

    assert database_config.DatabaseSettings is DatabaseSettings
    assert settings.allowed_schemas == ("analytics",)
    assert settings.allowed_tables == ("analytics.orders",)
    assert not hasattr(settings, "_extra")
