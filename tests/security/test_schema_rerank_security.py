from dataclasses import replace

from app.connectors.metadata import (
    TableMetadata,
    build_schema_snapshot,
)
from app.schema_linking import link_schema
from tests.unit.test_schema_embedding_index import PAYROLL
from tests.unit.test_schema_hybrid_retrieval import (
    ACTOR,
    HYBRID_FILM,
    SemanticEmbeddingProvider,
    _runtime,
)


AUTHORIZED_FILM = replace(
    HYBRID_FILM,
    aliases=("catalog",),
)


def _snapshot(private: TableMetadata = PAYROLL):
    return build_schema_snapshot(
        tables=(AUTHORIZED_FILM, ACTOR, private),
        primary_keys=(),
        foreign_keys=(),
        unique_constraints=(),
        unique_indexes=(),
    )


def _link(snapshot):
    return link_schema(
        "catalog",
        datasource_id="pagila",
        allowed_schemas=("public",),
        allowed_tables=("public.actor", "public.film"),
        snapshot=snapshot,
        top_k=5,
        retrieval_runtime=_runtime(
            SemanticEmbeddingProvider()
        ),
    )


def test_unapproved_scope_alias_cannot_affect_rerank_or_version() -> None:
    first = _link(_snapshot())
    changed = _link(
        _snapshot(
            replace(
                PAYROLL,
                aliases=("catalog", "private-rerank-secret"),
                comment="private-rerank-secret",
            )
        )
    )

    assert first.retrieval_pool is not None
    assert changed.retrieval_pool is not None
    assert (
        first.retrieval_pool.reranked_table_ids
        == changed.retrieval_pool.reranked_table_ids
    )
    assert (
        first.retrieval_pool.rerank_evidence
        == changed.retrieval_pool.rerank_evidence
    )
    assert first.retrieval_version_id == changed.retrieval_version_id
    film = next(
        item
        for item in first.retrieval_pool.rerank_evidence
        if item.object_id == "public.film"
    )
    assert film.approved_alias_count == 1


def test_rerank_repr_hides_authorized_and_private_object_ids() -> None:
    result = _link(_snapshot())
    assert result.retrieval_pool is not None

    rendered = repr(result.retrieval_pool) + "".join(
        repr(item)
        for item in result.retrieval_pool.rerank_evidence
    )

    assert "public.film" not in rendered
    assert "public.actor" not in rendered
    assert "private.payroll" not in rendered
    assert "private-rerank-secret" not in rendered
