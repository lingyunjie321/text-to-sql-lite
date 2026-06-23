from pathlib import Path

import pytest

from text_to_sql_demo.api.service import TextToSQLApiService


def _write_workflow_config(tmp_path: Path, database_yaml: str) -> Path:
    config_file = tmp_path / "workflow.yaml"
    config_file.write_text(
        f"""
workflow:
  name: database_connection_test
  start_node: schema_linking
  max_steps: 10
  max_repair_attempts: 3
dialect:
  name: postgres
  target_dialect: postgres
database:
{database_yaml}
schema:
  catalog_source: database
nodes:
  schema_linking:
    type: schema_linking
""",
        encoding="utf-8",
    )
    return config_file


def test_service_builds_postgres_url_from_structured_connection_fields(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TEXT_TO_SQL_DB_PASSWORD", "secret")
    config_file = _write_workflow_config(
        tmp_path,
        """
  default: warehouse
  connections:
    warehouse:
      driver: postgresql
      host: db.example.com
      port: 5432
      database_name: analytics
      username: readonly_user
      password_env: TEXT_TO_SQL_DB_PASSWORD
      query:
        sslmode: require
      fallback_url: postgresql://fallback/fallback_db
""",
    )

    service = TextToSQLApiService(config_path=config_file)

    assert (
        service.database_url
        == "postgresql+psycopg://readonly_user:secret@db.example.com:5432/analytics?sslmode=require"
    )


def test_full_database_url_env_still_overrides_structured_fields(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "DEMO_DATABASE_URL",
        "postgresql+psycopg://env_user:env_secret@env.example.com:5432/env_db",
    )
    monkeypatch.setenv("TEXT_TO_SQL_DB_PASSWORD", "structured_secret")
    config_file = _write_workflow_config(
        tmp_path,
        """
  default: warehouse
  connections:
    warehouse:
      driver: postgresql
      url_env: DEMO_DATABASE_URL
      host: db.example.com
      port: 5432
      database_name: analytics
      username: readonly_user
      password_env: TEXT_TO_SQL_DB_PASSWORD
      fallback_url: postgresql://fallback/fallback_db
""",
    )

    service = TextToSQLApiService(config_path=config_file)

    assert service.database_url == (
        "postgresql+psycopg://env_user:env_secret@env.example.com:5432/env_db"
    )


def test_structured_database_password_can_come_from_env_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env.local").write_text(
        "TEXT_TO_SQL_DB_PASSWORD=file_secret\n",
        encoding="utf-8",
    )
    config_file = _write_workflow_config(
        tmp_path,
        """
  default: warehouse
  connections:
    warehouse:
      driver: postgresql
      host: db.example.com
      port: 5432
      database_name: analytics
      username: readonly_user
      password_env: TEXT_TO_SQL_DB_PASSWORD
""",
    )

    service = TextToSQLApiService(config_path=config_file)

    assert (
        service.database_url
        == "postgresql+psycopg://readonly_user:file_secret@db.example.com:5432/analytics"
    )
