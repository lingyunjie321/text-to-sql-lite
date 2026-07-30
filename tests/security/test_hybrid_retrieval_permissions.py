import json
from copy import copy
from dataclasses import replace

import pytest

from app.connectors.metadata import (
    TableMetadata,
    build_schema_snapshot,
)
from app.schema_linking import link_schema
from app.workflow.complexity import (
    QueryComplexity,
    decide_complexity,
)
from tests.unit.test_schema_embedding_index import PAYROLL
from tests.unit.test_schema_hybrid_retrieval import (
    ACTOR,
    HYBRID_FILM,
    SemanticEmbeddingProvider,
)


def _snapshot(payroll: TableMetadata = PAYROLL):
    return build_schema_snapshot(
        tables=(HYBRID_FILM, ACTOR, payroll),
        primary_keys=(),
        foreign_keys=(),
        unique_constraints=(),
        unique_indexes=(),
    )


def _runtime(provider, registry=None):
    from app.schema_linking.index import (
        EmbeddingIndexRegistry,
        RetrievalRuntime,
    )

    return RetrievalRuntime(
        provider=provider,
        registry=registry or EmbeddingIndexRegistry(),
        semantic_version="semantic-v1",
    )


def _link(snapshot, runtime, *, question: str = "semantic-only-query"):
    return link_schema(
        question,
        datasource_id="pagila",
        allowed_schemas=("public",),
        allowed_tables=("public.actor", "public.film"),
        snapshot=snapshot,
        top_k=5,
        retrieval_runtime=runtime,
    )


def test_unauthorized_metadata_never_reaches_embedding_or_version() -> None:
    provider = SemanticEmbeddingProvider()
    runtime = _runtime(provider)

    first = _link(_snapshot(), runtime)
    changed = _link(
        _snapshot(
            replace(
                PAYROLL,
                comment="changed-private-secret-comment",
                aliases=("changed-private-secret-alias",),
            )
        ),
        runtime,
    )

    document_calls = tuple(
        call for call in provider.calls if call[0].startswith("{")
    )
    assert len(document_calls) == 1
    embedded_documents = "".join(document_calls[0])
    assert "private.payroll" not in embedded_documents
    assert "private-secret" not in embedded_documents
    assert first.retrieval_version_id == changed.retrieval_version_id
    assert first.retrieval_pool == changed.retrieval_pool
    assert first.candidate_tables == changed.candidate_tables


def test_wrong_retrieval_version_is_rejected_without_query_embedding() -> None:
    from app.schema_linking.index import EmbeddingIndexRegistry

    provider = SemanticEmbeddingProvider()
    source_registry = EmbeddingIndexRegistry()
    valid = source_registry.get_or_build_authorized(
        datasource_id="pagila",
        snapshot=_snapshot(),
        allowed_schemas=("public",),
        allowed_tables=("public.actor", "public.film"),
        provider=provider,
        semantic_version="semantic-v1",
    )
    calls_after_index = len(provider.calls)

    class WrongVersionRegistry(EmbeddingIndexRegistry):
        def get_or_build_authorized(self, **kwargs):
            del kwargs
            return replace(
                valid,
                retrieval_version=valid.retrieval_version.model_copy(
                    update={"semantic_version": "stale-semantic"}
                ),
            )

    with pytest.raises(
        ValueError,
        match=r"^schema linking context is invalid$",
    ):
        _link(
            _snapshot(),
            _runtime(provider, WrongVersionRegistry()),
        )

    assert len(provider.calls) == calls_after_index


def test_forged_unauthorized_index_document_cannot_become_candidate() -> None:
    from app.schema_linking.index import (
        EmbeddingIndex,
        EmbeddingIndexRegistry,
        SchemaDocument,
    )

    provider = SemanticEmbeddingProvider()
    source_registry = EmbeddingIndexRegistry()
    valid = source_registry.get_or_build_authorized(
        datasource_id="pagila",
        snapshot=_snapshot(),
        allowed_schemas=("public",),
        allowed_tables=("public.actor", "public.film"),
        provider=provider,
        semantic_version="semantic-v1",
    )
    forged_document = SchemaDocument(
        object_id="private.payroll",
        kind="table",
        text=json.dumps(
            {
                "kind": "table",
                "object_id": "private.payroll",
                "comment": "private-secret",
            }
        ),
        table_ids=("private.payroll",),
    )
    forged = EmbeddingIndex(
        retrieval_version=valid.retrieval_version,
        documents=(*valid.documents, forged_document),
        vectors=(*valid.vectors, (1.0, 0.0)),
    )

    class ForgedRegistry(EmbeddingIndexRegistry):
        def get_or_build_authorized(self, **kwargs):
            del kwargs
            return forged

    result = _link(
        _snapshot(),
        _runtime(provider, ForgedRegistry()),
        question="film",
    )

    assert result.retrieval_pool is not None
    assert result.retrieval_pool.mode == "bm25_only"
    assert (
        result.retrieval_pool.embedding_degradation
        == "invalid_response"
    )
    assert all(
        table.object_id != "private.payroll"
        for table in result.candidate_tables
    )


def test_authorized_embedding_evidence_informs_complexity_route() -> None:
    provider = SemanticEmbeddingProvider()
    result = _link(_snapshot(), _runtime(provider))

    decision = decide_complexity(
        "semantic-only-query",
        candidate_tables=result.candidate_tables,
        join_paths=result.join_paths,
        has_repair_history=False,
    )

    assert all(table.score > 0 for table in result.candidate_tables)
    assert decision.level is QueryComplexity.MEDIUM
    assert decision.schema_top_k == 10


def test_retrieval_pool_and_evidence_repr_hide_object_ids() -> None:
    provider = SemanticEmbeddingProvider()
    result = _link(_snapshot(), _runtime(provider))
    assert result.retrieval_pool is not None

    rendered = repr(result.retrieval_pool) + "".join(
        repr(evidence)
        for evidence in (
            *result.retrieval_pool.table_evidence,
            *result.retrieval_pool.field_evidence,
        )
    )

    assert "public.actor" not in rendered
    assert "public.film" not in rendered
    assert "private.payroll" not in rendered


def test_prepared_pool_cannot_be_reused_for_a_different_question() -> None:
    provider = SemanticEmbeddingProvider()
    runtime = _runtime(provider)
    first = _link(
        _snapshot(),
        runtime,
        question="film actor",
    )
    calls_after_first = len(provider.calls)

    with pytest.raises(
        ValueError,
        match=r"^schema linking context is invalid$",
    ):
        link_schema(
            "different-question",
            datasource_id="pagila",
            allowed_schemas=("public",),
            allowed_tables=("public.actor", "public.film"),
            snapshot=_snapshot(),
            top_k=5,
            retrieval_runtime=runtime,
            prepared_pool=first.retrieval_pool,
        )

    assert len(provider.calls) == calls_after_first


def test_prepared_pool_cannot_reorder_same_version_rerank_evidence() -> None:
    provider = SemanticEmbeddingProvider()
    runtime = _runtime(provider)
    first = _link(
        _snapshot(),
        runtime,
        question="film actor",
    )
    assert first.retrieval_pool is not None
    pool = first.retrieval_pool
    reversed_ids = tuple(reversed(pool.reranked_table_ids))
    evidence_by_id = {
        item.object_id: item for item in pool.rerank_evidence
    }
    forged = replace(
        pool,
        reranked_table_ids=reversed_ids,
        rerank_evidence=tuple(
            replace(
                evidence_by_id[object_id],
                rerank_rank=rank,
            )
            for rank, object_id in enumerate(
                reversed_ids,
                start=1,
            )
        ),
    )
    calls_after_first = len(provider.calls)

    with pytest.raises(
        ValueError,
        match=r"^schema linking context is invalid$",
    ):
        link_schema(
            "film actor",
            datasource_id="pagila",
            allowed_schemas=("public",),
            allowed_tables=("public.actor", "public.film"),
            snapshot=_snapshot(),
            top_k=5,
            retrieval_runtime=runtime,
            prepared_pool=forged,
        )

    assert len(provider.calls) == calls_after_first


def test_prepared_pool_requires_the_registered_request_local_object() -> None:
    provider = SemanticEmbeddingProvider()
    runtime = _runtime(provider)
    first = _link(_snapshot(), runtime)
    assert first.retrieval_pool is not None
    copied = replace(first.retrieval_pool)
    calls_after_first = len(provider.calls)

    with pytest.raises(
        ValueError,
        match=r"^schema linking context is invalid$",
    ):
        link_schema(
            "semantic-only-query",
            datasource_id="pagila",
            allowed_schemas=("public",),
            allowed_tables=("public.actor", "public.film"),
            snapshot=_snapshot(),
            top_k=5,
            retrieval_runtime=runtime,
            prepared_pool=copied,
        )

    assert len(provider.calls) == calls_after_first


def test_prepared_pool_provenance_is_not_shared_across_runtimes() -> None:
    provider = SemanticEmbeddingProvider()
    runtime = _runtime(provider)
    first = _link(_snapshot(), runtime)
    assert first.retrieval_pool is not None
    independent_runtime = replace(runtime)
    calls_after_first = len(provider.calls)

    assert not hasattr(runtime, "prepared_pools")
    with pytest.raises(
        ValueError,
        match=r"^schema linking context is invalid$",
    ):
        link_schema(
            "semantic-only-query",
            datasource_id="pagila",
            allowed_schemas=("public",),
            allowed_tables=("public.actor", "public.film"),
            snapshot=_snapshot(),
            top_k=5,
            retrieval_runtime=independent_runtime,
            prepared_pool=first.retrieval_pool,
        )

    assert len(provider.calls) == calls_after_first


def test_shallow_copied_runtime_gets_independent_pool_provenance() -> None:
    provider = SemanticEmbeddingProvider()
    runtime = _runtime(provider)
    first = _link(_snapshot(), runtime)
    assert first.retrieval_pool is not None
    copied_runtime = copy(runtime)
    calls_after_first = len(provider.calls)

    assert copied_runtime is not runtime
    with pytest.raises(
        ValueError,
        match=r"^schema linking context is invalid$",
    ):
        link_schema(
            "semantic-only-query",
            datasource_id="pagila",
            allowed_schemas=("public",),
            allowed_tables=("public.actor", "public.film"),
            snapshot=_snapshot(),
            top_k=5,
            retrieval_runtime=copied_runtime,
            prepared_pool=first.retrieval_pool,
        )

    assert len(provider.calls) == calls_after_first


@pytest.mark.parametrize(
    "changes",
    (
        {"mode": "forged"},
        {
            "mode": "bm25_only",
            "embedding_degradation": "forged",
        },
    ),
)
def test_retrieval_pool_rejects_open_ended_status_values(
    changes: dict[str, object],
) -> None:
    provider = SemanticEmbeddingProvider()
    result = _link(_snapshot(), _runtime(provider))
    assert result.retrieval_pool is not None

    with pytest.raises(
        ValueError,
        match=r"^schema retrieval pool is invalid$",
    ):
        replace(result.retrieval_pool, **changes)
