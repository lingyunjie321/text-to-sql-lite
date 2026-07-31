"""BM25 scoring and document builders for schema retrieval."""

import math
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass

from app.connectors.metadata import TableMetadata
from app.schema_linking._tokenizer import _tokenize, _weighted_tokens

BM25_K1 = 1.5
BM25_B = 0.75
@dataclass(frozen=True, slots=True)
class _DocumentScore:
    score: float
    matched_tokens: tuple[str, ...]

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
