from __future__ import annotations

from pydantic import SecretStr

from app.local.credential_store import (
    DatasourceCredentials,
    InMemoryCredentialStore,
    ModelCredentials,
)


def test_model_credentials_are_available_without_appearing_in_repr() -> None:
    store = InMemoryCredentialStore()
    credentials = ModelCredentials(
        generation_api_key=SecretStr("generation-secret"),
        embedding_api_key=SecretStr("embedding-secret"),
    )

    store.put_model("local-model", credentials)

    stored = store.get_model("local-model")
    assert stored is not None
    assert stored.generation_api_key is not None
    assert stored.generation_api_key.get_secret_value() == "generation-secret"
    assert "generation-secret" not in repr(stored)
    assert "embedding-secret" not in repr(store)
    assert store.has_model("local-model") is True


def test_empty_model_credentials_remove_existing_entry() -> None:
    store = InMemoryCredentialStore()
    store.put_model(
        "local-model",
        ModelCredentials(generation_api_key=SecretStr("secret")),
    )

    store.put_model("local-model", ModelCredentials())

    assert store.get_model("local-model") is None
    assert store.has_model("local-model") is False


def test_datasource_credentials_can_be_replaced_and_discarded() -> None:
    store = InMemoryCredentialStore()
    store.put_datasource(
        "local-postgres",
        DatasourceCredentials(password=SecretStr("old-secret")),
    )
    store.put_datasource(
        "local-postgres",
        DatasourceCredentials(password=SecretStr("new-secret")),
    )

    stored = store.get_datasource("local-postgres")
    assert stored is not None
    assert stored.password is not None
    assert stored.password.get_secret_value() == "new-secret"

    store.discard_datasource("local-postgres")
    assert store.get_datasource("local-postgres") is None


def test_clear_all_removes_model_and_datasource_credentials() -> None:
    store = InMemoryCredentialStore()
    store.put_model(
        "local-model",
        ModelCredentials(generation_api_key=SecretStr("model-secret")),
    )
    store.put_datasource(
        "local-postgres",
        DatasourceCredentials(password=SecretStr("database-secret")),
    )

    store.clear_all()

    assert store.get_model("local-model") is None
    assert store.get_datasource("local-postgres") is None


def test_new_credential_store_has_no_credentials_after_profile_restart() -> None:
    first_process = InMemoryCredentialStore()
    first_process.put_model(
        "local-model",
        ModelCredentials(generation_api_key=SecretStr("secret")),
    )

    restarted_process = InMemoryCredentialStore()

    assert restarted_process.get_model("local-model") is None
