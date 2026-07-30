from __future__ import annotations

import math
from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass, field
from itertools import combinations

from app.connectors.metadata import SchemaSnapshot
from app.schema_linking.models import (
    RerankEvidence,
    RerankReason,
)


class RerankError(RuntimeError):
    def __init__(self) -> None:
        super().__init__("schema rerank failed")


@dataclass(frozen=True, slots=True)
class RerankOutcome:
    ranked_table_ids: tuple[str, ...] = field(repr=False)
    evidence: tuple[RerankEvidence, ...] = field(repr=False)
    degraded: bool = False

    def __post_init__(self) -> None:
        ranked_set = set(self.ranked_table_ids)
        evidence_ids = {
            item.object_id for item in self.evidence
        }
        if (
            type(self.degraded) is not bool
            or len(ranked_set) != len(self.ranked_table_ids)
            or ranked_set != evidence_ids
            or tuple(
                item.rerank_rank for item in self.evidence
            )
            != tuple(range(1, len(self.evidence) + 1))
            or tuple(
                item.object_id for item in self.evidence
            )
            != self.ranked_table_ids
        ):
            raise ValueError("rerank outcome is invalid")


@dataclass(frozen=True, slots=True)
class _Features:
    object_id: str
    fusion_rank: int
    fusion_score: float
    direct_field_count: int
    approved_alias_count: int
    required_bridge: bool
    join_connected: bool
    relevant_path_edges: int | None
    grain_key_coverage: bool
    has_direct_evidence: bool

    @property
    def sort_key(self) -> tuple[object, ...]:
        return (
            0 if self.required_bridge else 1,
            -self.direct_field_count,
            -self.approved_alias_count,
            0 if self.join_connected else 1,
            (
                self.relevant_path_edges
                if self.relevant_path_edges is not None
                else math.inf
            ),
            0 if self.grain_key_coverage else 1,
            -self.fusion_score,
            self.object_id,
        )

    @property
    def before_fusion_key(self) -> tuple[object, ...]:
        return self.sort_key[:6]

    @property
    def before_canonical_key(self) -> tuple[object, ...]:
        return self.sort_key[:7]


def _distances(
    graph: Mapping[str, tuple[str, ...]],
    start: str,
    *,
    blocked: str | None = None,
) -> dict[str, int]:
    if start == blocked:
        return {}
    distances = {start: 0}
    pending = deque((start,))
    while pending:
        current = pending.popleft()
        for neighbor in graph[current]:
            if neighbor == blocked or neighbor in distances:
                continue
            distances[neighbor] = distances[current] + 1
            pending.append(neighbor)
    return distances


def _required_bridge(
    *,
    candidate: str,
    direct_pairs: tuple[tuple[str, str], ...],
    graph: Mapping[str, tuple[str, ...]],
    all_distances: Mapping[str, Mapping[str, int]],
) -> bool:
    for left, right in direct_pairs:
        if candidate in (left, right):
            continue
        if right not in all_distances[left]:
            continue
        if right not in _distances(
            graph,
            left,
            blocked=candidate,
        ):
            return True
    return False


def _effective_reason_codes(
    ordered: tuple[_Features, ...],
) -> dict[str, tuple[RerankReason, ...]]:
    reasons_by_id: dict[str, set[RerankReason]] = {
        item.object_id: set() for item in ordered
    }
    reason_for_key = (
        RerankReason.REQUIRED_BRIDGE,
        RerankReason.FIELD_COVERAGE,
        RerankReason.APPROVED_ALIAS,
        RerankReason.JOIN_CONNECTIVITY,
        RerankReason.SHORTER_JOIN_PATH,
        RerankReason.GRAIN_KEY_COVERAGE,
        RerankReason.FUSION_RANK,
        RerankReason.CANONICAL_TIE_BREAK,
    )
    for winner, loser in zip(
        ordered,
        ordered[1:],
        strict=False,
    ):
        differing_index = next(
            (
                index
                for index, (left, right) in enumerate(
                    zip(
                        winner.sort_key,
                        loser.sort_key,
                        strict=True,
                    )
                )
                if left != right
            ),
            None,
        )
        if differing_index is None:
            continue
        reasons_by_id[winner.object_id].add(
            reason_for_key[differing_index]
        )
        if (
            differing_index == 3
            and not loser.join_connected
            and not loser.has_direct_evidence
            and loser.direct_field_count == 0
            and loser.approved_alias_count == 0
        ):
            reasons_by_id[loser.object_id].add(
                RerankReason.DISCONNECTED_PENALTY
            )
    return {
        object_id: tuple(
            reason
            for reason in RerankReason
            if reason in reasons
        )
        for object_id, reasons in reasons_by_id.items()
    }


def _validate_count_mapping(
    values: Mapping[str, int],
    *,
    expected_ids: set[str],
) -> None:
    if (
        not isinstance(values, Mapping)
        or set(values) != expected_ids
        or any(
            type(value) is not int or value < 0
            for value in values.values()
        )
    ):
        raise RerankError() from None


def _validate_boolean_mapping(
    values: Mapping[str, bool],
    *,
    expected_ids: set[str],
) -> None:
    if (
        not isinstance(values, Mapping)
        or set(values) != expected_ids
        or any(type(value) is not bool for value in values.values())
    ):
        raise RerankError() from None


def find_required_bridge_table_ids(
    *,
    direct_evidence_table_ids: frozenset[str],
    authorized_snapshot: SchemaSnapshot,
) -> tuple[str, ...]:
    try:
        if not isinstance(
            direct_evidence_table_ids,
            frozenset,
        ):
            raise RerankError()
        authorized_table_ids = {
            f"{table.schema_name}.{table.table_name}"
            for table in authorized_snapshot.tables
        }
        if not direct_evidence_table_ids.issubset(
            authorized_table_ids
        ):
            raise RerankError()
        graph: dict[str, set[str]] = {
            object_id: set()
            for object_id in authorized_table_ids
        }
        for foreign_key in authorized_snapshot.foreign_keys:
            source = (
                f"{foreign_key.source_schema}."
                f"{foreign_key.source_table}"
            )
            target = (
                f"{foreign_key.target_schema}."
                f"{foreign_key.target_table}"
            )
            if (
                source not in authorized_table_ids
                or target not in authorized_table_ids
            ):
                raise RerankError()
            graph[source].add(target)
            graph[target].add(source)
        frozen_graph = {
            object_id: tuple(sorted(neighbors))
            for object_id, neighbors in graph.items()
        }
        all_distances = {
            object_id: _distances(frozen_graph, object_id)
            for object_id in authorized_table_ids
        }
        direct_pairs = tuple(
            combinations(
                sorted(direct_evidence_table_ids),
                2,
            )
        )
        return tuple(
            object_id
            for object_id in sorted(authorized_table_ids)
            if (
                object_id not in direct_evidence_table_ids
                and _required_bridge(
                    candidate=object_id,
                    direct_pairs=direct_pairs,
                    graph=frozen_graph,
                    all_distances=all_distances,
                )
            )
        )
    except RerankError:
        raise
    except Exception:
        raise RerankError() from None


def rerank_schema_candidates(
    *,
    ranked_table_ids: tuple[str, ...],
    fusion_scores: Mapping[str, float],
    direct_field_counts: Mapping[str, int],
    approved_alias_counts: Mapping[str, int],
    grain_key_coverage: Mapping[str, bool],
    direct_evidence_table_ids: frozenset[str],
    authorized_snapshot: SchemaSnapshot,
) -> RerankOutcome:
    try:
        if (
            not isinstance(ranked_table_ids, tuple)
            or not ranked_table_ids
            or len(set(ranked_table_ids))
            != len(ranked_table_ids)
            or any(
                not isinstance(object_id, str)
                or not object_id
                or object_id != object_id.strip()
                for object_id in ranked_table_ids
            )
            or not isinstance(
                direct_evidence_table_ids,
                frozenset,
            )
        ):
            raise RerankError()
        candidate_ids = set(ranked_table_ids)
        authorized_table_ids = {
            f"{table.schema_name}.{table.table_name}"
            for table in authorized_snapshot.tables
        }
        if (
            not candidate_ids.issubset(authorized_table_ids)
            or not direct_evidence_table_ids.issubset(
                candidate_ids
            )
            or not isinstance(fusion_scores, Mapping)
            or set(fusion_scores) != candidate_ids
            or any(
                type(value) not in (int, float)
                or not math.isfinite(float(value))
                or value < 0
                for value in fusion_scores.values()
            )
        ):
            raise RerankError()
        _validate_count_mapping(
            direct_field_counts,
            expected_ids=candidate_ids,
        )
        _validate_count_mapping(
            approved_alias_counts,
            expected_ids=candidate_ids,
        )
        _validate_boolean_mapping(
            grain_key_coverage,
            expected_ids=candidate_ids,
        )

        graph: dict[str, set[str]] = {
            object_id: set()
            for object_id in authorized_table_ids
        }
        for foreign_key in authorized_snapshot.foreign_keys:
            source = (
                f"{foreign_key.source_schema}."
                f"{foreign_key.source_table}"
            )
            target = (
                f"{foreign_key.target_schema}."
                f"{foreign_key.target_table}"
            )
            if (
                source not in authorized_table_ids
                or target not in authorized_table_ids
            ):
                raise RerankError()
            graph[source].add(target)
            graph[target].add(source)
        frozen_graph = {
            object_id: tuple(sorted(neighbors))
            for object_id, neighbors in graph.items()
        }
        all_distances = {
            object_id: _distances(frozen_graph, object_id)
            for object_id in authorized_table_ids
        }
        direct_pairs = tuple(
            combinations(
                sorted(direct_evidence_table_ids),
                2,
            )
        )

        features: list[_Features] = []
        for fusion_rank, object_id in enumerate(
            ranked_table_ids,
            start=1,
        ):
            relevant_lengths = tuple(
                all_distances[left][object_id]
                + all_distances[object_id][right]
                for left, right in direct_pairs
                if object_id in all_distances[left]
                and right in all_distances[object_id]
            )
            relevant_path_edges = (
                min(relevant_lengths)
                if relevant_lengths
                else None
            )
            features.append(
                _Features(
                    object_id=object_id,
                    fusion_rank=fusion_rank,
                    fusion_score=float(
                        fusion_scores[object_id]
                    ),
                    direct_field_count=(
                        direct_field_counts[object_id]
                    ),
                    approved_alias_count=(
                        approved_alias_counts[object_id]
                    ),
                    required_bridge=_required_bridge(
                        candidate=object_id,
                        direct_pairs=direct_pairs,
                        graph=frozen_graph,
                        all_distances=all_distances,
                    ),
                    join_connected=(
                        relevant_path_edges is not None
                    ),
                    relevant_path_edges=relevant_path_edges,
                    grain_key_coverage=(
                        grain_key_coverage[object_id]
                    ),
                    has_direct_evidence=(
                        object_id
                        in direct_evidence_table_ids
                    ),
                )
            )
        candidates = tuple(features)
        ordered = tuple(
            sorted(candidates, key=lambda item: item.sort_key)
        )
        reason_codes = _effective_reason_codes(ordered)
        evidence = tuple(
            RerankEvidence(
                object_id=item.object_id,
                fusion_rank=item.fusion_rank,
                rerank_rank=rank,
                fusion_score=item.fusion_score,
                direct_field_count=item.direct_field_count,
                approved_alias_count=item.approved_alias_count,
                required_bridge=item.required_bridge,
                join_connected=item.join_connected,
                relevant_path_edges=item.relevant_path_edges,
                has_direct_evidence=item.has_direct_evidence,
                reason_codes=reason_codes[item.object_id],
                grain_key_coverage=item.grain_key_coverage,
            )
            for rank, item in enumerate(ordered, start=1)
        )
        return RerankOutcome(
            ranked_table_ids=tuple(
                item.object_id for item in ordered
            ),
            evidence=evidence,
        )
    except RerankError:
        raise
    except Exception:
        raise RerankError() from None


def fallback_rerank_outcome(
    *,
    ranked_table_ids: tuple[str, ...],
    fusion_scores: Mapping[str, float],
) -> RerankOutcome:
    try:
        if (
            not ranked_table_ids
            or len(set(ranked_table_ids))
            != len(ranked_table_ids)
            or set(fusion_scores) != set(ranked_table_ids)
        ):
            raise RerankError()
        evidence = tuple(
            RerankEvidence(
                object_id=object_id,
                fusion_rank=rank,
                rerank_rank=rank,
                fusion_score=float(fusion_scores[object_id]),
                direct_field_count=0,
                approved_alias_count=0,
                required_bridge=False,
                join_connected=False,
                relevant_path_edges=None,
                has_direct_evidence=False,
                reason_codes=(),
            )
            for rank, object_id in enumerate(
                ranked_table_ids,
                start=1,
            )
        )
        return RerankOutcome(
            ranked_table_ids=ranked_table_ids,
            evidence=evidence,
            degraded=True,
        )
    except (TypeError, ValueError, RerankError):
        raise RerankError() from None
