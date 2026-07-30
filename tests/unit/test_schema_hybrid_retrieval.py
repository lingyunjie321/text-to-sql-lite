import json
from dataclasses import replace

import pytest

from app.connectors.errors import ErrorType
from app.connectors.metadata import (
    TableMetadata,
    build_schema_snapshot,
)
from app.schema_linking.embedding import (
    EmbeddingError,
    EmbeddingProviderError,
)
from tests.unit.test_schema_embedding_index import (
    FILM,
    StubEmbeddingProvider,
    _authorized,
    _snapshot,
    _version,
)


ACTOR = TableMetadata(
    schema_name="public",
    table_name="actor",
    relation_kind="table",
    comment="Performers",
    columns=(),
)
HYBRID_FILM = replace(
    FILM,
    comment="Available films",
    aliases=(),
    columns=(),
)
HYBRID_SNAPSHOT = build_schema_snapshot(
    tables=(HYBRID_FILM, ACTOR),
    primary_keys=(),
    foreign_keys=(),
    unique_constraints=(),
    unique_indexes=(),
)


class SemanticEmbeddingProvider(StubEmbeddingProvider):
    def __init__(
        self,
        *,
        query_error: EmbeddingProviderError | None = None,
    ) -> None:
        super().__init__()
        self.query_error = query_error

    def embed(
        self,
        texts: tuple[str, ...],
        *,
        timeout_seconds: float | None = None,
    ) -> tuple[tuple[float, ...], ...]:
        self.calls.append(tuple(texts))
        self.timeouts.append(timeout_seconds)
        vectors: list[tuple[float, ...]] = []
        for text in texts:
            if text.startswith("{"):
                object_id = json.loads(text)["object_id"]
                vectors.append(
                    (1.0, 0.0)
                    if object_id == "public.film"
                    else (0.5, 0.5)
                    if object_id == "public.actor"
                    else (0.0, 1.0)
                )
            else:
                if self.query_error is not None:
                    raise self.query_error
                vectors.append((1.0, 0.0))
        return tuple(vectors)


def _runtime(provider: StubEmbeddingProvider):
    from app.schema_linking.index import (
        EmbeddingIndexRegistry,
        RetrievalRuntime,
    )

    return RetrievalRuntime(
        provider=provider,
        registry=EmbeddingIndexRegistry(),
        semantic_version="semantic-v1",
    )


def _link(
    provider: StubEmbeddingProvider,
    *,
    top_k: int = 5,
    prepared_pool=None,
    question: str = "semantic-only-query",
):
    from app.schema_linking import link_schema

    return link_schema(
        question,
        datasource_id="pagila",
        allowed_schemas=("public",),
        allowed_tables=("public.actor", "public.film"),
        snapshot=HYBRID_SNAPSHOT,
        top_k=top_k,  # type: ignore[arg-type]
        retrieval_runtime=_runtime(provider),
        prepared_pool=prepared_pool,
    )


def test_cosine_uses_max_table_or_field_document_score() -> None:
    from app.schema_linking.fusion import rank_embedding_index
    from app.schema_linking.index import (
        EmbeddingIndex,
        build_authorized_schema_documents,
    )

    snapshot = build_schema_snapshot(
        tables=(
            replace(
                FILM,
                aliases=(),
                columns=(FILM.columns[-1],),
            ),
            ACTOR,
        ),
        primary_keys=(),
        foreign_keys=(),
        unique_constraints=(),
        unique_indexes=(),
    )
    documents = build_authorized_schema_documents(
        snapshot=snapshot,
        allowed_schemas=("public",),
        allowed_tables=("public.actor", "public.film"),
    )
    vectors_by_id = {
        "public.actor": (0.6, 0.8),
        "public.film": (0.0, 1.0),
        "public.film.title": (1.0, 0.0),
    }
    version = _version(provider=StubEmbeddingProvider())
    version = version.model_copy(
        update={"schema_version": snapshot.schema_version}
    )
    index = EmbeddingIndex(
        retrieval_version=version,
        documents=documents,
        vectors=tuple(
            vectors_by_id[document.object_id]
            for document in documents
        ),
    )

    ranking = rank_embedding_index(
        index=index,
        query_vector=(1.0, 0.0),
        authorized_snapshot=snapshot,
    )

    assert tuple(
        evidence.object_id for evidence in ranking.table_ranks
    ) == ("public.film", "public.actor")
    assert tuple(
        evidence.similarity for evidence in ranking.table_ranks
    ) == pytest.approx((1.0, 0.6))
    assert ranking.table_ranks[0].source_document_id == (
        "public.film.title"
    )
    assert tuple(
        evidence.object_id for evidence in ranking.field_ranks
    ) == ("public.film.title",)


def test_cosine_aggregation_does_not_sum_multiple_fields() -> None:
    from app.connectors.metadata import ColumnMetadata
    from app.schema_linking.fusion import rank_embedding_index
    from app.schema_linking.index import (
        EmbeddingIndex,
        build_authorized_schema_documents,
    )

    title = FILM.columns[-1]
    description = ColumnMetadata(
        schema_name="public",
        table_name="film",
        column_name="description",
        ordinal_position=4,
        data_type="text",
        formatted_type="text",
        nullable=True,
        comment=None,
    )
    snapshot = build_schema_snapshot(
        tables=(
            replace(
                FILM,
                aliases=(),
                columns=(title, description),
            ),
            ACTOR,
        ),
        primary_keys=(),
        foreign_keys=(),
        unique_constraints=(),
        unique_indexes=(),
    )
    documents = build_authorized_schema_documents(
        snapshot=snapshot,
        allowed_schemas=("public",),
        allowed_tables=("public.actor", "public.film"),
    )
    vectors_by_id = {
        "public.actor": (1.0, 0.0),
        "public.film": (0.0, 1.0),
        "public.film.description": (0.8, 0.6),
        "public.film.title": (0.8, 0.6),
    }
    version = _version().model_copy(
        update={"schema_version": snapshot.schema_version}
    )
    index = EmbeddingIndex(
        retrieval_version=version,
        documents=documents,
        vectors=tuple(
            vectors_by_id[document.object_id]
            for document in documents
        ),
    )

    ranking = rank_embedding_index(
        index=index,
        query_vector=(1.0, 0.0),
        authorized_snapshot=snapshot,
    )

    assert tuple(
        item.object_id for item in ranking.table_ranks
    ) == ("public.actor", "public.film")
    assert tuple(
        item.similarity for item in ranking.table_ranks
    ) == pytest.approx((1.0, 0.8))


def test_cosine_rejects_invalid_vector_on_relation_document() -> None:
    from app.schema_linking.fusion import rank_embedding_index
    from app.schema_linking.index import (
        EmbeddingIndex,
        EmbeddingIndexBuildError,
        build_authorized_schema_documents,
    )

    snapshot = _snapshot()
    authorized = _authorized()
    documents = build_authorized_schema_documents(
        snapshot=snapshot,
        allowed_schemas=("public",),
        allowed_tables=("public.language", "public.film"),
    )
    version = _version()
    index = EmbeddingIndex(
        retrieval_version=version,
        documents=documents,
        vectors=tuple(
            (0.0, 0.0)
            if document.kind == "foreign_key"
            else (1.0, 0.0)
            for document in documents
        ),
    )

    with pytest.raises(EmbeddingIndexBuildError):
        rank_embedding_index(
            index=index,
            query_vector=(1.0, 0.0),
            authorized_snapshot=authorized,
        )


@pytest.mark.parametrize(
    "mutation",
    ("missing_relation", "forged_relation", "extra_relation"),
)
def test_cosine_requires_exact_canonical_schema_documents(
    mutation: str,
) -> None:
    from app.schema_linking.fusion import rank_embedding_index
    from app.schema_linking.index import (
        EmbeddingIndex,
        EmbeddingIndexBuildError,
        SchemaDocument,
        build_authorized_schema_documents,
    )

    snapshot = _snapshot()
    authorized = _authorized()
    documents = list(
        build_authorized_schema_documents(
            snapshot=snapshot,
            allowed_schemas=("public",),
            allowed_tables=("public.language", "public.film"),
        )
    )
    relation_index = next(
        index
        for index, document in enumerate(documents)
        if document.kind == "foreign_key"
    )
    if mutation == "missing_relation":
        documents.pop(relation_index)
    elif mutation == "forged_relation":
        documents[relation_index] = replace(
            documents[relation_index],
            object_id="foreign_key:forged",
            text='{"kind":"foreign_key","object_id":"forged"}',
        )
    else:
        documents.append(
            SchemaDocument(
                object_id="foreign_key:extra",
                kind="foreign_key",
                text=(
                    '{"kind":"foreign_key",'
                    '"object_id":"foreign_key:extra"}'
                ),
                table_ids=("public.film", "public.language"),
            )
        )
    index = EmbeddingIndex(
        retrieval_version=_version(),
        documents=tuple(documents),
        vectors=tuple((1.0, 0.0) for _ in documents),
    )

    with pytest.raises(EmbeddingIndexBuildError):
        rank_embedding_index(
            index=index,
            query_vector=(1.0, 0.0),
            authorized_snapshot=authorized,
        )


def test_hybrid_retrieval_can_recall_semantic_only_table() -> None:
    from app.schema_linking.index import (
        EmbeddingIndexRegistry,
        RetrievalRuntime,
    )
    from app.schema_linking import link_schema

    provider = SemanticEmbeddingProvider()
    runtime = RetrievalRuntime(
        provider=provider,
        registry=EmbeddingIndexRegistry(),
        semantic_version="semantic-v1",
    )

    result = link_schema(
        "semantic-only-query",
        datasource_id="pagila",
        allowed_schemas=("public",),
        allowed_tables=("public.actor", "public.film"),
        snapshot=HYBRID_SNAPSHOT,
        top_k=5,
        retrieval_runtime=runtime,
    )

    assert result.candidate_tables[0].object_id == "public.film"
    assert result.candidate_tables[0].score > 0
    assert result.retrieval_pool is not None
    assert result.retrieval_pool.mode == "hybrid"
    assert result.retrieval_pool.embedding_degradation is None
    assert result.retrieval_version_id == (
        result.retrieval_pool.retrieval_version_id
    )
    assert len(provider.calls) == 2

    from app.workflow import QueryComplexity, decide_complexity

    decision = decide_complexity(
        "semantic-only-query",
        candidate_tables=result.candidate_tables,
        join_paths=result.join_paths,
        has_repair_history=False,
    )
    assert decision.level is QueryComplexity.MEDIUM
    assert decision.schema_top_k == 10


def test_linker_derives_grain_only_from_complete_primary_key_evidence() -> None:
    from app.schema_linking import link_schema

    result = link_schema(
        "film id",
        datasource_id="pagila",
        allowed_schemas=("public",),
        allowed_tables=("public.language", "public.film"),
        snapshot=_snapshot(),
        top_k=5,
        retrieval_runtime=_runtime(StubEmbeddingProvider()),
    )

    assert result.retrieval_pool is not None
    evidence = {
        item.object_id: item
        for item in result.retrieval_pool.rerank_evidence
    }
    assert evidence["public.film"].grain_key_coverage is True
    assert evidence["public.language"].grain_key_coverage is False


def test_materialization_reuses_probe_pool_without_embedding_call() -> None:
    from app.schema_linking.index import (
        EmbeddingIndexRegistry,
        RetrievalRuntime,
    )
    from app.schema_linking import link_schema

    provider = SemanticEmbeddingProvider()
    runtime = RetrievalRuntime(
        provider=provider,
        registry=EmbeddingIndexRegistry(),
        semantic_version="semantic-v1",
    )
    probe = link_schema(
        "semantic-only-query",
        datasource_id="pagila",
        allowed_schemas=("public",),
        allowed_tables=("public.actor", "public.film"),
        snapshot=HYBRID_SNAPSHOT,
        top_k=20,
        retrieval_runtime=runtime,
    )
    calls_after_probe = len(provider.calls)

    materialized = link_schema(
        "semantic-only-query",
        datasource_id="pagila",
        allowed_schemas=("public",),
        allowed_tables=("public.actor", "public.film"),
        snapshot=HYBRID_SNAPSHOT,
        top_k=5,
        retrieval_runtime=runtime,
        prepared_pool=probe.retrieval_pool,
    )

    assert len(provider.calls) == calls_after_probe
    assert materialized.retrieval_pool is probe.retrieval_pool
    assert materialized.retrieval_version_id == (
        probe.retrieval_version_id
    )
    assert len(materialized.candidate_tables) <= 5


@pytest.mark.parametrize(
    ("error_type", "code", "degradation"),
    (
        (ErrorType.TIMEOUT, "EMBEDDING_TIMEOUT", "timeout"),
        (
            ErrorType.CONNECTION_ERROR,
            "EMBEDDING_CONNECTION_ERROR",
            "connection",
        ),
        (
            ErrorType.UNKNOWN,
            "EMBEDDING_RATE_LIMITED",
            "rate_limited",
        ),
        (
            ErrorType.UNKNOWN,
            "EMBEDDING_INVALID_RESPONSE",
            "invalid_response",
        ),
    ),
)
def test_embedding_query_failure_degrades_to_same_version_bm25(
    error_type: ErrorType,
    code: str,
    degradation: str,
) -> None:
    provider = SemanticEmbeddingProvider(
        query_error=EmbeddingProviderError(
            EmbeddingError(
                error_type=error_type,
                code=code,
                retryable=False,
                public_message="fixed embedding failure",
            )
        )
    )

    result = _link(provider, question="film")

    assert result.retrieval_pool is not None
    assert result.retrieval_pool.mode == "bm25_only"
    assert result.retrieval_pool.embedding_degradation == degradation
    assert tuple(
        table.object_id for table in result.candidate_tables
    ) == ("public.film", "public.actor")
    assert result.retrieval_version_id is not None


@pytest.mark.parametrize(
    "code",
    ("EMBEDDING_HTTP_ERROR", "EMBEDDING_INVALID_INPUT"),
)
def test_non_degradable_embedding_error_fails_closed(
    code: str,
) -> None:
    provider = SemanticEmbeddingProvider(
        query_error=EmbeddingProviderError(
            EmbeddingError(
                error_type=ErrorType.UNKNOWN,
                code=code,
                retryable=False,
                public_message="fixed embedding failure",
            )
        )
    )

    with pytest.raises(EmbeddingProviderError) as captured:
        _link(provider, question="film")

    assert captured.value.details.code == code


def test_embedding_failure_without_positive_bm25_path_fails_closed() -> None:
    provider = SemanticEmbeddingProvider(
        query_error=EmbeddingProviderError(
            EmbeddingError(
                error_type=ErrorType.TIMEOUT,
                code="EMBEDDING_TIMEOUT",
                retryable=False,
                public_message="fixed embedding failure",
            )
        )
    )

    with pytest.raises(EmbeddingProviderError) as captured:
        _link(provider)

    assert captured.value.details.code == "EMBEDDING_TIMEOUT"


def test_prepared_pool_rejects_schema_or_provider_version_mismatch() -> None:
    from app.schema_linking.index import (
        EmbeddingIndexRegistry,
        RetrievalRuntime,
    )
    from app.schema_linking import link_schema

    provider = SemanticEmbeddingProvider()
    runtime = RetrievalRuntime(
        provider=provider,
        registry=EmbeddingIndexRegistry(),
        semantic_version="semantic-v1",
    )
    probe = link_schema(
        "semantic-only-query",
        datasource_id="pagila",
        allowed_schemas=("public",),
        allowed_tables=("public.actor", "public.film"),
        snapshot=HYBRID_SNAPSHOT,
        top_k=20,
        retrieval_runtime=runtime,
    )

    with pytest.raises(
        ValueError,
        match=r"^schema linking context is invalid$",
    ):
        changed_snapshot = build_schema_snapshot(
            tables=(
                replace(HYBRID_FILM, comment="changed"),
                ACTOR,
            ),
            primary_keys=(),
            foreign_keys=(),
            unique_constraints=(),
            unique_indexes=(),
        )
        link_schema(
            "semantic-only-query",
            datasource_id="pagila",
            allowed_schemas=("public",),
            allowed_tables=("public.actor", "public.film"),
            snapshot=changed_snapshot,
            top_k=5,
            retrieval_runtime=runtime,
            prepared_pool=probe.retrieval_pool,
        )
