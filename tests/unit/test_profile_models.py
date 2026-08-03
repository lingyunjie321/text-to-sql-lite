from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.local.profile_models import DatasourceProfile, ModelProfile


def test_model_profile_normalizes_public_fields_without_secret_fields() -> None:
    profile = ModelProfile(
        id="local-model",
        name="  本地模型  ",
        provider_type="openai_compatible",
        base_url="http://127.0.0.1:11434/v1",
        model_name="  qwen2.5-coder  ",
    )

    assert profile.name == "本地模型"
    assert str(profile.base_url) == "http://127.0.0.1:11434/v1"
    assert profile.model_name == "qwen2.5-coder"
    assert "api_key" not in profile.model_dump()
    assert "password" not in repr(profile)


@pytest.mark.parametrize(
    "profile_id",
    ["", "UPPER", "bad id", "bad\nlog", "../escape", "trailing-"],
)
def test_profile_id_rejects_values_that_are_unsafe_for_logs(
    profile_id: str,
) -> None:
    with pytest.raises(ValidationError, match="profile id is invalid"):
        ModelProfile(
            id=profile_id,
            name="Model",
            provider_type="openai_compatible",
            base_url="https://models.example.com/v1",
            model_name="model",
        )


@pytest.mark.parametrize(
    "base_url",
    [
        "http://models.example.com/v1",
        "https://user:secret@models.example.com/v1",
        "https://models.example.com/v1?api_key=secret",
        "https://models.example.com/v1#secret",
    ],
)
def test_model_profile_rejects_unsafe_remote_endpoint(base_url: str) -> None:
    with pytest.raises(ValidationError, match="base_url is invalid"):
        ModelProfile(
            id="remote-model",
            name="Remote",
            provider_type="openai_compatible",
            base_url=base_url,
            model_name="model",
        )


@pytest.mark.parametrize(
    "embedding_fields",
    [
        {"embedding_model": "embedding-model"},
        {
            "embedding_base_url": "http://localhost:11434/v1",
            "embedding_model": "embedding-model",
        },
        {
            "embedding_base_url": "http://localhost:11434/v1",
            "embedding_dimension": 768,
        },
    ],
)
def test_model_profile_requires_complete_embedding_group(
    embedding_fields: dict[str, object],
) -> None:
    with pytest.raises(
        ValidationError,
        match="embedding configuration is incomplete",
    ):
        ModelProfile(
            id="local-model",
            name="Local",
            provider_type="openai_compatible",
            base_url="http://localhost:11434/v1",
            model_name="model",
            **embedding_fields,
        )


def test_model_profile_accepts_complete_embedding_group() -> None:
    profile = ModelProfile(
        id="local-model",
        name="Local",
        provider_type="openai_compatible",
        base_url="http://localhost:11434/v1",
        model_name="model",
        embedding_base_url="http://localhost:11434/v1",
        embedding_model="embedding-model",
        embedding_dimension=768,
    )

    assert profile.embedding_dimension == 768


@pytest.mark.parametrize("dimension", [True, 0, -1, 1_000_001])
def test_model_profile_rejects_invalid_embedding_dimension(
    dimension: object,
) -> None:
    with pytest.raises(ValidationError):
        ModelProfile(
            id="local-model",
            name="Local",
            provider_type="openai_compatible",
            base_url="http://localhost:11434/v1",
            model_name="model",
            embedding_base_url="http://localhost:11434/v1",
            embedding_model="embedding-model",
            embedding_dimension=dimension,
        )


def test_model_profile_rejects_secret_extra_fields() -> None:
    with pytest.raises(ValidationError):
        ModelProfile(
            id="local-model",
            name="Local",
            provider_type="openai_compatible",
            base_url="http://localhost:11434/v1",
            model_name="model",
            api_key="must-not-enter-profile",  # type: ignore[call-arg]
        )


def test_datasource_profile_normalizes_and_freezes_allowlist() -> None:
    profile = DatasourceProfile(
        id="local_postgres",
        name="  Local PostgreSQL  ",
        database_type="postgresql",
        host="127.0.0.1",
        port=5432,
        database="  analytics  ",
        username="  reader  ",
        allowed_schemas=[" public "],
        allowed_tables=[" public.orders ", "public.customers"],
    )

    assert profile.name == "Local PostgreSQL"
    assert profile.database == "analytics"
    assert profile.username == "reader"
    assert profile.allowed_schemas == ("public",)
    assert profile.allowed_tables == ("public.orders", "public.customers")
    assert "password" not in profile.model_dump()


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("host", "postgresql://reader:secret@db/pagila", "host is invalid"),
        ("port", True, "Input should be a valid integer"),
        ("port", 0, "greater than or equal to 1"),
        ("database", "bad\nname", "database is invalid"),
        ("username", "bad\x00name", "username is invalid"),
    ],
)
def test_datasource_profile_rejects_unsafe_connection_identity(
    field: str,
    value: object,
    message: str,
) -> None:
    values: dict[str, object] = {
        "id": "local-postgres",
        "name": "Local",
        "database_type": "postgresql",
        "host": "localhost",
        "port": 5432,
        "database": "analytics",
        "username": "reader",
        "allowed_schemas": ["public"],
        "allowed_tables": ["public.orders"],
    }
    values[field] = value

    with pytest.raises(ValidationError, match=message):
        DatasourceProfile(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "allowed_tables",
    [[], ["orders"], ["private.orders"], ["public.orders", "public.orders"]],
)
def test_datasource_profile_rejects_invalid_table_allowlist(
    allowed_tables: list[str],
) -> None:
    with pytest.raises(ValidationError):
        DatasourceProfile(
            id="local-postgres",
            name="Local",
            database_type="postgresql",
            host="localhost",
            port=5432,
            database="analytics",
            username="reader",
            allowed_schemas=["public"],
            allowed_tables=allowed_tables,
        )


def test_datasource_profile_rejects_password_extra_field() -> None:
    with pytest.raises(ValidationError):
        DatasourceProfile(
            id="local-postgres",
            name="Local",
            database_type="postgresql",
            host="localhost",
            port=5432,
            database="analytics",
            username="reader",
            allowed_schemas=["public"],
            allowed_tables=["public.orders"],
            password="must-not-enter-profile",  # type: ignore[call-arg]
        )
