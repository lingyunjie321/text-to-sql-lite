import inspect
from dataclasses import replace

import pytest

from app.connectors.metadata import TableMetadata
from tests.unit.test_schema_embedding_index import (
    PAYROLL,
    StubEmbeddingProvider,
    _snapshot,
)


def _inputs(
    *,
    payroll: TableMetadata = PAYROLL,
    provider: StubEmbeddingProvider | None = None,
):
    selected_provider = provider or StubEmbeddingProvider()
    return _snapshot(payroll=payroll), selected_provider


def _get_index(registry, snapshot, provider):
    return registry.get_or_build_authorized(
        datasource_id="pagila",
        snapshot=snapshot,
        allowed_schemas=("public",),
        allowed_tables=("public.film", "public.language"),
        provider=provider,
        semantic_version="semantic-v1",
    )


def test_authorization_precedes_documents_and_provider_call() -> None:
    from app.schema_linking.index import EmbeddingIndexRegistry

    snapshot, provider = _inputs()
    registry = EmbeddingIndexRegistry()

    _get_index(registry, snapshot, provider)

    rendered = "".join(
        text for call in provider.calls for text in call
    )
    assert "never-index-secret" not in rendered
    assert all("private.payroll" not in text for text in provider.calls[0])


def test_unauthorized_change_cannot_invalidate_or_rebuild_index() -> None:
    from app.schema_linking.index import EmbeddingIndexRegistry

    provider = StubEmbeddingProvider()
    first_snapshot, _ = _inputs(provider=provider)
    changed_snapshot, _ = _inputs(
        provider=provider,
        payroll=replace(
            PAYROLL,
            comment="changed-never-index-secret",
            aliases=("changed-never-index-alias",),
        ),
    )
    registry = EmbeddingIndexRegistry()

    first = _get_index(registry, first_snapshot, provider)
    changed = _get_index(registry, changed_snapshot, provider)

    assert changed.retrieval_version == first.retrieval_version
    assert changed.documents == first.documents
    assert changed is first
    assert len(provider.calls) == 1


def test_public_index_contract_has_no_pollution_input() -> None:
    from app.schema_linking import index

    forbidden = {
        "question",
        "gold",
        "evaluation",
        "few_shot",
        "rag",
        "expected_sql",
    }
    callables = (
        index.authorization_scope_sha256,
        index.authorize_schema_snapshot,
        index.build_authorized_schema_documents,
        index.build_retrieval_version,
        index.EmbeddingIndexRegistry.get_or_build_authorized,
    )

    for value in callables:
        parameters = set(inspect.signature(value).parameters)
        assert parameters.isdisjoint(forbidden)
    assert not hasattr(index.EmbeddingIndexRegistry, "get_or_build")
    assert not hasattr(index, "build_schema_documents")


def test_registry_observability_exposes_only_version_ids() -> None:
    from app.schema_linking.index import EmbeddingIndexRegistry

    snapshot, provider = _inputs()
    registry = EmbeddingIndexRegistry()
    result = _get_index(registry, snapshot, provider)

    rendered = repr(registry) + repr(result)
    assert result.retrieval_version_id in rendered
    for document in result.documents:
        rendered += repr(document)
        assert document.text not in rendered
        assert document.object_id not in rendered
    assert repr(result.vectors) not in rendered


def test_failed_build_does_not_publish_or_leak_partial_data() -> None:
    from app.schema_linking.index import (
        EmbeddingIndexBuildError,
        EmbeddingIndexRegistry,
    )

    provider = StubEmbeddingProvider(
        error=RuntimeError(
            "private-vector-response never-index-secret"
        )
    )
    snapshot, _ = _inputs(provider=provider)
    registry = EmbeddingIndexRegistry()

    with pytest.raises(EmbeddingIndexBuildError) as captured:
        _get_index(registry, snapshot, provider)

    rendered = (
        str(captured.value)
        + repr(captured.value)
        + repr(registry)
    )
    assert registry.resident_version_ids == ()
    assert "private-vector-response" not in rendered
    assert "never-index-secret" not in rendered
