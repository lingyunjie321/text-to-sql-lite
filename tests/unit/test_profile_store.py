from __future__ import annotations

import sqlite3
import stat
from pathlib import Path

import pytest

from app.local.profile_models import DatasourceProfile, ModelProfile
from app.local.profile_store import (
    LocalProfileStore,
    ProfileAlreadyExistsError,
    ProfileNotFoundError,
    ProfileStoreCorruptError,
)


def _model(profile_id: str = "local-model", name: str = "Local Model") -> ModelProfile:
    return ModelProfile(
        id=profile_id,
        name=name,
        provider_type="openai_compatible",
        base_url="http://localhost:11434/v1",
        model_name="qwen2.5-coder",
    )


def _embedding_model() -> ModelProfile:
    return ModelProfile(
        id="embedding-model",
        name="Embedding Model",
        provider_type="openai_compatible",
        base_url="http://localhost:11434/v1",
        model_name="qwen2.5-coder",
        embedding_base_url="http://localhost:11434/v1",
        embedding_model="nomic-embed-text",
        embedding_dimension=768,
    )


def _datasource(
    profile_id: str = "local-postgres",
    name: str = "Local PostgreSQL",
) -> DatasourceProfile:
    return DatasourceProfile(
        id=profile_id,
        name=name,
        database_type="postgresql",
        host="127.0.0.1",
        port=5432,
        database="analytics",
        username="reader",
        allowed_schemas=("public",),
        allowed_tables=("public.orders",),
    )


def test_store_initializes_versioned_database_only_when_constructed(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "profiles" / "config.db"
    assert not database_path.exists()

    LocalProfileStore(database_path)

    assert database_path.is_file()
    with sqlite3.connect(database_path) as connection:
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(model_profiles)")
        }
    assert version == 2
    assert "embedding_dimension" in columns
    assert "api_key" not in columns
    assert "password" not in columns


def test_store_does_not_change_existing_injected_parent_permissions(
    tmp_path: Path,
) -> None:
    existing_parent = tmp_path / "shared-config"
    existing_parent.mkdir(mode=0o750)
    existing_parent.chmod(0o750)

    LocalProfileStore(existing_parent / "config.db")

    mode = stat.S_IMODE(existing_parent.stat().st_mode)
    assert mode == 0o750


def test_store_round_trips_model_profile(tmp_path: Path) -> None:
    store = LocalProfileStore(tmp_path / "config.db")
    created = store.create_model(_model())

    assert created == _model()
    assert store.get_model("local-model") == _model()

    replaced = _model(name="Renamed Model")
    assert store.replace_model(replaced) == replaced
    assert store.list_models() == (replaced,)
    assert store.delete_model("local-model") is True
    assert store.get_model("local-model") is None
    assert store.delete_model("local-model") is False


def test_store_round_trips_embedding_dimension(tmp_path: Path) -> None:
    store = LocalProfileStore(tmp_path / "config.db")

    store.create_model(_embedding_model())

    assert store.get_model("embedding-model") == _embedding_model()


def test_store_migrates_version_one_model_profiles(tmp_path: Path) -> None:
    database_path = tmp_path / "config.db"
    with sqlite3.connect(database_path) as connection:
        connection.executescript(
            """
            CREATE TABLE model_profiles (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                provider_type TEXT NOT NULL,
                base_url TEXT NOT NULL,
                model_name TEXT NOT NULL,
                embedding_base_url TEXT,
                embedding_model TEXT,
                CHECK (provider_type = 'openai_compatible'),
                CHECK (
                    (embedding_base_url IS NULL AND embedding_model IS NULL)
                    OR
                    (embedding_base_url IS NOT NULL AND embedding_model IS NOT NULL)
                )
            );
            CREATE TABLE datasource_profiles (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                database_type TEXT NOT NULL,
                host TEXT NOT NULL,
                port INTEGER NOT NULL CHECK (port BETWEEN 1 AND 65535),
                database_name TEXT NOT NULL,
                username TEXT NOT NULL,
                allowed_schemas_json TEXT NOT NULL,
                allowed_tables_json TEXT NOT NULL,
                CHECK (database_type IN ('postgresql', 'mysql'))
            );
            INSERT INTO model_profiles (
                id, name, provider_type, base_url, model_name,
                embedding_base_url, embedding_model
            ) VALUES (
                'local-model', 'Local Model', 'openai_compatible',
                'http://localhost:11434/v1', 'qwen2.5-coder', NULL, NULL
            );
            PRAGMA user_version=1;
            """
        )

    store = LocalProfileStore(database_path)

    with sqlite3.connect(database_path) as connection:
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(model_profiles)")
        }
    assert version == 2
    assert "embedding_dimension" in columns
    assert store.get_model("local-model") == _model()


def test_store_does_not_guess_dimension_for_version_one_embedding(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "config.db"
    with sqlite3.connect(database_path) as connection:
        connection.executescript(
            """
            CREATE TABLE model_profiles (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                provider_type TEXT NOT NULL,
                base_url TEXT NOT NULL,
                model_name TEXT NOT NULL,
                embedding_base_url TEXT,
                embedding_model TEXT
            );
            CREATE TABLE datasource_profiles (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                database_type TEXT NOT NULL,
                host TEXT NOT NULL,
                port INTEGER NOT NULL,
                database_name TEXT NOT NULL,
                username TEXT NOT NULL,
                allowed_schemas_json TEXT NOT NULL,
                allowed_tables_json TEXT NOT NULL
            );
            INSERT INTO model_profiles VALUES (
                'local-model', 'Local Model', 'openai_compatible',
                'http://localhost:11434/v1', 'qwen2.5-coder',
                'http://localhost:11434/v1', 'nomic-embed-text'
            );
            PRAGMA user_version=1;
            """
        )

    with pytest.raises(ProfileStoreCorruptError):
        LocalProfileStore(database_path)

    with sqlite3.connect(database_path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 1
        columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(model_profiles)")
        }
    assert "embedding_dimension" not in columns


def test_store_round_trips_datasource_profile(tmp_path: Path) -> None:
    store = LocalProfileStore(tmp_path / "config.db")
    created = store.create_datasource(_datasource())

    assert created == _datasource()
    assert store.get_datasource("local-postgres") == _datasource()

    replaced = _datasource(name="Renamed Database")
    assert store.replace_datasource(replaced) == replaced
    assert store.list_datasources() == (replaced,)
    assert store.delete_datasource("local-postgres") is True
    assert store.get_datasource("local-postgres") is None


def test_store_lists_profiles_by_name_then_id(tmp_path: Path) -> None:
    store = LocalProfileStore(tmp_path / "config.db")
    store.create_model(_model("z-model", "B"))
    store.create_model(_model("a-model", "A"))
    store.create_model(_model("b-model", "A"))

    assert tuple(profile.id for profile in store.list_models()) == (
        "a-model",
        "b-model",
        "z-model",
    )


def test_store_reports_duplicate_profile_without_database_details(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "secret-directory" / "config.db"
    store = LocalProfileStore(database_path)
    store.create_model(_model())

    with pytest.raises(ProfileAlreadyExistsError) as exc_info:
        store.create_model(_model())

    assert exc_info.value.code == "PROFILE_ALREADY_EXISTS"
    assert str(database_path) not in str(exc_info.value)
    assert "model_profiles" not in str(exc_info.value)


def test_store_reports_missing_replace_with_stable_error(tmp_path: Path) -> None:
    store = LocalProfileStore(tmp_path / "config.db")

    with pytest.raises(ProfileNotFoundError) as exc_info:
        store.replace_datasource(_datasource())

    assert exc_info.value.code == "PROFILE_NOT_FOUND"
    assert str(exc_info.value) == "profile was not found"


def test_store_rejects_unknown_schema_version_without_overwriting_it(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "config.db"
    with sqlite3.connect(database_path) as connection:
        connection.execute("PRAGMA user_version=99")

    with pytest.raises(ProfileStoreCorruptError) as exc_info:
        LocalProfileStore(database_path)

    assert exc_info.value.code == "PROFILE_STORE_CORRUPT"
    assert str(database_path) not in str(exc_info.value)
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 99


def test_store_rejects_unversioned_nonempty_database_without_modifying_it(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "config.db"
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "CREATE TABLE model_profiles (api_key TEXT NOT NULL)"
        )

    with pytest.raises(ProfileStoreCorruptError):
        LocalProfileStore(database_path)

    with sqlite3.connect(database_path) as connection:
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
    assert version == 0
    assert tables == {"model_profiles"}


def test_store_rejects_versioned_database_with_unknown_schema(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "config.db"
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "CREATE TABLE model_profiles (id TEXT PRIMARY KEY, api_key TEXT)"
        )
        connection.execute(
            "CREATE TABLE datasource_profiles (id TEXT PRIMARY KEY)"
        )
        connection.execute("PRAGMA user_version=1")

    with pytest.raises(ProfileStoreCorruptError):
        LocalProfileStore(database_path)


def test_store_fails_closed_when_persisted_allowlist_is_corrupt(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "config.db"
    store = LocalProfileStore(database_path)
    store.create_datasource(_datasource())
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "UPDATE datasource_profiles SET allowed_tables_json = ? WHERE id = ?",
            ("not-json", "local-postgres"),
        )

    with pytest.raises(ProfileStoreCorruptError) as exc_info:
        store.get_datasource("local-postgres")

    assert str(exc_info.value) == "profile store data is invalid"


def test_store_fails_closed_when_allowlist_blob_is_not_utf8(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "config.db"
    store = LocalProfileStore(database_path)
    store.create_datasource(_datasource())
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            UPDATE datasource_profiles
            SET allowed_schemas_json = ?
            WHERE id = ?
            """,
            (sqlite3.Binary(b"\xff"), "local-postgres"),
        )

    with pytest.raises(ProfileStoreCorruptError):
        store.get_datasource("local-postgres")


def test_store_file_never_contains_unrelated_secret_sentinel(tmp_path: Path) -> None:
    database_path = tmp_path / "config.db"
    store = LocalProfileStore(database_path)
    store.create_model(_model())
    store.create_datasource(_datasource())

    assert b"stage2-secret-sentinel" not in database_path.read_bytes()
