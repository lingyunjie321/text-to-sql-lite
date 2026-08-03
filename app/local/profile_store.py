"""SQLite persistence for non-sensitive local profiles."""

from __future__ import annotations

from contextlib import contextmanager
import json
import os
from pathlib import Path
import sqlite3
import threading
from typing import Iterator, NoReturn

from pydantic import ValidationError

from app.config.local_app import default_profile_database_path
from app.local.profile_models import DatasourceProfile, ModelProfile

_SCHEMA_VERSION = 2
_V1_EXPECTED_SCHEMA = {
    "model_profiles": frozenset(
        {
            "id",
            "name",
            "provider_type",
            "base_url",
            "model_name",
            "embedding_base_url",
            "embedding_model",
        }
    ),
    "datasource_profiles": frozenset(
        {
            "id",
            "name",
            "database_type",
            "host",
            "port",
            "database_name",
            "username",
            "allowed_schemas_json",
            "allowed_tables_json",
        }
    ),
}
_EXPECTED_SCHEMA = {
    "model_profiles": frozenset(
        {
            "id",
            "name",
            "provider_type",
            "base_url",
            "model_name",
            "embedding_base_url",
            "embedding_model",
            "embedding_dimension",
        }
    ),
    "datasource_profiles": frozenset(
        {
            "id",
            "name",
            "database_type",
            "host",
            "port",
            "database_name",
            "username",
            "allowed_schemas_json",
            "allowed_tables_json",
        }
    ),
}


class ProfileStoreError(RuntimeError):
    """Base error with a stable, non-sensitive public code and message."""

    code = "PROFILE_STORE_UNAVAILABLE"


class ProfileAlreadyExistsError(ProfileStoreError):
    code = "PROFILE_ALREADY_EXISTS"

    def __init__(self) -> None:
        super().__init__("profile already exists")


class ProfileNotFoundError(ProfileStoreError):
    code = "PROFILE_NOT_FOUND"

    def __init__(self) -> None:
        super().__init__("profile was not found")


class ProfileStoreBusyError(ProfileStoreError):
    code = "PROFILE_STORE_BUSY"

    def __init__(self) -> None:
        super().__init__("profile store is busy")


class ProfileStoreCorruptError(ProfileStoreError):
    code = "PROFILE_STORE_CORRUPT"

    def __init__(self) -> None:
        super().__init__("profile store data is invalid")


class ProfileStoreUnavailableError(ProfileStoreError):
    code = "PROFILE_STORE_UNAVAILABLE"

    def __init__(self) -> None:
        super().__init__("profile store is unavailable")


class LocalProfileStore:
    """Persist validated profiles while excluding every credential."""

    def __init__(self, database_path: Path | None = None) -> None:
        self._protect_existing_parent = database_path is None
        self._database_path = (
            database_path or default_profile_database_path()
        ).expanduser()
        self._write_lock = threading.RLock()
        self._initialize()

    @property
    def database_path(self) -> Path:
        return self._database_path

    def create_model(self, profile: ModelProfile) -> ModelProfile:
        try:
            with self._write_connection() as connection:
                connection.execute(
                    """
                    INSERT INTO model_profiles (
                        id, name, provider_type, base_url, model_name,
                        embedding_base_url, embedding_model,
                        embedding_dimension
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        profile.id,
                        profile.name,
                        profile.provider_type,
                        str(profile.base_url),
                        profile.model_name,
                        (
                            str(profile.embedding_base_url)
                            if profile.embedding_base_url is not None
                            else None
                        ),
                        profile.embedding_model,
                        profile.embedding_dimension,
                    ),
                )
        except sqlite3.IntegrityError:
            raise ProfileAlreadyExistsError() from None
        except sqlite3.Error as error:
            self._raise_sqlite_error(error)
        return profile

    def get_model(self, profile_id: str) -> ModelProfile | None:
        try:
            with self._connection() as connection:
                row = connection.execute(
                    "SELECT * FROM model_profiles WHERE id = ?",
                    (profile_id,),
                ).fetchone()
        except sqlite3.Error as error:
            self._raise_sqlite_error(error)
        if row is None:
            return None
        return self._model_from_row(row)

    def list_models(self) -> tuple[ModelProfile, ...]:
        try:
            with self._connection() as connection:
                rows = connection.execute(
                    "SELECT * FROM model_profiles ORDER BY name, id"
                ).fetchall()
        except sqlite3.Error as error:
            self._raise_sqlite_error(error)
        return tuple(self._model_from_row(row) for row in rows)

    def replace_model(self, profile: ModelProfile) -> ModelProfile:
        try:
            with self._write_connection() as connection:
                cursor = connection.execute(
                    """
                    UPDATE model_profiles
                    SET name = ?, provider_type = ?, base_url = ?, model_name = ?,
                        embedding_base_url = ?, embedding_model = ?,
                        embedding_dimension = ?
                    WHERE id = ?
                    """,
                    (
                        profile.name,
                        profile.provider_type,
                        str(profile.base_url),
                        profile.model_name,
                        (
                            str(profile.embedding_base_url)
                            if profile.embedding_base_url is not None
                            else None
                        ),
                        profile.embedding_model,
                        profile.embedding_dimension,
                        profile.id,
                    ),
                )
                if cursor.rowcount != 1:
                    raise ProfileNotFoundError()
        except ProfileNotFoundError:
            raise
        except sqlite3.Error as error:
            self._raise_sqlite_error(error)
        return profile

    def delete_model(self, profile_id: str) -> bool:
        try:
            with self._write_connection() as connection:
                cursor = connection.execute(
                    "DELETE FROM model_profiles WHERE id = ?",
                    (profile_id,),
                )
                return cursor.rowcount == 1
        except sqlite3.Error as error:
            self._raise_sqlite_error(error)

    def create_datasource(
        self,
        profile: DatasourceProfile,
    ) -> DatasourceProfile:
        try:
            with self._write_connection() as connection:
                connection.execute(
                    """
                    INSERT INTO datasource_profiles (
                        id, name, database_type, host, port, database_name,
                        username, allowed_schemas_json, allowed_tables_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        profile.id,
                        profile.name,
                        profile.database_type,
                        profile.host,
                        profile.port,
                        profile.database,
                        profile.username,
                        json.dumps(
                            profile.allowed_schemas,
                            ensure_ascii=False,
                            separators=(",", ":"),
                        ),
                        json.dumps(
                            profile.allowed_tables,
                            ensure_ascii=False,
                            separators=(",", ":"),
                        ),
                    ),
                )
        except sqlite3.IntegrityError:
            raise ProfileAlreadyExistsError() from None
        except sqlite3.Error as error:
            self._raise_sqlite_error(error)
        return profile

    def get_datasource(self, profile_id: str) -> DatasourceProfile | None:
        try:
            with self._connection() as connection:
                row = connection.execute(
                    "SELECT * FROM datasource_profiles WHERE id = ?",
                    (profile_id,),
                ).fetchone()
        except sqlite3.Error as error:
            self._raise_sqlite_error(error)
        if row is None:
            return None
        return self._datasource_from_row(row)

    def list_datasources(self) -> tuple[DatasourceProfile, ...]:
        try:
            with self._connection() as connection:
                rows = connection.execute(
                    "SELECT * FROM datasource_profiles ORDER BY name, id"
                ).fetchall()
        except sqlite3.Error as error:
            self._raise_sqlite_error(error)
        return tuple(self._datasource_from_row(row) for row in rows)

    def replace_datasource(
        self,
        profile: DatasourceProfile,
    ) -> DatasourceProfile:
        try:
            with self._write_connection() as connection:
                cursor = connection.execute(
                    """
                    UPDATE datasource_profiles
                    SET name = ?, database_type = ?, host = ?, port = ?,
                        database_name = ?, username = ?, allowed_schemas_json = ?,
                        allowed_tables_json = ?
                    WHERE id = ?
                    """,
                    (
                        profile.name,
                        profile.database_type,
                        profile.host,
                        profile.port,
                        profile.database,
                        profile.username,
                        json.dumps(
                            profile.allowed_schemas,
                            ensure_ascii=False,
                            separators=(",", ":"),
                        ),
                        json.dumps(
                            profile.allowed_tables,
                            ensure_ascii=False,
                            separators=(",", ":"),
                        ),
                        profile.id,
                    ),
                )
                if cursor.rowcount != 1:
                    raise ProfileNotFoundError()
        except ProfileNotFoundError:
            raise
        except sqlite3.Error as error:
            self._raise_sqlite_error(error)
        return profile

    def delete_datasource(self, profile_id: str) -> bool:
        try:
            with self._write_connection() as connection:
                cursor = connection.execute(
                    "DELETE FROM datasource_profiles WHERE id = ?",
                    (profile_id,),
                )
                return cursor.rowcount == 1
        except sqlite3.Error as error:
            self._raise_sqlite_error(error)

    def _initialize(self) -> None:
        try:
            parent_existed = self._database_path.parent.exists()
            self._database_path.parent.mkdir(
                mode=0o700,
                parents=True,
                exist_ok=True,
            )
            if self._protect_existing_parent or not parent_existed:
                os.chmod(self._database_path.parent, 0o700)
            with self._connection() as connection:
                version = connection.execute("PRAGMA user_version").fetchone()[0]
                if version not in (0, 1, _SCHEMA_VERSION):
                    raise ProfileStoreCorruptError()
                if version == 0:
                    existing_object = connection.execute(
                        """
                        SELECT 1
                        FROM sqlite_master
                        WHERE name NOT LIKE 'sqlite_%'
                        LIMIT 1
                        """
                    ).fetchone()
                    if existing_object is not None:
                        raise ProfileStoreCorruptError()
                    connection.execute("BEGIN IMMEDIATE")
                    try:
                        connection.execute(
                            """
                            CREATE TABLE IF NOT EXISTS model_profiles (
                                id TEXT PRIMARY KEY,
                                name TEXT NOT NULL,
                                provider_type TEXT NOT NULL,
                                base_url TEXT NOT NULL,
                                model_name TEXT NOT NULL,
                                embedding_base_url TEXT,
                                embedding_model TEXT,
                                embedding_dimension INTEGER,
                                CHECK (provider_type = 'openai_compatible'),
                                CHECK (
                                    (
                                        embedding_base_url IS NULL
                                        AND embedding_model IS NULL
                                        AND embedding_dimension IS NULL
                                    )
                                    OR
                                    (
                                        embedding_base_url IS NOT NULL
                                        AND embedding_model IS NOT NULL
                                        AND embedding_dimension BETWEEN 1 AND 1000000
                                    )
                                )
                            )
                            """
                        )
                        connection.execute(
                            """
                            CREATE TABLE IF NOT EXISTS datasource_profiles (
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
                            )
                            """
                        )
                        connection.execute(f"PRAGMA user_version={_SCHEMA_VERSION}")
                        connection.commit()
                    except BaseException:
                        connection.rollback()
                        raise
                elif version == 1:
                    self._migrate_v1_to_v2(connection)
                self._validate_schema(connection)
                connection.execute("PRAGMA journal_mode=WAL")
            os.chmod(self._database_path, 0o600)
        except ProfileStoreError:
            raise
        except (OSError, sqlite3.Error) as error:
            if isinstance(error, sqlite3.Error):
                self._raise_sqlite_error(error)
            raise ProfileStoreUnavailableError() from None

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self._database_path, timeout=5.0)
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA busy_timeout=5000")
            yield connection
        finally:
            connection.close()

    @contextmanager
    def _write_connection(self) -> Iterator[sqlite3.Connection]:
        with self._write_lock:
            with self._connection() as connection:
                connection.execute("BEGIN IMMEDIATE")
                try:
                    yield connection
                    connection.commit()
                except BaseException:
                    connection.rollback()
                    raise

    @staticmethod
    def _validate_schema(
        connection: sqlite3.Connection,
        expected_schema: dict[str, frozenset[str]] = _EXPECTED_SCHEMA,
    ) -> None:
        objects = {
            (row["type"], row["name"])
            for row in connection.execute(
                """
                SELECT type, name
                FROM sqlite_master
                WHERE name NOT LIKE 'sqlite_%'
                """
            )
        }
        expected_objects = {
            ("table", table_name) for table_name in expected_schema
        }
        if objects != expected_objects:
            raise ProfileStoreCorruptError()
        for table_name, expected_columns in expected_schema.items():
            columns = {
                row["name"]
                for row in connection.execute(
                    f"PRAGMA table_info({table_name})"
                )
            }
            if columns != expected_columns:
                raise ProfileStoreCorruptError()

    @classmethod
    def _migrate_v1_to_v2(cls, connection: sqlite3.Connection) -> None:
        cls._validate_schema(connection, _V1_EXPECTED_SCHEMA)
        configured_embedding = connection.execute(
            """
            SELECT 1
            FROM model_profiles
            WHERE embedding_base_url IS NOT NULL
               OR embedding_model IS NOT NULL
            LIMIT 1
            """
        ).fetchone()
        if configured_embedding is not None:
            raise ProfileStoreCorruptError()
        connection.execute("BEGIN IMMEDIATE")
        try:
            connection.execute(
                """
                ALTER TABLE model_profiles
                ADD COLUMN embedding_dimension INTEGER
                CHECK (
                    embedding_dimension IS NULL
                    OR embedding_dimension BETWEEN 1 AND 1000000
                )
                """
            )
            connection.execute("PRAGMA user_version=2")
            connection.commit()
        except BaseException:
            connection.rollback()
            raise

    @staticmethod
    def _model_from_row(row: sqlite3.Row) -> ModelProfile:
        try:
            return ModelProfile(
                id=row["id"],
                name=row["name"],
                provider_type=row["provider_type"],
                base_url=row["base_url"],
                model_name=row["model_name"],
                embedding_base_url=row["embedding_base_url"],
                embedding_model=row["embedding_model"],
                embedding_dimension=row["embedding_dimension"],
            )
        except (IndexError, KeyError, TypeError, ValidationError):
            raise ProfileStoreCorruptError() from None

    @staticmethod
    def _datasource_from_row(row: sqlite3.Row) -> DatasourceProfile:
        try:
            return DatasourceProfile(
                id=row["id"],
                name=row["name"],
                database_type=row["database_type"],
                host=row["host"],
                port=row["port"],
                database=row["database_name"],
                username=row["username"],
                allowed_schemas=json.loads(row["allowed_schemas_json"]),
                allowed_tables=json.loads(row["allowed_tables_json"]),
            )
        except (
            json.JSONDecodeError,
            IndexError,
            KeyError,
            TypeError,
            UnicodeError,
            ValidationError,
        ):
            raise ProfileStoreCorruptError() from None

    @staticmethod
    def _raise_sqlite_error(error: sqlite3.Error) -> NoReturn:
        message = str(error).casefold()
        if "locked" in message or "busy" in message:
            raise ProfileStoreBusyError() from None
        if "malformed" in message or "not a database" in message:
            raise ProfileStoreCorruptError() from None
        raise ProfileStoreUnavailableError() from None
