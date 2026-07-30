import hashlib
import math
import re
import unicodedata
from collections import Counter, deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from itertools import combinations
from time import monotonic, perf_counter_ns
from typing import Literal

from app.connectors.metadata import (
    SchemaSnapshot,
    TableMetadata,
)
from app.connectors.errors import ErrorType
from app.schema_linking.authorization import (
    authorize_schema_snapshot as _authorized_snapshot,
)
from app.schema_linking.embedding import (
    EmbeddingError,
    EmbeddingProviderError,
)
from app.schema_linking.fusion import (
    EmbeddingDegradation,
    EmbeddingRankEvidence,
    FusedCandidate,
    RetrievalEvidence,
    SchemaRetrievalPool,
    rank_embedding_index,
    reciprocal_rank_fusion,
)
from app.schema_linking.index import (
    EmbeddingIndexBuildError,
    RetrievalRuntime,
    _is_prepared_pool,
    _remaining_timeout,
    _remember_prepared_pool,
    authorization_scope_sha256,
    build_retrieval_version,
)
from app.schema_linking.models import (
    CandidateField,
    CandidateTable,
    JoinEdge,
    JoinPath,
    RETRIEVAL_VERSION_CONTRACT,
    RetrievalVersion,
    SchemaTopK,
    SchemaLinkingResult,
    validate_schema_top_k,
)
from app.schema_linking.rerank import (
    RerankOutcome,
    fallback_rerank_outcome,
    find_required_bridge_table_ids,
    rerank_schema_candidates,
)

BM25_K1 = 1.5
BM25_B = 0.75
_FIELD_AGGREGATION_WEIGHT = 0.35
RETRIEVAL_CANDIDATE_LIMIT = 20
_CAMEL_BOUNDARY = re.compile(
    r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])"
)
_WORD = re.compile(r"\w+", flags=re.UNICODE)


def _elapsed_ms(started_ns: int) -> float:
    return max(0.0, (perf_counter_ns() - started_ns) / 1_000_000)


def _tokenize(text: str) -> tuple[str, ...]:
    normalized = unicodedata.normalize("NFKC", text)
    tokens: list[str] = []
    for word in _WORD.findall(normalized):
        folded_word = word.casefold()
        tokens.append(folded_word)
        for underscore_part in word.split("_"):
            if not underscore_part:
                continue
            folded_part = underscore_part.casefold()
            if folded_part != folded_word:
                tokens.append(folded_part)
            for camel_part in _CAMEL_BOUNDARY.split(underscore_part):
                folded_camel_part = camel_part.casefold()
                if folded_camel_part and folded_camel_part != folded_part:
                    tokens.append(folded_camel_part)
    return tuple(tokens)


def _weighted_tokens(
    text: str | None,
    *,
    repetitions: int = 1,
) -> tuple[str, ...]:
    if not text:
        return ()
    return _tokenize(text) * repetitions


@dataclass(frozen=True, slots=True)
class _DocumentScore:
    score: float
    matched_tokens: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _GraphStep:
    neighbor: str
    edge: JoinEdge


RetrievalFailureCode = Literal[
    "EMBEDDING_INVALID_INPUT",
    "EMBEDDING_TIMEOUT",
    "EMBEDDING_CONNECTION_ERROR",
    "EMBEDDING_HTTP_ERROR",
    "EMBEDDING_RATE_LIMITED",
    "EMBEDDING_INVALID_RESPONSE",
]


@dataclass(frozen=True, slots=True)
class RetrievalFailureEvidence:
    retrieval_version: RetrievalVersion
    failure_code: RetrievalFailureCode
    bm25_table_count: int
    bm25_field_count: int
    bm25_duration_ms: float
    embedding_duration_ms: float

    def __post_init__(self) -> None:
        if (
            not isinstance(self.retrieval_version, RetrievalVersion)
            or self.failure_code
            not in {
                "EMBEDDING_INVALID_INPUT",
                "EMBEDDING_TIMEOUT",
                "EMBEDDING_CONNECTION_ERROR",
                "EMBEDDING_HTTP_ERROR",
                "EMBEDDING_RATE_LIMITED",
                "EMBEDDING_INVALID_RESPONSE",
            }
            or type(self.bm25_table_count) is not int
            or self.bm25_table_count < 0
            or type(self.bm25_field_count) is not int
            or self.bm25_field_count < 0
            or any(
                type(value) not in (int, float)
                or not math.isfinite(float(value))
                or value < 0
                for value in (
                    self.bm25_duration_ms,
                    self.embedding_duration_ms,
                )
            )
        ):
            raise ValueError(
                "retrieval failure evidence is invalid"
            )


class SchemaRetrievalFailure(EmbeddingProviderError):
    def __init__(
        self,
        *,
        cause: EmbeddingProviderError | EmbeddingIndexBuildError,
        evidence: RetrievalFailureEvidence,
    ) -> None:
        details = (
            cause.details
            if isinstance(cause, EmbeddingProviderError)
            else EmbeddingError(
                error_type=ErrorType.UNKNOWN,
                code="EMBEDDING_INVALID_RESPONSE",
                retryable=False,
                public_message=(
                    "The embedding response is invalid."
                ),
            )
        )
        super().__init__(details)
        self.args = ("Schema retrieval failed.",)
        self.cause = cause
        self.evidence = evidence


class _BM25:
    def __init__(self, documents: Mapping[str, tuple[str, ...]]) -> None:
        self._documents = dict(documents)
        self._frequencies = {
            document_id: Counter(tokens)
            for document_id, tokens in self._documents.items()
        }
        self._document_count = len(self._documents)
        total_length = sum(
            len(tokens) for tokens in self._documents.values()
        )
        self._average_length = (
            total_length / self._document_count
            if self._document_count
            else 0.0
        )
        document_frequency: Counter[str] = Counter()
        for tokens in self._documents.values():
            document_frequency.update(set(tokens))
        self._document_frequency = document_frequency

    def score(self, query_tokens: tuple[str, ...]) -> dict[str, _DocumentScore]:
        query_terms = tuple(sorted(set(query_tokens)))
        scores: dict[str, _DocumentScore] = {}
        for document_id, tokens in self._documents.items():
            frequencies = self._frequencies[document_id]
            matched_tokens = tuple(
                term for term in query_terms if frequencies[term] > 0
            )
            score = sum(
                self._term_score(
                    frequencies[term],
                    len(tokens),
                    self._document_frequency[term],
                )
                for term in matched_tokens
            )
            scores[document_id] = _DocumentScore(
                score=round(score, 12),
                matched_tokens=matched_tokens,
            )
        return scores

    def _term_score(
        self,
        term_frequency: int,
        document_length: int,
        document_frequency: int,
    ) -> float:
        if (
            not self._document_count
            or not self._average_length
            or not term_frequency
        ):
            return 0.0
        inverse_document_frequency = math.log(
            1
            + (
                self._document_count
                - document_frequency
                + 0.5
            )
            / (document_frequency + 0.5)
        )
        length_normalization = (
            1
            - BM25_B
            + BM25_B * document_length / self._average_length
        )
        return (
            inverse_document_frequency
            * term_frequency
            * (BM25_K1 + 1)
            / (
                term_frequency
                + BM25_K1 * length_normalization
            )
        )


def _table_document(table: TableMetadata) -> tuple[str, ...]:
    tokens = list(_weighted_tokens(table.schema_name))
    tokens.extend(_weighted_tokens(table.table_name, repetitions=3))
    for alias in table.aliases:
        tokens.extend(_weighted_tokens(alias, repetitions=2))
    tokens.extend(_weighted_tokens(table.comment))
    for column in table.columns:
        tokens.extend(
            _weighted_tokens(column.column_name, repetitions=2)
        )
        for alias in column.aliases:
            tokens.extend(_weighted_tokens(alias, repetitions=2))
        tokens.extend(_weighted_tokens(column.comment))
    return tuple(tokens)


def _field_document(
    table: TableMetadata,
    column_name: str,
) -> tuple[str, ...]:
    column = next(
        item for item in table.columns if item.column_name == column_name
    )
    tokens = list(_weighted_tokens(table.table_name))
    tokens.extend(_weighted_tokens(column.column_name, repetitions=3))
    for alias in column.aliases:
        tokens.extend(_weighted_tokens(alias, repetitions=2))
    tokens.extend(_weighted_tokens(column.comment))
    return tuple(tokens)


def _approved_alias_match_count(
    table: TableMetadata,
    *,
    query_tokens: tuple[str, ...],
) -> int:
    query_token_set = set(query_tokens)
    aliases = (
        *table.aliases,
        *(
            alias
            for column in table.columns
            for alias in column.aliases
        ),
    )
    return sum(
        1
        for alias in aliases
        if (
            (alias_tokens := set(_tokenize(alias)))
            and alias_tokens.issubset(query_token_set)
        )
    )


def _foreign_key_graph(
    snapshot: SchemaSnapshot,
) -> dict[str, tuple[_GraphStep, ...]]:
    adjacency: dict[str, list[_GraphStep]] = {
        f"{table.schema_name}.{table.table_name}": []
        for table in snapshot.tables
    }
    for foreign_key in snapshot.foreign_keys:
        source_table = (
            f"{foreign_key.source_schema}.{foreign_key.source_table}"
        )
        target_table = (
            f"{foreign_key.target_schema}.{foreign_key.target_table}"
        )
        edge = JoinEdge(
            constraint_name=foreign_key.constraint_name,
            source_table=source_table,
            source_columns=foreign_key.source_columns,
            target_table=target_table,
            target_columns=foreign_key.target_columns,
        )
        adjacency[source_table].append(
            _GraphStep(neighbor=target_table, edge=edge)
        )
        adjacency[target_table].append(
            _GraphStep(neighbor=source_table, edge=edge)
        )
    return {
        table_id: tuple(
            sorted(
                steps,
                key=lambda step: (
                    step.neighbor,
                    step.edge.constraint_name,
                    step.edge.source_table,
                    step.edge.target_table,
                ),
            )
        )
        for table_id, steps in adjacency.items()
    }


def _shortest_path(
    graph: Mapping[str, tuple[_GraphStep, ...]],
    start: str,
    target: str,
    *,
    allowed_nodes: set[str] | None = None,
) -> JoinPath | None:
    if start == target:
        return JoinPath(tables=(start,), edges=())
    if start not in graph or target not in graph:
        return None

    visited = {start}
    pending = deque([(start, (start,), ())])
    while pending:
        current, tables, edges = pending.popleft()
        for step in graph[current]:
            if (
                step.neighbor in visited
                or (
                    allowed_nodes is not None
                    and step.neighbor not in allowed_nodes
                )
            ):
                continue
            next_tables = (*tables, step.neighbor)
            next_edges = (*edges, step.edge)
            if step.neighbor == target:
                return JoinPath(
                    tables=next_tables,
                    edges=next_edges,
                )
            visited.add(step.neighbor)
            pending.append(
                (step.neighbor, next_tables, next_edges)
            )
    return None


def _path_order(path: JoinPath) -> tuple[object, ...]:
    return (
        len(path.edges),
        path.tables,
        tuple(edge.constraint_name for edge in path.edges),
    )


def _distances_from_tables(
    graph: Mapping[str, tuple[_GraphStep, ...]],
    starting_tables: set[str],
) -> dict[str, int]:
    distances = {
        table_id: 0 for table_id in starting_tables
    }
    pending = deque(sorted(starting_tables))
    while pending:
        current = pending.popleft()
        for step in graph.get(current, ()):
            if step.neighbor in distances:
                continue
            distances[step.neighbor] = distances[current] + 1
            pending.append(step.neighbor)
    return distances


def _select_table_ids(
    ranked_table_ids: list[str],
    graph: Mapping[str, tuple[_GraphStep, ...]],
    *,
    top_k: SchemaTopK,
) -> list[str]:
    selected: list[str] = []
    selected_set: set[str] = set()
    for candidate in ranked_table_ids:
        if candidate in selected_set:
            continue
        if not selected:
            selected.append(candidate)
            selected_set.add(candidate)
            continue

        connecting_paths = tuple(
            path
            for selected_table in selected
            if (
                path := _shortest_path(
                    graph,
                    candidate,
                    selected_table,
                )
            )
            is not None
        )
        best_path = (
            min(connecting_paths, key=_path_order)
            if connecting_paths
            else None
        )
        additions = (
            tuple(
                table_id
                for table_id in best_path.tables
                if table_id not in selected_set
            )
            if best_path is not None
            else (candidate,)
        )
        if len(selected_set) + len(additions) <= top_k:
            selected.extend(additions)
            selected_set.update(additions)
        elif len(selected_set) < top_k:
            selected.append(candidate)
            selected_set.add(candidate)
        if len(selected_set) == top_k:
            break

    return [
        table_id
        for table_id in ranked_table_ids
        if table_id in selected_set
    ]


def _join_paths(
    selected_table_ids: list[str],
    graph: Mapping[str, tuple[_GraphStep, ...]],
) -> tuple[JoinPath, ...]:
    selected_set = set(selected_table_ids)
    paths: list[JoinPath] = []
    for start, target in combinations(sorted(selected_set), 2):
        path = _shortest_path(
            graph,
            start,
            target,
            allowed_nodes=selected_set,
        )
        if path is not None:
            paths.append(path)
    return tuple(paths)


def retrieval_query_sha256(question: str) -> str:
    try:
        encoded = question.encode("utf-8")
    except UnicodeEncodeError:
        raise ValueError("schema linking context is invalid") from None
    digest = hashlib.sha256()
    digest.update(b"schema-retrieval-query-v1")
    digest.update(len(encoded).to_bytes(8, "big"))
    digest.update(encoded)
    return digest.hexdigest()


def _embedding_degradation(
    error: EmbeddingProviderError | EmbeddingIndexBuildError,
) -> EmbeddingDegradation:
    if isinstance(error, EmbeddingIndexBuildError):
        return "invalid_response"
    degradations: dict[str, EmbeddingDegradation] = {
        "EMBEDDING_TIMEOUT": "timeout",
        "EMBEDDING_CONNECTION_ERROR": "connection",
        "EMBEDDING_RATE_LIMITED": "rate_limited",
        "EMBEDDING_INVALID_RESPONSE": "invalid_response",
    }
    degradation = degradations.get(error.details.code)
    if degradation is None:
        raise error
    return degradation


def _retrieval_failure_code(
    error: EmbeddingProviderError | EmbeddingIndexBuildError,
) -> RetrievalFailureCode:
    if isinstance(error, EmbeddingIndexBuildError):
        return "EMBEDDING_INVALID_RESPONSE"
    code = error.details.code
    if code == "EMBEDDING_INVALID_INPUT":
        return code
    if code == "EMBEDDING_TIMEOUT":
        return code
    if code == "EMBEDDING_CONNECTION_ERROR":
        return code
    if code == "EMBEDDING_HTTP_ERROR":
        return code
    if code == "EMBEDDING_RATE_LIMITED":
        return code
    if code == "EMBEDDING_INVALID_RESPONSE":
        return code
    raise error


def _retrieval_evidence(
    *,
    ordered_ids: tuple[str, ...],
    bm25_scores: Mapping[str, float],
    bm25_ranked_ids: tuple[str, ...],
    embedding_ranks: tuple[EmbeddingRankEvidence, ...],
    fused: tuple[FusedCandidate, ...],
) -> tuple[RetrievalEvidence, ...]:
    bm25_rank_by_id = {
        object_id: rank
        for rank, object_id in enumerate(
            bm25_ranked_ids,
            start=1,
        )
    }
    embedding_by_id = {
        evidence.object_id: evidence
        for evidence in embedding_ranks
    }
    fused_by_id = {
        candidate.object_id: (rank, candidate)
        for rank, candidate in enumerate(fused, start=1)
    }
    return tuple(
        RetrievalEvidence(
            object_id=object_id,
            bm25_rank=bm25_rank_by_id.get(object_id),
            bm25_score=bm25_scores.get(object_id, 0.0),
            embedding_rank=(
                embedding_by_id[object_id].rank
                if object_id in embedding_by_id
                else None
            ),
            embedding_similarity=(
                embedding_by_id[object_id].similarity
                if object_id in embedding_by_id
                else None
            ),
            fusion_rank=(
                fused_by_id[object_id][0]
                if object_id in fused_by_id
                else None
            ),
            fusion_score=(
                fused_by_id[object_id][1].score
                if object_id in fused_by_id
                else 0.0
            ),
            contributions=(
                fused_by_id[object_id][1].contributions
                if object_id in fused_by_id
                else ()
            ),
        )
        for object_id in ordered_ids
    )


def _embedding_ranks_from_evidence(
    evidence: tuple[RetrievalEvidence, ...],
) -> tuple[EmbeddingRankEvidence, ...]:
    ranked = tuple(
        sorted(
            (
                item
                for item in evidence
                if item.embedding_rank is not None
            ),
            key=lambda item: item.embedding_rank or 0,
        )
    )
    if (
        tuple(
            item.embedding_rank for item in ranked
        )
        != tuple(range(1, len(ranked) + 1))
        or any(
            item.embedding_similarity is None
            or not math.isfinite(item.embedding_similarity)
            or item.embedding_similarity <= 0
            for item in ranked
        )
        or any(
            (
                item.embedding_rank is None
                and item.embedding_similarity is not None
            )
            for item in evidence
        )
    ):
        raise ValueError(
            "schema linking context is invalid"
        ) from None
    return tuple(
        EmbeddingRankEvidence(
            object_id=item.object_id,
            similarity=item.embedding_similarity,  # type: ignore[arg-type]
            rank=item.embedding_rank,  # type: ignore[arg-type]
            source_document_id=item.object_id,
        )
        for item in ranked
    )


def _ranked_with_lexical_remainder(
    fused: tuple[FusedCandidate, ...],
    lexical_ranked_ids: list[str],
) -> tuple[str, ...]:
    fused_ids = {
        candidate.object_id for candidate in fused
    }
    return (
        *(candidate.object_id for candidate in fused),
        *(
            object_id
            for object_id in lexical_ranked_ids
            if object_id not in fused_ids
        ),
    )


def _validate_prepared_pool_contents(
    *,
    pool: SchemaRetrievalPool,
    aggregate_scores: Mapping[str, float],
    field_scores: Mapping[str, _DocumentScore],
    bm25_table_ranked_ids: tuple[str, ...],
    bm25_field_ranked_ids: tuple[str, ...],
    lexical_ranked_table_ids: list[str],
    lexical_ranked_field_ids: list[str],
) -> None:
    embedding_table_ranks = _embedding_ranks_from_evidence(
        pool.table_evidence
    )
    embedding_field_ranks = _embedding_ranks_from_evidence(
        pool.field_evidence
    )
    if (
        (
            pool.mode == "bm25_only"
            and (
                embedding_table_ranks
                or embedding_field_ranks
                or not bm25_table_ranked_ids
            )
        )
        or (
            pool.mode == "hybrid"
            and pool.embedding_degradation is not None
        )
    ):
        raise ValueError(
            "schema linking context is invalid"
        ) from None

    fused_tables = reciprocal_rank_fusion(
        {
            "bm25": bm25_table_ranked_ids,
            "embedding": tuple(
                item.object_id
                for item in embedding_table_ranks
            ),
        }
    )
    fused_fields = reciprocal_rank_fusion(
        {
            "bm25": bm25_field_ranked_ids,
            "embedding": tuple(
                item.object_id
                for item in embedding_field_ranks
            ),
        }
    )
    ranked_table_ids = _ranked_with_lexical_remainder(
        fused_tables,
        lexical_ranked_table_ids,
    )
    ranked_field_ids = _ranked_with_lexical_remainder(
        fused_fields,
        lexical_ranked_field_ids,
    )
    expected_table_evidence = _retrieval_evidence(
        ordered_ids=ranked_table_ids,
        bm25_scores=aggregate_scores,
        bm25_ranked_ids=bm25_table_ranked_ids,
        embedding_ranks=embedding_table_ranks,
        fused=fused_tables,
    )
    expected_field_evidence = _retrieval_evidence(
        ordered_ids=ranked_field_ids,
        bm25_scores={
            object_id: score.score
            for object_id, score in field_scores.items()
        },
        bm25_ranked_ids=bm25_field_ranked_ids,
        embedding_ranks=embedding_field_ranks,
        fused=fused_fields,
    )
    if (
        pool.ranked_table_ids != ranked_table_ids
        or pool.ranked_field_ids != ranked_field_ids
        or pool.table_evidence != expected_table_evidence
        or pool.field_evidence != expected_field_evidence
    ):
        raise ValueError(
            "schema linking context is invalid"
        ) from None


def link_schema(
    question: str,
    *,
    allowed_schemas: tuple[str, ...],
    allowed_tables: tuple[str, ...],
    snapshot: SchemaSnapshot,
    top_k: SchemaTopK,
    datasource_id: str | None = None,
    retrieval_runtime: RetrievalRuntime | None = None,
    prepared_pool: SchemaRetrievalPool | None = None,
    deadline_at: float | None = None,
    clock: Callable[[], float] = monotonic,
) -> SchemaLinkingResult:
    validated_top_k = validate_schema_top_k(top_k)
    if (
        (retrieval_runtime is None) != (datasource_id is None)
        or (
            prepared_pool is not None
            and retrieval_runtime is None
        )
        or not callable(clock)
        or (
            deadline_at is not None
            and (
                type(deadline_at) not in (int, float)
                or not math.isfinite(deadline_at)
            )
        )
    ):
        raise ValueError("schema linking context is invalid") from None
    authorized = _authorized_snapshot(
        allowed_schemas=allowed_schemas,
        allowed_tables=allowed_tables,
        snapshot=snapshot,
    )
    bm25_started_ns = perf_counter_ns()
    query_tokens = _tokenize(question)
    table_by_id = {
        f"{table.schema_name}.{table.table_name}": table
        for table in authorized.tables
    }
    table_scores = _BM25(
        {
            object_id: _table_document(table)
            for object_id, table in table_by_id.items()
        }
    ).score(query_tokens)
    field_by_id = {
        (
            f"{table.schema_name}.{table.table_name}."
            f"{column.column_name}"
        ): (table, column)
        for table in authorized.tables
        for column in table.columns
    }
    field_scores = _BM25(
        {
            object_id: _field_document(table, column.column_name)
            for object_id, (table, column) in field_by_id.items()
        }
    ).score(query_tokens)

    aggregate_scores: dict[str, float] = {}
    aggregate_matches: dict[str, tuple[str, ...]] = {}
    for object_id, table in table_by_id.items():
        field_prefix = f"{object_id}."
        relevant_field_scores = [
            score
            for field_id, score in field_scores.items()
            if field_id.startswith(field_prefix)
        ]
        best_fields = sorted(
            relevant_field_scores,
            key=lambda item: item.score,
            reverse=True,
        )[:3]
        aggregate_scores[object_id] = round(
            table_scores[object_id].score
            + _FIELD_AGGREGATION_WEIGHT
            * sum(item.score for item in best_fields),
            12,
        )
        aggregate_matches[object_id] = tuple(
            sorted(
                {
                    *table_scores[object_id].matched_tokens,
                    *(
                        token
                        for field_score in relevant_field_scores
                        for token in field_score.matched_tokens
                    ),
                }
            )
        )

    graph = _foreign_key_graph(authorized)
    positive_table_ids = {
        object_id
        for object_id, score in aggregate_scores.items()
        if score > 0
    }
    relationship_distances = _distances_from_tables(
        graph,
        positive_table_ids,
    )
    lexical_ranked_table_ids = sorted(
        table_by_id,
        key=lambda object_id: (
            (
                0
                if aggregate_scores[object_id] > 0
                else 1
                if object_id in relationship_distances
                else 2
            ),
            (
                -aggregate_scores[object_id]
                if aggregate_scores[object_id] > 0
                else relationship_distances.get(object_id, 0)
            ),
            object_id,
        ),
    )
    lexical_ranked_field_ids = sorted(
        field_by_id,
        key=lambda object_id: (
            -field_scores[object_id].score,
            object_id,
        ),
    )
    bm25_table_ranked_ids = tuple(
        object_id
        for object_id in lexical_ranked_table_ids
        if aggregate_scores[object_id] > 0
    )[:RETRIEVAL_CANDIDATE_LIMIT]
    bm25_field_ranked_ids = tuple(
        object_id
        for object_id in lexical_ranked_field_ids
        if field_scores[object_id].score > 0
    )[:RETRIEVAL_CANDIDATE_LIMIT]
    bm25_duration_ms = _elapsed_ms(bm25_started_ns)

    retrieval_pool: SchemaRetrievalPool | None = None
    ranked_table_ids = lexical_ranked_table_ids
    ranked_field_ids = lexical_ranked_field_ids
    if retrieval_runtime is not None:
        assert datasource_id is not None
        expected_version = build_retrieval_version(
            datasource_id=datasource_id,
            snapshot=snapshot,
            allowed_schemas=allowed_schemas,
            allowed_tables=allowed_tables,
            provider=retrieval_runtime.provider,
            semantic_version=retrieval_runtime.semantic_version,
        )
        expected_scope_sha256 = authorization_scope_sha256(
            allowed_schemas=allowed_schemas,
            allowed_tables=allowed_tables,
        )
        expected_query_sha256 = retrieval_query_sha256(question)
        if prepared_pool is not None:
            if not _is_prepared_pool(
                retrieval_runtime,
                prepared_pool
            ):
                raise ValueError(
                    "schema linking context is invalid"
                ) from None
            if (
                prepared_pool.query_sha256
                != expected_query_sha256
                or prepared_pool.schema_version
                != authorized.schema_version
                or prepared_pool.authorization_scope_sha256
                != expected_scope_sha256
                or prepared_pool.retrieval_version_id
                != expected_version.retrieval_version_id
                or set(prepared_pool.ranked_table_ids)
                != set(table_by_id)
                or set(prepared_pool.ranked_field_ids)
                != set(field_by_id)
                or {
                    evidence.object_id
                    for evidence in prepared_pool.table_evidence
                }
                != set(table_by_id)
                or {
                    evidence.object_id
                    for evidence in prepared_pool.field_evidence
                }
                != set(field_by_id)
            ):
                raise ValueError(
                    "schema linking context is invalid"
                ) from None
            _validate_prepared_pool_contents(
                pool=prepared_pool,
                aggregate_scores=aggregate_scores,
                field_scores=field_scores,
                bm25_table_ranked_ids=(
                    bm25_table_ranked_ids
                ),
                bm25_field_ranked_ids=(
                    bm25_field_ranked_ids
                ),
                lexical_ranked_table_ids=(
                    lexical_ranked_table_ids
                ),
                lexical_ranked_field_ids=(
                    lexical_ranked_field_ids
                ),
            )
            retrieval_pool = prepared_pool
        else:
            embedding_table_ranks: tuple[
                EmbeddingRankEvidence,
                ...,
            ] = ()
            embedding_field_ranks: tuple[
                EmbeddingRankEvidence,
                ...,
            ] = ()
            degradation: EmbeddingDegradation | None = None
            mode: Literal["hybrid", "bm25_only"] = "hybrid"
            embedding_started_ns = perf_counter_ns()
            try:
                index = (
                    retrieval_runtime.registry
                    .get_or_build_authorized(
                        datasource_id=datasource_id,
                        snapshot=snapshot,
                        allowed_schemas=allowed_schemas,
                        allowed_tables=allowed_tables,
                        provider=retrieval_runtime.provider,
                        semantic_version=(
                            retrieval_runtime.semantic_version
                        ),
                        deadline_at=deadline_at,
                        clock=clock,
                    )
                )
                if index.retrieval_version != expected_version:
                    raise ValueError(
                        "schema linking context is invalid"
                    )
                query_vectors = retrieval_runtime.provider.embed(
                    (question,),
                    timeout_seconds=_remaining_timeout(
                        deadline_at=deadline_at,
                        clock=clock,
                    ),
                )
                if (
                    not isinstance(query_vectors, tuple)
                    or len(query_vectors) != 1
                ):
                    raise EmbeddingIndexBuildError()
                embedding_ranking = rank_embedding_index(
                    index=index,
                    query_vector=query_vectors[0],
                    authorized_snapshot=authorized,
                )
                embedding_table_ranks = (
                    embedding_ranking.table_ranks
                )
                embedding_field_ranks = (
                    embedding_ranking.field_ranks
                )
            except (
                EmbeddingProviderError,
                EmbeddingIndexBuildError,
            ) as error:
                embedding_duration_ms = _elapsed_ms(
                    embedding_started_ns
                )
                if not bm25_table_ranked_ids:
                    raise SchemaRetrievalFailure(
                        cause=error,
                        evidence=RetrievalFailureEvidence(
                            retrieval_version=expected_version,
                            failure_code=(
                                _retrieval_failure_code(error)
                            ),
                            bm25_table_count=len(
                                bm25_table_ranked_ids
                            ),
                            bm25_field_count=len(
                                bm25_field_ranked_ids
                            ),
                            bm25_duration_ms=bm25_duration_ms,
                            embedding_duration_ms=(
                                embedding_duration_ms
                            ),
                        ),
                    ) from None
                mode = "bm25_only"
                degradation = _embedding_degradation(error)
            else:
                embedding_duration_ms = _elapsed_ms(
                    embedding_started_ns
                )

            rrf_started_ns = perf_counter_ns()
            fused_tables = reciprocal_rank_fusion(
                {
                    "bm25": bm25_table_ranked_ids,
                    "embedding": tuple(
                        evidence.object_id
                        for evidence in embedding_table_ranks
                    ),
                }
            )
            fused_fields = reciprocal_rank_fusion(
                {
                    "bm25": bm25_field_ranked_ids,
                    "embedding": tuple(
                        evidence.object_id
                        for evidence in embedding_field_ranks
                    ),
                }
            )
            ranked_table_ids = list(
                _ranked_with_lexical_remainder(
                    fused_tables,
                    lexical_ranked_table_ids,
                )
            )
            ranked_field_ids = list(
                _ranked_with_lexical_remainder(
                    fused_fields,
                    lexical_ranked_field_ids,
                )
            )
            rrf_duration_ms = _elapsed_ms(rrf_started_ns)
            rerank_started_ns = perf_counter_ns()
            raw_fusion_scores = {
                candidate.object_id: candidate.score
                for candidate in fused_tables
            }
            raw_fused_ids = tuple(raw_fusion_scores)
            raw_direct_evidence_table_ids = frozenset(
                {
                    *positive_table_ids,
                    *(
                        evidence.object_id
                        for evidence in embedding_table_ranks
                    ),
                }
                & set(raw_fused_ids)
            )
            try:
                required_bridge_ids = (
                    find_required_bridge_table_ids(
                        direct_evidence_table_ids=(
                            raw_direct_evidence_table_ids
                        ),
                        authorized_snapshot=authorized,
                    )
                )
                rerank_input_ids = (
                    *raw_fused_ids,
                    *(
                        object_id
                        for object_id in required_bridge_ids
                        if object_id not in raw_fusion_scores
                    ),
                )
                fusion_scores = {
                    object_id: raw_fusion_scores.get(
                        object_id,
                        0.0,
                    )
                    for object_id in rerank_input_ids
                }
                embedding_field_ids = {
                    evidence.object_id
                    for evidence in embedding_field_ranks
                }
                direct_field_ids = {
                    field_id
                    for field_id in field_by_id
                    if (
                        field_scores[field_id].score > 0
                        or field_id in embedding_field_ids
                    )
                }
                direct_field_counts = {
                    table_id: sum(
                        1
                        for field_id in direct_field_ids
                        if field_id.startswith(f"{table_id}.")
                    )
                    for table_id in rerank_input_ids
                }
                approved_alias_counts = {
                    table_id: _approved_alias_match_count(
                        table_by_id[table_id],
                        query_tokens=query_tokens,
                    )
                    for table_id in rerank_input_ids
                }
                primary_key_fields: dict[str, set[str]] = {}
                for primary_key in authorized.primary_keys:
                    table_id = (
                        f"{primary_key.schema_name}."
                        f"{primary_key.table_name}"
                    )
                    primary_key_fields.setdefault(
                        table_id,
                        set(),
                    ).update(
                        f"{table_id}.{column}"
                        for column in primary_key.columns
                    )
                grain_key_coverage = {
                    table_id: bool(
                        primary_key_fields.get(table_id)
                    )
                    and primary_key_fields[table_id].issubset(
                        direct_field_ids
                    )
                    for table_id in rerank_input_ids
                }
                if rerank_input_ids:
                    rerank_outcome = rerank_schema_candidates(
                        ranked_table_ids=rerank_input_ids,
                        fusion_scores=fusion_scores,
                        direct_field_counts=(
                            direct_field_counts
                        ),
                        approved_alias_counts=(
                            approved_alias_counts
                        ),
                        grain_key_coverage=(
                            grain_key_coverage
                        ),
                        direct_evidence_table_ids=(
                            raw_direct_evidence_table_ids
                        ),
                        authorized_snapshot=authorized,
                    )
                else:
                    rerank_outcome = RerankOutcome(
                        ranked_table_ids=(),
                        evidence=(),
                    )
            except Exception:
                if raw_fused_ids:
                    rerank_outcome = fallback_rerank_outcome(
                        ranked_table_ids=raw_fused_ids,
                        fusion_scores=raw_fusion_scores,
                    )
                else:
                    rerank_outcome = RerankOutcome(
                        ranked_table_ids=(),
                        evidence=(),
                        degraded=True,
                    )
            rerank_duration_ms = _elapsed_ms(
                rerank_started_ns
            )
            reranked_table_ids = (
                *rerank_outcome.ranked_table_ids,
                *(
                    object_id
                    for object_id in ranked_table_ids
                    if object_id
                    not in set(
                        rerank_outcome.ranked_table_ids
                    )
                ),
            )
            retrieval_pool = SchemaRetrievalPool(
                query_sha256=expected_query_sha256,
                schema_version=authorized.schema_version,
                authorization_scope_sha256=(
                    expected_scope_sha256
                ),
                retrieval_version_id=(
                    expected_version.retrieval_version_id
                ),
                retrieval_version_contract=(
                    RETRIEVAL_VERSION_CONTRACT
                ),
                bm25_version=expected_version.bm25_version,
                embedding_provider_contract_version=(
                    expected_version
                    .embedding_provider_contract_version
                ),
                embedding_provider_config_sha256=(
                    expected_version
                    .embedding_provider_config_sha256
                ),
                document_version=(
                    expected_version.document_version
                ),
                fusion_version=expected_version.fusion_version,
                rrf_k=expected_version.rrf_k,
                rerank_version=expected_version.rerank_version,
                mode=mode,
                ranked_table_ids=tuple(ranked_table_ids),
                ranked_field_ids=tuple(ranked_field_ids),
                table_evidence=_retrieval_evidence(
                    ordered_ids=tuple(ranked_table_ids),
                    bm25_scores=aggregate_scores,
                    bm25_ranked_ids=bm25_table_ranked_ids,
                    embedding_ranks=embedding_table_ranks,
                    fused=fused_tables,
                ),
                field_evidence=_retrieval_evidence(
                    ordered_ids=tuple(ranked_field_ids),
                    bm25_scores={
                        object_id: score.score
                        for object_id, score
                        in field_scores.items()
                    },
                    bm25_ranked_ids=bm25_field_ranked_ids,
                    embedding_ranks=embedding_field_ranks,
                    fused=fused_fields,
                ),
                reranked_table_ids=(
                    reranked_table_ids
                ),
                rerank_evidence=rerank_outcome.evidence,
                bm25_duration_ms=bm25_duration_ms,
                embedding_duration_ms=(
                    embedding_duration_ms
                ),
                rrf_duration_ms=rrf_duration_ms,
                rerank_duration_ms=rerank_duration_ms,
                embedding_degradation=degradation,
                rerank_degraded=rerank_outcome.degraded,
            )
            _remember_prepared_pool(
                retrieval_runtime,
                retrieval_pool
            )
        ranked_table_ids = list(
            (
                retrieval_pool.ranked_table_ids
                if prepared_pool is None
                else retrieval_pool.reranked_table_ids
            )
        )
        ranked_field_ids = list(
            retrieval_pool.ranked_field_ids
        )

    has_embedding_evidence = (
        retrieval_pool is not None
        and any(
            evidence.embedding_rank is not None
            for evidence in retrieval_pool.table_evidence
        )
    )
    selected_table_ids = (
        _select_table_ids(
            ranked_table_ids,
            graph,
            top_k=validated_top_k,
        )
        if positive_table_ids or has_embedding_evidence
        else ranked_table_ids[:validated_top_k]
    )
    selected_tables = tuple(
        table_by_id[object_id] for object_id in selected_table_ids
    )
    hybrid_table_scores = (
        {
            evidence.object_id: evidence.fusion_score
            for evidence in retrieval_pool.table_evidence
        }
        if retrieval_pool is not None
        else {}
    )
    candidates = tuple(
        CandidateTable(
            object_id=f"{table.schema_name}.{table.table_name}",
            schema_name=table.schema_name,
            table_name=table.table_name,
            relation_kind=table.relation_kind,
            comment=table.comment,
            score=max(
                aggregate_scores[
                    f"{table.schema_name}.{table.table_name}"
                ],
                hybrid_table_scores.get(
                    f"{table.schema_name}.{table.table_name}",
                    0.0,
                ),
            ),
            matched_tokens=aggregate_matches[
                f"{table.schema_name}.{table.table_name}"
            ],
        )
        for table in selected_tables
    )
    selected_rank = {
        object_id: rank
        for rank, object_id in enumerate(selected_table_ids)
    }
    retrieval_field_rank = {
        object_id: rank
        for rank, object_id in enumerate(ranked_field_ids)
    }
    selected_field_ids = sorted(
        (
            field_id
            for field_id, (table, _) in field_by_id.items()
            if f"{table.schema_name}.{table.table_name}"
            in selected_rank
        ),
        key=lambda field_id: (
            selected_rank[field_id.rsplit(".", 1)[0]],
            retrieval_field_rank[field_id],
            field_id,
        ),
    )
    hybrid_field_scores = (
        {
            evidence.object_id: evidence.fusion_score
            for evidence in retrieval_pool.field_evidence
        }
        if retrieval_pool is not None
        else {}
    )
    fields = tuple(
        CandidateField(
            object_id=field_id,
            schema_name=table.schema_name,
            table_name=table.table_name,
            column_name=column.column_name,
            formatted_type=column.formatted_type,
            nullable=column.nullable,
            comment=column.comment,
            score=max(
                field_scores[field_id].score,
                hybrid_field_scores.get(field_id, 0.0),
            ),
            matched_tokens=field_scores[field_id].matched_tokens,
        )
        for field_id in selected_field_ids
        for table, column in (field_by_id[field_id],)
    )
    return SchemaLinkingResult(
        candidate_tables=candidates,
        candidate_fields=fields,
        join_paths=_join_paths(selected_table_ids, graph),
        schema_version=authorized.schema_version,
        top_k=validated_top_k,
        retrieval_version_id=(
            retrieval_pool.retrieval_version_id
            if retrieval_pool is not None
            else None
        ),
        retrieval_pool=retrieval_pool,
    )
