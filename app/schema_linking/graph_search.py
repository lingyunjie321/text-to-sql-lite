"""Foreign-key graph construction and join path discovery."""

from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass
from itertools import combinations

from app.connectors.metadata import SchemaSnapshot
from app.schema_linking.models import JoinEdge, JoinPath, SchemaTopK

@dataclass(frozen=True, slots=True)
class _GraphStep:
    neighbor: str
    edge: JoinEdge
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

