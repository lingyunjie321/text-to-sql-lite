from __future__ import annotations

import hashlib
import json
import math
import struct
import threading
import time
import weakref
from copy import deepcopy
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Callable, Literal

from app.connectors.metadata import (
    SchemaSnapshot,
    normalize_metadata_scope,
)
from app.schema_linking.authorization import authorize_schema_snapshot
from app.schema_linking.embedding import (
    EMBEDDING_PROVIDER_CONTRACT_VERSION,
    EmbeddingProvider,
    EmbeddingProviderError,
    _embedding_timeout_error,
)
from app.schema_linking.models import (
    BM25_VERSION,
    RRF_K,
    RetrievalVersion,
)

SCHEMA_DOCUMENT_VERSION = "schema-doc-v1"
FUSION_VERSION = "rrf-v1"
RERANK_VERSION = "schema-rerank-v2"
INDEX_MAX_ENTRIES = 32
INDEX_EMBEDDING_BATCH_SIZE = 64

SchemaDocumentKind = Literal[
    "table",
    "field",
    "primary_key",
    "foreign_key",
]


def _digest_components(*components: bytes) -> str:
    digest = hashlib.sha256()
    for component in components:
        digest.update(struct.pack(">Q", len(component)))
        digest.update(component)
    return digest.hexdigest()


def authorization_scope_sha256(
    *,
    allowed_schemas: tuple[str, ...],
    allowed_tables: tuple[str, ...],
) -> str:
    try:
        scope = normalize_metadata_scope(
            allowed_schemas,
            allowed_tables,
        )
    except ValueError:
        raise ValueError("schema linking context is invalid") from None
    payload = json.dumps(
        {
            "schemas": scope.schemas,
            "tables": tuple(
                f"{schema_name}.{table_name}"
                for schema_name, table_name in scope.table_pairs
            ),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return _digest_components(
        b"retrieval-authorization-scope-v1",
        payload,
    )


@dataclass(frozen=True, slots=True)
class SchemaDocument:
    object_id: str = field(repr=False)
    kind: SchemaDocumentKind
    text: str = field(repr=False)
    table_ids: tuple[str, ...] = field(
        default=(),
        repr=False,
    )

    def __post_init__(self) -> None:
        if (
            not self.object_id.strip()
            or not self.text.strip()
            or any(
                not table_id.strip()
                for table_id in self.table_ids
            )
        ):
            raise ValueError("schema document is invalid")
        try:
            self.text.encode("utf-8")
        except UnicodeEncodeError:
            raise ValueError("schema document is invalid") from None

    @property
    def document_sha256(self) -> str:
        return hashlib.sha256(
            self.text.encode("utf-8")
        ).hexdigest()

    def __repr__(self) -> str:
        return (
            "SchemaDocument("
            f"kind={self.kind!r}, "
            f"document_sha256={self.document_sha256!r})"
        )


def _document(
    *,
    object_id: str,
    kind: SchemaDocumentKind,
    payload: dict[str, object],
    table_ids: tuple[str, ...],
) -> SchemaDocument:
    return SchemaDocument(
        object_id=object_id,
        kind=kind,
        text=json.dumps(
            {
                **payload,
                "kind": kind,
                "object_id": object_id,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ),
        table_ids=table_ids,
    )


def _build_schema_documents(
    authorized_snapshot: SchemaSnapshot,
) -> tuple[SchemaDocument, ...]:
    table_documents: list[SchemaDocument] = []
    field_documents: list[SchemaDocument] = []
    primary_key_documents: dict[str, SchemaDocument] = {}
    foreign_key_documents: dict[str, SchemaDocument] = {}

    for table in sorted(
        authorized_snapshot.tables,
        key=lambda item: (item.schema_name, item.table_name),
    ):
        table_id = f"{table.schema_name}.{table.table_name}"
        table_documents.append(
            _document(
                object_id=table_id,
                kind="table",
                payload={
                    "aliases": sorted(table.aliases),
                    "comment": table.comment,
                    "schema": table.schema_name,
                    "table": table.table_name,
                },
                table_ids=(table_id,),
            )
        )
        for column in sorted(
            table.columns,
            key=lambda item: item.column_name,
        ):
            object_id = f"{table_id}.{column.column_name}"
            field_documents.append(
                _document(
                    object_id=object_id,
                    kind="field",
                    payload={
                        "aliases": sorted(column.aliases),
                        "column": column.column_name,
                        "comment": column.comment,
                        "schema": table.schema_name,
                        "table": table.table_name,
                        "type": column.formatted_type,
                    },
                    table_ids=(table_id,),
                )
            )

    for primary_key in sorted(
        authorized_snapshot.primary_keys,
        key=lambda item: (
            item.schema_name,
            item.table_name,
            item.columns,
        ),
    ):
        table_id = (
            f"{primary_key.schema_name}.{primary_key.table_name}"
        )
        object_id = (
            f"primary_key:{table_id}"
            f"({','.join(primary_key.columns)})"
        )
        primary_key_documents.setdefault(
            object_id,
            _document(
                object_id=object_id,
                kind="primary_key",
                payload={
                    "columns": list(primary_key.columns),
                    "table": table_id,
                },
                table_ids=(table_id,),
            ),
        )

    for foreign_key in sorted(
        authorized_snapshot.foreign_keys,
        key=lambda item: (
            item.source_schema,
            item.source_table,
            item.source_columns,
            item.target_schema,
            item.target_table,
            item.target_columns,
        ),
    ):
        source_table = (
            f"{foreign_key.source_schema}.{foreign_key.source_table}"
        )
        target_table = (
            f"{foreign_key.target_schema}.{foreign_key.target_table}"
        )
        object_id = (
            f"foreign_key:{source_table}"
            f"({','.join(foreign_key.source_columns)})"
            f"->{target_table}"
            f"({','.join(foreign_key.target_columns)})"
        )
        foreign_key_documents.setdefault(
            object_id,
            _document(
                object_id=object_id,
                kind="foreign_key",
                payload={
                    "source": {
                        "columns": list(
                            foreign_key.source_columns
                        ),
                        "table": source_table,
                    },
                    "target": {
                        "columns": list(
                            foreign_key.target_columns
                        ),
                        "table": target_table,
                    },
                },
                table_ids=(source_table, target_table),
            ),
        )

    return (
        *table_documents,
        *field_documents,
        *primary_key_documents.values(),
        *foreign_key_documents.values(),
    )


def build_authorized_schema_documents(
    *,
    snapshot: SchemaSnapshot,
    allowed_schemas: tuple[str, ...],
    allowed_tables: tuple[str, ...],
) -> tuple[SchemaDocument, ...]:
    return _build_schema_documents(
        authorize_schema_snapshot(
            snapshot=snapshot,
            allowed_schemas=allowed_schemas,
            allowed_tables=allowed_tables,
        )
    )


def _build_retrieval_version(
    *,
    datasource_id: str,
    authorized_snapshot: SchemaSnapshot,
    authorization_scope_sha256: str,
    provider: EmbeddingProvider,
    semantic_version: str,
    bm25_version: str,
    embedding_provider_contract_version: str,
    document_version: str,
    fusion_version: str,
    rrf_k: int,
    rerank_version: str,
) -> RetrievalVersion:
    return RetrievalVersion(
        datasource_id=datasource_id,
        authorization_scope_sha256=authorization_scope_sha256,
        schema_version=authorized_snapshot.schema_version,
        semantic_version=semantic_version,
        bm25_version=bm25_version,
        embedding_provider_contract_version=(
            embedding_provider_contract_version
        ),
        embedding_model=provider.model_id,
        embedding_dimension=provider.dimension,
        embedding_provider_config_sha256=(
            provider.provider_config_sha256
        ),
        document_version=document_version,
        fusion_version=fusion_version,
        rrf_k=rrf_k,
        rerank_version=rerank_version,
    )


def build_retrieval_version(
    *,
    datasource_id: str,
    snapshot: SchemaSnapshot,
    allowed_schemas: tuple[str, ...],
    allowed_tables: tuple[str, ...],
    provider: EmbeddingProvider,
    semantic_version: str,
    bm25_version: str = BM25_VERSION,
    embedding_provider_contract_version: str = (
        EMBEDDING_PROVIDER_CONTRACT_VERSION
    ),
    document_version: str = SCHEMA_DOCUMENT_VERSION,
    fusion_version: str = FUSION_VERSION,
    rrf_k: int = RRF_K,
    rerank_version: str = RERANK_VERSION,
) -> RetrievalVersion:
    authorized_snapshot = authorize_schema_snapshot(
        snapshot=snapshot,
        allowed_schemas=allowed_schemas,
        allowed_tables=allowed_tables,
    )
    return _build_retrieval_version(
        datasource_id=datasource_id,
        authorized_snapshot=authorized_snapshot,
        authorization_scope_sha256=authorization_scope_sha256(
            allowed_schemas=allowed_schemas,
            allowed_tables=allowed_tables,
        ),
        provider=provider,
        semantic_version=semantic_version,
        bm25_version=bm25_version,
        embedding_provider_contract_version=(
            embedding_provider_contract_version
        ),
        document_version=document_version,
        fusion_version=fusion_version,
        rrf_k=rrf_k,
        rerank_version=rerank_version,
    )


class EmbeddingIndexBuildError(RuntimeError):
    code = "EMBEDDING_INDEX_BUILD_FAILED"

    def __init__(self) -> None:
        super().__init__("The embedding index could not be built.")


def _remaining_timeout(
    *,
    deadline_at: float | None,
    clock: Callable[[], float],
) -> float | None:
    if deadline_at is None:
        return None
    if (
        type(deadline_at) not in (int, float)
        or not math.isfinite(deadline_at)
        or not callable(clock)
    ):
        raise EmbeddingIndexBuildError() from None
    current = clock()
    if (
        type(current) not in (int, float)
        or not math.isfinite(current)
    ):
        raise EmbeddingIndexBuildError() from None
    remaining = float(deadline_at) - float(current)
    if remaining <= 0:
        raise _embedding_timeout_error() from None
    return remaining


@dataclass(frozen=True, slots=True)
class EmbeddingIndex:
    retrieval_version: RetrievalVersion
    documents: tuple[SchemaDocument, ...] = field(repr=False)
    vectors: tuple[tuple[float, ...], ...] = field(repr=False)

    @property
    def retrieval_version_id(self) -> str:
        return self.retrieval_version.retrieval_version_id

    def __repr__(self) -> str:
        return (
            "EmbeddingIndex("
            f"retrieval_version_id={self.retrieval_version_id!r}, "
            f"document_count={len(self.documents)}, "
            f"dimension={self.retrieval_version.embedding_dimension})"
        )


def _normalized_vector(
    value: object,
    *,
    dimension: int,
) -> tuple[float, ...]:
    if (
        not isinstance(value, tuple)
        or len(value) != dimension
    ):
        raise EmbeddingIndexBuildError() from None
    vector: list[float] = []
    for component in value:
        if type(component) not in (int, float):
            raise EmbeddingIndexBuildError() from None
        normalized_component = float(component)
        if not math.isfinite(normalized_component):
            raise EmbeddingIndexBuildError() from None
        vector.append(normalized_component)
    norm = math.hypot(*vector)
    if not math.isfinite(norm) or norm == 0:
        raise EmbeddingIndexBuildError() from None
    return tuple(component / norm for component in vector)


def _build_embedding_index(
    *,
    version: RetrievalVersion,
    documents: tuple[SchemaDocument, ...],
    provider: EmbeddingProvider,
    max_batch_documents: int,
    deadline_at: float | None,
    clock: Callable[[], float],
) -> EmbeddingIndex:
    if (
        provider.model_id != version.embedding_model
        or provider.dimension != version.embedding_dimension
        or provider.provider_config_sha256
        != version.embedding_provider_config_sha256
        or len({document.object_id for document in documents})
        != len(documents)
    ):
        raise EmbeddingIndexBuildError() from None

    vectors: list[tuple[float, ...]] = []
    try:
        for start in range(0, len(documents), max_batch_documents):
            batch = documents[start : start + max_batch_documents]
            embedded = provider.embed(
                tuple(document.text for document in batch),
                timeout_seconds=_remaining_timeout(
                    deadline_at=deadline_at,
                    clock=clock,
                ),
            )
            if (
                not isinstance(embedded, tuple)
                or len(embedded) != len(batch)
            ):
                raise EmbeddingIndexBuildError()
            vectors.extend(
                _normalized_vector(
                    vector,
                    dimension=version.embedding_dimension,
                )
                for vector in embedded
            )
    except (EmbeddingProviderError, EmbeddingIndexBuildError):
        raise
    except Exception:
        raise EmbeddingIndexBuildError() from None

    return EmbeddingIndex(
        retrieval_version=version,
        documents=documents,
        vectors=tuple(vectors),
    )


@dataclass(slots=True)
class _BuildFlight:
    event: threading.Event
    result: EmbeddingIndex | None = None
    error: (
        EmbeddingProviderError | EmbeddingIndexBuildError | None
    ) = None
    waiter_count: int = 0


def _copy_build_error(
    error: EmbeddingProviderError | EmbeddingIndexBuildError,
) -> EmbeddingProviderError | EmbeddingIndexBuildError:
    if isinstance(error, EmbeddingProviderError):
        return EmbeddingProviderError(error.details)
    return EmbeddingIndexBuildError()


class EmbeddingIndexRegistry:
    def __init__(
        self,
        *,
        max_entries: int = INDEX_MAX_ENTRIES,
        max_batch_documents: int = INDEX_EMBEDDING_BATCH_SIZE,
    ) -> None:
        if (
            type(max_entries) is not int
            or not 1 <= max_entries <= INDEX_MAX_ENTRIES
            or type(max_batch_documents) is not int
            or not 1 <= max_batch_documents
            <= INDEX_EMBEDDING_BATCH_SIZE
        ):
            raise ValueError("embedding index registry is invalid")
        self._max_entries = max_entries
        self._max_batch_documents = max_batch_documents
        self._lock = threading.Lock()
        self._indexes: OrderedDict[str, EmbeddingIndex] = (
            OrderedDict()
        )
        self._flights: dict[str, _BuildFlight] = {}

    @property
    def resident_version_ids(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(self._indexes)

    @property
    def waiting_build_count(self) -> int:
        with self._lock:
            return sum(
                flight.waiter_count
                for flight in self._flights.values()
            )

    def __repr__(self) -> str:
        return (
            "EmbeddingIndexRegistry("
            f"resident_version_ids={self.resident_version_ids!r})"
        )

    def get_or_build_authorized(
        self,
        *,
        datasource_id: str,
        snapshot: SchemaSnapshot,
        allowed_schemas: tuple[str, ...],
        allowed_tables: tuple[str, ...],
        provider: EmbeddingProvider,
        semantic_version: str,
        bm25_version: str = BM25_VERSION,
        embedding_provider_contract_version: str = (
            EMBEDDING_PROVIDER_CONTRACT_VERSION
        ),
        document_version: str = SCHEMA_DOCUMENT_VERSION,
        fusion_version: str = FUSION_VERSION,
        rrf_k: int = RRF_K,
        rerank_version: str = RERANK_VERSION,
        deadline_at: float | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> EmbeddingIndex:
        authorized_snapshot = authorize_schema_snapshot(
            snapshot=snapshot,
            allowed_schemas=allowed_schemas,
            allowed_tables=allowed_tables,
        )
        documents = _build_schema_documents(authorized_snapshot)
        version = _build_retrieval_version(
            datasource_id=datasource_id,
            authorized_snapshot=authorized_snapshot,
            authorization_scope_sha256=authorization_scope_sha256(
                allowed_schemas=allowed_schemas,
                allowed_tables=allowed_tables,
            ),
            provider=provider,
            semantic_version=semantic_version,
            bm25_version=bm25_version,
            embedding_provider_contract_version=(
                embedding_provider_contract_version
            ),
            document_version=document_version,
            fusion_version=fusion_version,
            rrf_k=rrf_k,
            rerank_version=rerank_version,
        )
        return self._get_or_build(
            version=version,
            documents=documents,
            provider=provider,
            deadline_at=deadline_at,
            clock=clock,
        )

    def _get_or_build(
        self,
        *,
        version: RetrievalVersion,
        documents: tuple[SchemaDocument, ...],
        provider: EmbeddingProvider,
        deadline_at: float | None,
        clock: Callable[[], float],
    ) -> EmbeddingIndex:
        version_id = version.retrieval_version_id
        if (
            provider.model_id != version.embedding_model
            or provider.dimension != version.embedding_dimension
            or provider.provider_config_sha256
            != version.embedding_provider_config_sha256
            or not isinstance(documents, tuple)
            or not callable(clock)
        ):
            raise EmbeddingIndexBuildError() from None

        with self._lock:
            cached = self._indexes.get(version_id)
            if cached is not None:
                if cached.documents != documents:
                    raise EmbeddingIndexBuildError() from None
                self._indexes.move_to_end(version_id)
                return cached
            flight = self._flights.get(version_id)
            is_builder = flight is None
            if flight is None:
                flight = _BuildFlight(event=threading.Event())
                self._flights[version_id] = flight
            else:
                flight.waiter_count += 1

        if not is_builder:
            wait_timeout = _remaining_timeout(
                deadline_at=deadline_at,
                clock=clock,
            )
            try:
                completed = flight.event.wait(wait_timeout)
            finally:
                with self._lock:
                    flight.waiter_count = max(
                        0,
                        flight.waiter_count - 1,
                    )
            if not completed:
                raise _embedding_timeout_error() from None
            if flight.error is not None:
                raise _copy_build_error(flight.error) from None
            if (
                flight.result is None
                or flight.result.documents != documents
            ):
                raise EmbeddingIndexBuildError() from None
            return flight.result

        try:
            index = _build_embedding_index(
                version=version,
                documents=documents,
                provider=provider,
                max_batch_documents=self._max_batch_documents,
                deadline_at=deadline_at,
                clock=clock,
            )
        except (
            EmbeddingProviderError,
            EmbeddingIndexBuildError,
        ) as error:
            with self._lock:
                flight.error = error
                flight.event.set()
                self._flights.pop(version_id, None)
            raise _copy_build_error(error) from None
        except BaseException:
            with self._lock:
                flight.error = EmbeddingIndexBuildError()
                flight.event.set()
                self._flights.pop(version_id, None)
            raise

        with self._lock:
            self._indexes[version_id] = index
            self._indexes.move_to_end(version_id)
            while len(self._indexes) > self._max_entries:
                self._indexes.popitem(last=False)
            flight.result = index
            flight.event.set()
            self._flights.pop(version_id, None)
        return index


class _PreparedPoolRegistry:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._pools: dict[
            int,
            tuple[weakref.ReferenceType[object], object],
        ] = {}

    def _discard(
        self,
        key: int,
        reference: weakref.ReferenceType[object],
    ) -> None:
        with self._lock:
            current = self._pools.get(key)
            if current is not None and current[0] is reference:
                self._pools.pop(key, None)

    def _remember(self, pool: object) -> None:
        try:
            key = id(pool)
            reference = weakref.ref(
                pool,
                lambda value: self._discard(key, value),
            )
            snapshot = deepcopy(pool)
            with self._lock:
                self._pools[key] = (reference, snapshot)
        except (TypeError, ValueError):
            raise ValueError(
                "prepared pool registry is invalid"
            ) from None

    def contains(self, pool: object) -> bool:
        with self._lock:
            record = self._pools.get(id(pool))
            return (
                record is not None
                and record[0]() is pool
                and record[1] == pool
            )

    def __repr__(self) -> str:
        with self._lock:
            count = len(self._pools)
        return (
            "_PreparedPoolRegistry("
            f"resident_count={count})"
        )


@dataclass(frozen=True, slots=True)
class RetrievalRuntime:
    provider: EmbeddingProvider = field(repr=False)
    registry: EmbeddingIndexRegistry = field(repr=False)
    semantic_version: str
    _prepared_pools: _PreparedPoolRegistry = field(
        default_factory=_PreparedPoolRegistry,
        init=False,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        if (
            not self.semantic_version
            or self.semantic_version
            != self.semantic_version.strip()
            or not self.provider.model_id.strip()
            or type(self.provider.dimension) is not int
            or self.provider.dimension <= 0
            or len(self.provider.provider_config_sha256) != 64
            or any(
                character not in "0123456789abcdef"
                for character
                in self.provider.provider_config_sha256
            )
            or not isinstance(
                self._prepared_pools,
                _PreparedPoolRegistry,
            )
        ):
            raise ValueError("retrieval runtime is invalid")

    def __copy__(self) -> RetrievalRuntime:
        return RetrievalRuntime(
            provider=self.provider,
            registry=self.registry,
            semantic_version=self.semantic_version,
        )

    def __deepcopy__(
        self,
        memo: dict[int, object],
    ) -> RetrievalRuntime:
        copied = self.__copy__()
        memo[id(self)] = copied
        return copied


def _remember_prepared_pool(
    runtime: RetrievalRuntime,
    pool: object,
) -> None:
    runtime._prepared_pools._remember(pool)


def _is_prepared_pool(
    runtime: RetrievalRuntime,
    pool: object,
) -> bool:
    return runtime._prepared_pools.contains(pool)
