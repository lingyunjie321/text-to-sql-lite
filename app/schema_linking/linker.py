import math
import re
import unicodedata
from collections import Counter, deque
from collections.abc import Mapping
from dataclasses import dataclass
from itertools import combinations

from app.connectors.metadata import (
    SchemaSnapshot,
    TableMetadata,
    build_schema_snapshot,
    normalize_metadata_scope,
)
from app.schema_linking.models import (
    TOP_K,
    CandidateField,
    CandidateTable,
    JoinEdge,
    JoinPath,
    SchemaLinkingResult,
)

_BM25_K1 = 1.5
_BM25_B = 0.75
_FIELD_AGGREGATION_WEIGHT = 0.35
_CAMEL_BOUNDARY = re.compile(
    r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])"
)
_WORD = re.compile(r"\w+", flags=re.UNICODE)


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
            - _BM25_B
            + _BM25_B * document_length / self._average_length
        )
        return (
            inverse_document_frequency
            * term_frequency
            * (_BM25_K1 + 1)
            / (
                term_frequency
                + _BM25_K1 * length_normalization
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
        if len(selected_set) + len(additions) <= TOP_K:
            selected.extend(additions)
            selected_set.update(additions)
        elif len(selected_set) < TOP_K:
            selected.append(candidate)
            selected_set.add(candidate)
        if len(selected_set) == TOP_K:
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


def _authorized_snapshot(
    *,
    allowed_schemas: tuple[str, ...],
    allowed_tables: tuple[str, ...],
    snapshot: SchemaSnapshot,
) -> SchemaSnapshot:
    try:
        scope = normalize_metadata_scope(allowed_schemas, allowed_tables)
    except ValueError:
        raise ValueError("schema linking context is invalid") from None

    visible_tables = set(scope.table_pairs)
    tables = tuple(
        table
        for table in snapshot.tables
        if (table.schema_name, table.table_name) in visible_tables
    )
    visible_columns = {
        (table.schema_name, table.table_name): {
            column.column_name for column in table.columns
        }
        for table in tables
    }

    def columns_are_visible(
        schema_name: str,
        table_name: str,
        columns: tuple[str, ...],
    ) -> bool:
        table_columns = visible_columns.get((schema_name, table_name))
        return (
            table_columns is not None
            and set(columns).issubset(table_columns)
        )

    primary_keys = tuple(
        key
        for key in snapshot.primary_keys
        if columns_are_visible(
            key.schema_name,
            key.table_name,
            key.columns,
        )
    )
    foreign_keys = tuple(
        key
        for key in snapshot.foreign_keys
        if columns_are_visible(
            key.source_schema,
            key.source_table,
            key.source_columns,
        )
        and columns_are_visible(
            key.target_schema,
            key.target_table,
            key.target_columns,
        )
    )
    unique_constraints = tuple(
        constraint
        for constraint in snapshot.unique_constraints
        if columns_are_visible(
            constraint.schema_name,
            constraint.table_name,
            constraint.columns,
        )
    )
    unique_indexes = tuple(
        index
        for index in snapshot.unique_indexes
        if columns_are_visible(
            index.schema_name,
            index.table_name,
            index.columns,
        )
    )
    return build_schema_snapshot(
        tables=tables,
        primary_keys=primary_keys,
        foreign_keys=foreign_keys,
        unique_constraints=unique_constraints,
        unique_indexes=unique_indexes,
    )


def link_schema(
    question: str,
    *,
    allowed_schemas: tuple[str, ...],
    allowed_tables: tuple[str, ...],
    snapshot: SchemaSnapshot,
) -> SchemaLinkingResult:
    authorized = _authorized_snapshot(
        allowed_schemas=allowed_schemas,
        allowed_tables=allowed_tables,
        snapshot=snapshot,
    )
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
    ranked_table_ids = sorted(
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
    selected_table_ids = (
        _select_table_ids(ranked_table_ids, graph)
        if positive_table_ids
        else ranked_table_ids[:TOP_K]
    )
    selected_tables = tuple(
        table_by_id[object_id] for object_id in selected_table_ids
    )
    candidates = tuple(
        CandidateTable(
            object_id=f"{table.schema_name}.{table.table_name}",
            schema_name=table.schema_name,
            table_name=table.table_name,
            relation_kind=table.relation_kind,
            comment=table.comment,
            score=aggregate_scores[
                f"{table.schema_name}.{table.table_name}"
            ],
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
    selected_field_ids = sorted(
        (
            field_id
            for field_id, (table, _) in field_by_id.items()
            if f"{table.schema_name}.{table.table_name}"
            in selected_rank
        ),
        key=lambda field_id: (
            selected_rank[field_id.rsplit(".", 1)[0]],
            -field_scores[field_id].score,
            field_id,
        ),
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
            score=field_scores[field_id].score,
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
    )
