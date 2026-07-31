import json
import math
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError, replace

import pytest

from app.connectors.metadata import (
    ColumnMetadata,
    ForeignKeyMetadata,
    PrimaryKeyMetadata,
    TableMetadata,
    build_schema_snapshot,
)


def _column(
    table_name: str,
    column_name: str,
    position: int,
    *,
    aliases: tuple[str, ...] = (),
    comment: str | None = None,
    formatted_type: str = "integer",
) -> ColumnMetadata:
    return ColumnMetadata(
        schema_name="public",
        table_name=table_name,
        column_name=column_name,
        ordinal_position=position,
        data_type="int4",
        formatted_type=formatted_type,
        nullable=False,
        comment=comment,
        aliases=aliases,
    )


FILM = TableMetadata(
    schema_name="public",
    table_name="film",
    relation_kind="table",
    comment="Available films",
    aliases=("影片", "movies"),
    columns=(
        _column("film", "film_id", 1),
        _column(
            "film",
            "language_id",
            2,
            comment="Spoken language",
        ),
        _column(
            "film",
            "title",
            3,
            aliases=("片名", "name"),
            comment="Film title",
            formatted_type="character varying(255)",
        ),
    ),
)
LANGUAGE = TableMetadata(
    schema_name="public",
    table_name="language",
    relation_kind="table",
    comment=None,
    columns=(_column("language", "language_id", 1),),
)
PAYROLL = TableMetadata(
    schema_name="private",
    table_name="payroll",
    relation_kind="table",
    comment="never-index-secret-comment",
    aliases=("never-index-secret-alias",),
    columns=(
        ColumnMetadata(
            schema_name="private",
            table_name="payroll",
            column_name="salary",
            ordinal_position=1,
            data_type="numeric",
            formatted_type="numeric",
            nullable=False,
            comment="never-index-secret-field",
        ),
    ),
)
FILM_PK = PrimaryKeyMetadata(
    constraint_name="film_pkey",
    schema_name="public",
    table_name="film",
    columns=("film_id",),
)
FILM_LANGUAGE_FK = ForeignKeyMetadata(
    constraint_name="film_language_id_fkey",
    source_schema="public",
    source_table="film",
    source_columns=("language_id",),
    target_schema="public",
    target_table="language",
    target_columns=("language_id",),
)
PRIVATE_FK = ForeignKeyMetadata(
    constraint_name="payroll_film_fkey",
    source_schema="private",
    source_table="payroll",
    source_columns=("salary",),
    target_schema="public",
    target_table="film",
    target_columns=("film_id",),
)


def _snapshot(
    *,
    film: TableMetadata = FILM,
    payroll: TableMetadata = PAYROLL,
):
    return build_schema_snapshot(
        tables=(payroll, LANGUAGE, film),
        primary_keys=(FILM_PK,),
        foreign_keys=(PRIVATE_FK, FILM_LANGUAGE_FK),
        unique_constraints=(),
        unique_indexes=(),
    )


class StubEmbeddingProvider:
    def __init__(
        self,
        *,
        model_id: str = "embedding-v1",
        dimension: int = 2,
        vector: tuple[float, ...] = (3.0, 4.0),
        error: Exception | None = None,
        provider_config_sha256: str = "a" * 64,
    ) -> None:
        self.model_id = model_id
        self.dimension = dimension
        self.vector = vector
        self.error = error
        self.provider_config_sha256 = provider_config_sha256
        self.calls: list[tuple[str, ...]] = []
        self.timeouts: list[float | None] = []

    def embed(
        self,
        texts: tuple[str, ...],
        *,
        timeout_seconds: float | None = None,
    ) -> tuple[tuple[float, ...], ...]:
        self.calls.append(tuple(texts))
        self.timeouts.append(timeout_seconds)
        if self.error is not None:
            raise self.error
        return tuple(self.vector for _ in texts)


def _authorized():
    from app.schema_linking.index import authorize_schema_snapshot

    return authorize_schema_snapshot(
        snapshot=_snapshot(),
        allowed_schemas=("public",),
        allowed_tables=("public.language", "public.film"),
    )


def _version(
    *,
    provider: StubEmbeddingProvider | None = None,
    semantic_version: str = "semantic-v1",
    document_version: str = "schema-doc-v1",
    fusion_version: str = "rrf-v1",
    rerank_version: str = "schema-rerank-v2",
):
    from app.schema_linking.index import build_retrieval_version

    return build_retrieval_version(
        datasource_id="pagila",
        snapshot=_snapshot(),
        allowed_schemas=("public",),
        allowed_tables=("public.language", "public.film"),
        provider=provider or StubEmbeddingProvider(),
        semantic_version=semantic_version,
        document_version=document_version,
        fusion_version=fusion_version,
        rerank_version=rerank_version,
    )


def _registry_get(
    registry,
    provider: StubEmbeddingProvider,
    *,
    snapshot=None,
    allowed_schemas: tuple[str, ...] = ("public",),
    allowed_tables: tuple[str, ...] = (
        "public.language",
        "public.film",
    ),
    semantic_version: str = "semantic-v1",
    deadline_at: float | None = None,
    clock=time.monotonic,
):
    return registry.get_or_build_authorized(
        datasource_id="pagila",
        snapshot=snapshot or _snapshot(),
        allowed_schemas=allowed_schemas,
        allowed_tables=allowed_tables,
        provider=provider,
        semantic_version=semantic_version,
        deadline_at=deadline_at,
        clock=clock,
    )


def _wait_for_registry_waiters(
    registry,
    expected: int,
) -> None:
    deadline = time.monotonic() + 2
    while registry.waiting_build_count < expected:
        if time.monotonic() >= deadline:
            pytest.fail("registry waiters did not reach the expected count")
        time.sleep(0.001)


def test_schema_doc_v1_serializes_exact_authorized_objects() -> None:
    from app.schema_linking.index import (
        build_authorized_schema_documents,
    )

    documents = build_authorized_schema_documents(
        snapshot=_snapshot(),
        allowed_schemas=("public",),
        allowed_tables=("public.language", "public.film"),
    )

    assert tuple(document.object_id for document in documents) == (
        "public.film",
        "public.language",
        "public.film.film_id",
        "public.film.language_id",
        "public.film.title",
        "public.language.language_id",
        "primary_key:public.film(film_id)",
        (
            "foreign_key:public.film(language_id)"
            "->public.language(language_id)"
        ),
    )
    assert tuple(document.kind for document in documents) == (
        "table",
        "table",
        "field",
        "field",
        "field",
        "field",
        "primary_key",
        "foreign_key",
    )
    assert documents[0].text == (
        '{"aliases":["movies","影片"],"comment":"Available films",'
        '"kind":"table","object_id":"public.film","schema":"public",'
        '"table":"film"}'
    )
    assert documents[4].text == (
        '{"aliases":["name","片名"],"column":"title",'
        '"comment":"Film title","kind":"field",'
        '"object_id":"public.film.title","schema":"public",'
        '"table":"film","type":"character varying(255)"}'
    )
    assert json.loads(documents[-2].text) == {
        "columns": ["film_id"],
        "kind": "primary_key",
        "object_id": "primary_key:public.film(film_id)",
        "table": "public.film",
    }
    assert json.loads(documents[-1].text) == {
        "kind": "foreign_key",
        "object_id": (
            "foreign_key:public.film(language_id)"
            "->public.language(language_id)"
        ),
        "source": {
            "columns": ["language_id"],
            "table": "public.film",
        },
        "target": {
            "columns": ["language_id"],
            "table": "public.language",
        },
    }
    assert all(
        "never-index-secret" not in document.text
        for document in documents
    )


def test_documents_are_stable_for_order_and_alias_order() -> None:
    from app.schema_linking.index import (
        build_authorized_schema_documents,
    )

    reordered_film = replace(
        FILM,
        aliases=tuple(reversed(FILM.aliases)),
        columns=tuple(
            replace(column, aliases=tuple(reversed(column.aliases)))
            for column in FILM.columns
        ),
    )
    reordered = build_schema_snapshot(
        tables=(reordered_film, LANGUAGE),
        primary_keys=(FILM_PK,),
        foreign_keys=(FILM_LANGUAGE_FK,),
        unique_constraints=(),
        unique_indexes=(),
    )

    assert build_authorized_schema_documents(
        snapshot=reordered,
        allowed_schemas=("public",),
        allowed_tables=("public.language", "public.film"),
    ) == build_authorized_schema_documents(
        snapshot=_snapshot(),
        allowed_schemas=("public",),
        allowed_tables=("public.language", "public.film"),
    )


def test_authorized_change_changes_documents_and_version() -> None:
    from app.schema_linking.index import (
        build_authorized_schema_documents,
        build_retrieval_version,
    )

    changed_raw = _snapshot(
        film=replace(FILM, comment="Changed authorized comment")
    )
    provider = StubEmbeddingProvider()

    before_version = build_retrieval_version(
        datasource_id="pagila",
        snapshot=_snapshot(),
        allowed_schemas=("public",),
        allowed_tables=("public.film", "public.language"),
        provider=provider,
        semantic_version="semantic-v1",
    )
    after_version = build_retrieval_version(
        datasource_id="pagila",
        snapshot=changed_raw,
        allowed_schemas=("public",),
        allowed_tables=("public.film", "public.language"),
        provider=provider,
        semantic_version="semantic-v1",
    )

    assert build_authorized_schema_documents(
        snapshot=changed_raw,
        allowed_schemas=("public",),
        allowed_tables=("public.film", "public.language"),
    ) != build_authorized_schema_documents(
        snapshot=_snapshot(),
        allowed_schemas=("public",),
        allowed_tables=("public.film", "public.language"),
    )
    assert (
        after_version.retrieval_version_id
        != before_version.retrieval_version_id
    )


def test_unauthorized_change_cannot_change_documents_or_version() -> None:
    from app.schema_linking.index import (
        build_authorized_schema_documents,
        build_retrieval_version,
    )

    changed_raw = _snapshot(
        payroll=replace(
            PAYROLL,
            comment="different-hidden-comment",
            aliases=("different-hidden-alias",),
        )
    )
    provider = StubEmbeddingProvider()

    before_version = build_retrieval_version(
        datasource_id="pagila",
        snapshot=_snapshot(),
        allowed_schemas=("public",),
        allowed_tables=("public.film", "public.language"),
        provider=provider,
        semantic_version="semantic-v1",
    )
    after_version = build_retrieval_version(
        datasource_id="pagila",
        snapshot=changed_raw,
        allowed_schemas=("public",),
        allowed_tables=("public.film", "public.language"),
        provider=provider,
        semantic_version="semantic-v1",
    )

    assert build_authorized_schema_documents(
        snapshot=changed_raw,
        allowed_schemas=("public",),
        allowed_tables=("public.film", "public.language"),
    ) == build_authorized_schema_documents(
        snapshot=_snapshot(),
        allowed_schemas=("public",),
        allowed_tables=("public.film", "public.language"),
    )
    assert (
        after_version.retrieval_version_id
        == before_version.retrieval_version_id
    )


@pytest.mark.parametrize(
    ("change", "expected_field"),
    (
        ({"datasource_id": "other"}, "datasource_id"),
        (
            {"authorization_scope_sha256": "b" * 64},
            "authorization_scope_sha256",
        ),
        ({"schema_version": "b" * 64}, "schema_version"),
        ({"semantic_version": "semantic-v2"}, "semantic_version"),
        ({"embedding_model": "embedding-v2"}, "embedding_model"),
        ({"embedding_dimension": 3}, "embedding_dimension"),
        ({"document_version": "schema-doc-v2"}, "document_version"),
        ({"fusion_version": "rrf-v2"}, "fusion_version"),
        ({"rerank_version": "schema-rerank-v3"}, "rerank_version"),
    ),
)
def test_retrieval_version_changes_for_every_contract_component(
    change: dict[str, object],
    expected_field: str,
) -> None:
    version = _version()
    changed = version.model_copy(update=change)

    assert getattr(changed, expected_field) != getattr(
        version,
        expected_field,
    )
    assert changed.retrieval_version_id != version.retrieval_version_id


def test_scope_hash_is_stable_for_equivalent_scope() -> None:
    from app.schema_linking.index import authorization_scope_sha256

    first = authorization_scope_sha256(
        allowed_schemas=("public", "public"),
        allowed_tables=("public.language", "public.film"),
    )
    second = authorization_scope_sha256(
        allowed_schemas=("public",),
        allowed_tables=(
            "public.film",
            "public.language",
            "public.film",
        ),
    )

    assert first == second
    assert len(first) == 64


def test_build_index_batches_and_normalizes_vectors() -> None:
    from app.schema_linking.index import EmbeddingIndexRegistry

    tables = tuple(
        TableMetadata(
            schema_name="public",
            table_name=f"table_{index:02d}",
            relation_kind="table",
            comment=None,
            columns=(),
        )
        for index in range(65)
    )
    snapshot = build_schema_snapshot(
        tables=tables,
        primary_keys=(),
        foreign_keys=(),
        unique_constraints=(),
        unique_indexes=(),
    )
    allowed_tables = tuple(
        f"public.{table.table_name}" for table in tables
    )
    provider = StubEmbeddingProvider()
    registry = EmbeddingIndexRegistry()

    index = _registry_get(
        registry,
        provider=provider,
        snapshot=snapshot,
        allowed_tables=allowed_tables,
    )

    from app.schema_linking.index import INDEX_EMBEDDING_BATCH_SIZE
    batch_sizes = [len(call) for call in provider.calls]
    assert sum(batch_sizes) == len(index.documents)
    assert all(bs <= INDEX_EMBEDDING_BATCH_SIZE for bs in batch_sizes)
    assert tuple(
        text for call in provider.calls for text in call
    ) == tuple(document.text for document in index.documents)
    assert len(index.vectors) == 65
    assert index.vectors[0] == pytest.approx((0.6, 0.8))
    assert math.hypot(*index.vectors[0]) == pytest.approx(1.0)
    with pytest.raises(FrozenInstanceError):
        index.vectors = ()  # type: ignore[misc]


def test_registry_cache_hit_returns_same_index_and_touches_lru() -> None:
    from app.schema_linking.index import EmbeddingIndexRegistry

    provider = StubEmbeddingProvider()
    registry = EmbeddingIndexRegistry(max_entries=2)

    first = _registry_get(registry, provider)
    second = _registry_get(registry, provider)

    assert second is first
    assert len(provider.calls) == 1
    assert registry.resident_version_ids == (
        first.retrieval_version_id,
    )


def test_registry_version_binds_safe_provider_configuration() -> None:
    from app.schema_linking.index import EmbeddingIndexRegistry

    first_provider = StubEmbeddingProvider(
        vector=(1.0, 0.0),
        provider_config_sha256="a" * 64,
    )
    second_provider = StubEmbeddingProvider(
        vector=(0.0, 1.0),
        provider_config_sha256="b" * 64,
    )
    registry = EmbeddingIndexRegistry()

    first = _registry_get(registry, first_provider)
    second = _registry_get(registry, second_provider)

    assert second is not first
    assert second.retrieval_version_id != first.retrieval_version_id
    assert len(first_provider.calls) == 1
    assert len(second_provider.calls) == 1


def test_registry_caps_builder_call_to_remaining_deadline() -> None:
    from app.schema_linking.index import EmbeddingIndexRegistry

    provider = StubEmbeddingProvider()
    registry = EmbeddingIndexRegistry()

    _registry_get(
        registry,
        provider,
        deadline_at=100.0,
        clock=lambda: 97.5,
    )

    assert provider.timeouts == [2.5]


def test_registry_concurrent_first_build_runs_one_builder() -> None:
    from app.schema_linking.index import EmbeddingIndexRegistry

    release = threading.Event()
    started = threading.Event()

    class BlockingProvider(StubEmbeddingProvider):
        def embed(
            self,
            texts: tuple[str, ...],
            *,
            timeout_seconds: float | None = None,
        ) -> tuple[tuple[float, ...], ...]:
            self.calls.append(tuple(texts))
            self.timeouts.append(timeout_seconds)
            started.set()
            assert release.wait(timeout=2)
            return tuple(self.vector for _ in texts)

    provider = BlockingProvider()
    registry = EmbeddingIndexRegistry()
    barrier = threading.Barrier(5)

    def get_index():
        barrier.wait(timeout=2)
        return _registry_get(registry, provider)

    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(get_index) for _ in range(4)]
        barrier.wait(timeout=2)
        assert started.wait(timeout=2)
        _wait_for_registry_waiters(registry, 3)
        release.set()
        results = [future.result(timeout=2) for future in futures]

    assert len(provider.calls) == 1
    assert all(result is results[0] for result in results)


def test_registry_waiter_respects_its_own_deadline() -> None:
    from app.schema_linking.embedding import EmbeddingProviderError
    from app.schema_linking.index import EmbeddingIndexRegistry

    release = threading.Event()
    started = threading.Event()

    class BlockingProvider(StubEmbeddingProvider):
        def embed(
            self,
            texts: tuple[str, ...],
            *,
            timeout_seconds: float | None = None,
        ) -> tuple[tuple[float, ...], ...]:
            self.calls.append(tuple(texts))
            self.timeouts.append(timeout_seconds)
            started.set()
            assert release.wait(timeout=2)
            return tuple(self.vector for _ in texts)

    provider = BlockingProvider()
    registry = EmbeddingIndexRegistry()
    with ThreadPoolExecutor(max_workers=1) as executor:
        builder = executor.submit(
            _registry_get,
            registry,
            provider,
        )
        assert started.wait(timeout=2)
        with pytest.raises(EmbeddingProviderError) as captured:
            _registry_get(
                registry,
                provider,
                deadline_at=time.monotonic() + 0.01,
            )
        release.set()
        builder.result(timeout=2)

    assert captured.value.details.code == "EMBEDDING_TIMEOUT"
    assert registry.waiting_build_count == 0
    assert len(provider.calls) == 1


def test_failed_build_is_not_published_and_can_retry() -> None:
    from app.schema_linking.index import (
        EmbeddingIndexBuildError,
        EmbeddingIndexRegistry,
    )

    provider = StubEmbeddingProvider(
        error=RuntimeError("private partial build detail")
    )
    registry = EmbeddingIndexRegistry()

    with pytest.raises(EmbeddingIndexBuildError) as captured:
        _registry_get(registry, provider)

    assert registry.resident_version_ids == ()
    assert "private" not in (
        str(captured.value) + repr(captured.value)
    )

    provider.error = None
    index = _registry_get(registry, provider)

    assert index.documents
    assert registry.resident_version_ids == (
        index.retrieval_version_id,
    )


@pytest.mark.parametrize(
    "vector",
    (
        (1.0,),
        (1.0, 0.0, 0.0),
        (True, 0.0),
        (float("nan"), 0.0),
        (float("inf"), 0.0),
        (0.0, -0.0),
    ),
)
def test_index_revalidates_provider_vectors(
    vector: tuple[object, ...],
) -> None:
    from app.schema_linking.index import (
        EmbeddingIndexBuildError,
        EmbeddingIndexRegistry,
    )

    provider = StubEmbeddingProvider(
        vector=vector,  # type: ignore[arg-type]
    )
    registry = EmbeddingIndexRegistry()

    with pytest.raises(EmbeddingIndexBuildError):
        _registry_get(registry, provider)

    assert registry.resident_version_ids == ()


@pytest.mark.parametrize("changed_property", ("model_id", "dimension"))
def test_registry_rejects_provider_identity_change_before_embed(
    changed_property: str,
) -> None:
    from app.schema_linking.index import (
        EmbeddingIndexBuildError,
        EmbeddingIndexRegistry,
    )

    class ChangingIdentityProvider(StubEmbeddingProvider):
        def __init__(self) -> None:
            super().__init__()
            self.model_reads = 0
            self.dimension_reads = 0

        @property
        def model_id(self) -> str:
            self.model_reads += 1
            if (
                changed_property == "model_id"
                and self.model_reads > 1
            ):
                return "embedding-v2"
            return "embedding-v1"

        @model_id.setter
        def model_id(self, value: str) -> None:
            del value

        @property
        def dimension(self) -> int:
            self.dimension_reads += 1
            if (
                changed_property == "dimension"
                and self.dimension_reads > 1
            ):
                return 3
            return 2

        @dimension.setter
        def dimension(self, value: int) -> None:
            del value

    provider = ChangingIdentityProvider()
    registry = EmbeddingIndexRegistry()

    with pytest.raises(EmbeddingIndexBuildError):
        _registry_get(registry, provider)

    assert provider.calls == []
    assert registry.resident_version_ids == ()


def test_failed_concurrent_build_notifies_every_waiter_once() -> None:
    from app.schema_linking.index import (
        EmbeddingIndexBuildError,
        EmbeddingIndexRegistry,
    )

    release = threading.Event()
    started = threading.Event()

    class FailingProvider(StubEmbeddingProvider):
        def embed(
            self,
            texts: tuple[str, ...],
            *,
            timeout_seconds: float | None = None,
        ) -> tuple[tuple[float, ...], ...]:
            self.calls.append(tuple(texts))
            self.timeouts.append(timeout_seconds)
            started.set()
            assert release.wait(timeout=2)
            raise RuntimeError("private concurrent failure")

    provider = FailingProvider()
    registry = EmbeddingIndexRegistry()
    barrier = threading.Barrier(5)

    def get_index():
        barrier.wait(timeout=2)
        return _registry_get(registry, provider)

    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(get_index) for _ in range(4)]
        barrier.wait(timeout=2)
        assert started.wait(timeout=2)
        _wait_for_registry_waiters(registry, 3)
        release.set()
        for future in futures:
            with pytest.raises(EmbeddingIndexBuildError) as captured:
                future.result(timeout=2)
            assert "private" not in (
                str(captured.value) + repr(captured.value)
            )

    assert len(provider.calls) == 1
    assert registry.resident_version_ids == ()


def test_builder_cancellation_notifies_waiters_without_publishing() -> None:
    from app.schema_linking.index import (
        EmbeddingIndexBuildError,
        EmbeddingIndexRegistry,
    )

    class BuildCancelled(BaseException):
        pass

    release = threading.Event()
    started = threading.Event()

    class CancelledProvider(StubEmbeddingProvider):
        def embed(
            self,
            texts: tuple[str, ...],
            *,
            timeout_seconds: float | None = None,
        ) -> tuple[tuple[float, ...], ...]:
            self.calls.append(tuple(texts))
            self.timeouts.append(timeout_seconds)
            started.set()
            assert release.wait(timeout=2)
            raise BuildCancelled()

    provider = CancelledProvider()
    registry = EmbeddingIndexRegistry()
    barrier = threading.Barrier(3)

    def get_index():
        barrier.wait(timeout=2)
        return _registry_get(registry, provider)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(get_index) for _ in range(2)]
        barrier.wait(timeout=2)
        assert started.wait(timeout=2)
        _wait_for_registry_waiters(registry, 1)
        release.set()
        outcomes: list[type[BaseException]] = []
        for future in futures:
            try:
                future.result(timeout=2)
            except BaseException as error:
                outcomes.append(type(error))

    assert set(outcomes) == {
        BuildCancelled,
        EmbeddingIndexBuildError,
    }
    assert len(provider.calls) == 1
    assert registry.resident_version_ids == ()


def test_registry_evicts_exactly_the_least_recently_used_version() -> None:
    from app.schema_linking.index import EmbeddingIndexRegistry

    provider = StubEmbeddingProvider()
    registry = EmbeddingIndexRegistry()
    indexes = tuple(
        _registry_get(
            registry,
            provider,
            semantic_version=f"semantic-v{index}",
        )
        for index in range(32)
    )
    _registry_get(
        registry,
        provider,
        semantic_version="semantic-v0",
    )
    newest = _registry_get(
        registry,
        provider,
        semantic_version="semantic-v32",
    )

    resident = registry.resident_version_ids
    assert len(resident) == 32
    assert indexes[0].retrieval_version_id in resident
    assert indexes[1].retrieval_version_id not in resident
    assert newest.retrieval_version_id in resident
    assert all(
        index.retrieval_version_id in resident
        for index in indexes[2:]
    )
