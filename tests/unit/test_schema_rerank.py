from dataclasses import FrozenInstanceError, replace

import pytest

from app.connectors.metadata import (
    ForeignKeyMetadata,
    TableMetadata,
    build_schema_snapshot,
)


def _table(name: str) -> TableMetadata:
    return TableMetadata(
        schema_name="public",
        table_name=name,
        relation_kind="table",
        comment=None,
        columns=(),
    )


def _snapshot(
    names: tuple[str, ...],
    edges: tuple[tuple[str, str], ...],
):
    return build_schema_snapshot(
        tables=tuple(_table(name) for name in names),
        primary_keys=(),
        foreign_keys=tuple(
            ForeignKeyMetadata(
                constraint_name=f"{left}_{right}_fkey",
                source_schema="public",
                source_table=left,
                source_columns=("left_id",),
                target_schema="public",
                target_table=right,
                target_columns=("right_id",),
            )
            for left, right in edges
        ),
        unique_constraints=(),
        unique_indexes=(),
    )


def _rerank(
    names: tuple[str, ...],
    edges: tuple[tuple[str, str], ...],
    *,
    field_counts: dict[str, int] | None = None,
    alias_counts: dict[str, int] | None = None,
    grain_key_coverage: dict[str, bool] | None = None,
    direct: frozenset[str] = frozenset(),
    fusion_scores: dict[str, float] | None = None,
):
    from app.schema_linking.rerank import rerank_schema_candidates

    object_ids = tuple(f"public.{name}" for name in names)
    return rerank_schema_candidates(
        ranked_table_ids=object_ids,
        fusion_scores=(
            fusion_scores
            or {
                object_id: 1 / (61 + rank)
                for rank, object_id in enumerate(object_ids)
            }
        ),
        direct_field_counts=(
            field_counts
            or {object_id: 0 for object_id in object_ids}
        ),
        approved_alias_counts=(
            alias_counts
            or {object_id: 0 for object_id in object_ids}
        ),
        grain_key_coverage=(
            grain_key_coverage
            or {object_id: False for object_id in object_ids}
        ),
        direct_evidence_table_ids=direct,
        authorized_snapshot=_snapshot(names, edges),
    )


def test_required_bridge_outranks_direct_candidates() -> None:
    outcome = _rerank(
        ("film", "actor", "film_actor"),
        (("film", "film_actor"), ("film_actor", "actor")),
        field_counts={
            "public.film": 1,
            "public.actor": 1,
            "public.film_actor": 0,
        },
        direct=frozenset({"public.film", "public.actor"}),
        fusion_scores={
            "public.film": 0.03,
            "public.actor": 0.02,
            "public.film_actor": 0.001,
        },
    )

    assert outcome.ranked_table_ids[0] == "public.film_actor"
    bridge = next(
        item
        for item in outcome.evidence
        if item.object_id == "public.film_actor"
    )
    assert bridge.required_bridge is True
    assert tuple(reason.value for reason in bridge.reason_codes) == (
        "required_bridge",
    )


def test_direct_candidate_can_also_be_a_required_bridge() -> None:
    outcome = _rerank(
        ("a", "c", "b"),
        (("a", "b"), ("b", "c")),
        field_counts={
            "public.a": 2,
            "public.b": 0,
            "public.c": 2,
        },
        direct=frozenset(
            {"public.a", "public.b", "public.c"}
        ),
    )

    bridge = next(
        item
        for item in outcome.evidence
        if item.object_id == "public.b"
    )
    assert bridge.required_bridge is True
    assert bridge.has_direct_evidence is True
    assert outcome.ranked_table_ids[0] == "public.b"


def test_alternative_paths_are_not_marked_as_required_bridges() -> None:
    outcome = _rerank(
        ("a", "c", "b", "d"),
        (("a", "b"), ("b", "c"), ("a", "d"), ("d", "c")),
        direct=frozenset({"public.a", "public.c"}),
    )

    evidence = {
        item.object_id: item for item in outcome.evidence
    }
    assert evidence["public.b"].required_bridge is False
    assert evidence["public.d"].required_bridge is False


def test_required_bridge_features_use_the_full_authorized_graph() -> None:
    from app.schema_linking.rerank import rerank_schema_candidates

    candidates = (
        "public.a",
        "public.d",
        "public.x",
        "public.y",
    )
    outcome = rerank_schema_candidates(
        ranked_table_ids=candidates,
        fusion_scores={
            object_id: 1 / (61 + rank)
            for rank, object_id in enumerate(candidates)
        },
        direct_field_counts={
            object_id: 0 for object_id in candidates
        },
        approved_alias_counts={
            object_id: 0 for object_id in candidates
        },
        grain_key_coverage={
            object_id: False for object_id in candidates
        },
        direct_evidence_table_ids=frozenset(
            {"public.a", "public.d"}
        ),
        authorized_snapshot=_snapshot(
            ("a", "b", "c", "x", "y", "d"),
            (
                ("a", "b"),
                ("a", "c"),
                ("b", "x"),
                ("c", "x"),
                ("x", "y"),
                ("y", "d"),
            ),
        ),
    )

    evidence = {
        item.object_id: item for item in outcome.evidence
    }
    assert evidence["public.x"].required_bridge is True
    assert evidence["public.y"].required_bridge is True
    assert all(item.join_connected for item in outcome.evidence)


def test_field_coverage_precedes_higher_fusion_score() -> None:
    outcome = _rerank(
        ("b", "a"),
        (),
        field_counts={"public.a": 2, "public.b": 1},
        direct=frozenset({"public.a", "public.b"}),
        fusion_scores={"public.a": 0.01, "public.b": 0.5},
    )

    assert outcome.ranked_table_ids == ("public.a", "public.b")
    assert next(
        item for item in outcome.evidence
        if item.object_id == "public.a"
    ).direct_field_count == 2


def test_shorter_relevant_path_precedes_longer_alternative() -> None:
    outcome = _rerank(
        ("a", "b", "x", "y", "z"),
        (
            ("a", "x"),
            ("x", "b"),
            ("a", "y"),
            ("y", "z"),
            ("z", "b"),
        ),
        direct=frozenset({"public.a", "public.b"}),
        field_counts={
            "public.a": 1,
            "public.b": 1,
            "public.x": 0,
            "public.y": 0,
            "public.z": 0,
        },
    )

    assert outcome.ranked_table_ids.index(
        "public.x"
    ) < outcome.ranked_table_ids.index("public.y")
    x_evidence = next(
        item
        for item in outcome.evidence
        if item.object_id == "public.x"
    )
    assert x_evidence.relevant_path_edges == 2
    assert "shorter_join_path" in {
        reason.value for reason in x_evidence.reason_codes
    }


def test_connected_zero_evidence_precedes_disconnected_higher_rrf() -> None:
    outcome = _rerank(
        ("orphan", "x", "a", "b"),
        (("a", "x"), ("x", "b")),
        direct=frozenset({"public.a", "public.b"}),
        fusion_scores={
            "public.orphan": 1.0,
            "public.x": 0.001,
            "public.a": 0.0009,
            "public.b": 0.0008,
        },
    )

    assert outcome.ranked_table_ids.index(
        "public.x"
    ) < outcome.ranked_table_ids.index("public.orphan")
    orphan = next(
        item
        for item in outcome.evidence
        if item.object_id == "public.orphan"
    )
    assert tuple(reason.value for reason in orphan.reason_codes) == (
        "disconnected_penalty",
    )


def test_fusion_then_canonical_id_break_exact_feature_ties() -> None:
    fusion = _rerank(
        ("b", "a"),
        (),
        direct=frozenset({"public.a", "public.b"}),
        fusion_scores={"public.a": 0.2, "public.b": 0.1},
    )
    canonical = _rerank(
        ("b", "a"),
        (),
        direct=frozenset({"public.a", "public.b"}),
        fusion_scores={"public.a": 0.1, "public.b": 0.1},
    )

    assert fusion.ranked_table_ids == ("public.a", "public.b")
    assert canonical.ranked_table_ids == ("public.a", "public.b")
    assert "fusion_rank" in {
        reason.value
        for reason in next(
            item for item in fusion.evidence
            if item.object_id == "public.a"
        ).reason_codes
    }
    assert "canonical_tie_break" in {
        reason.value
        for reason in next(
            item for item in canonical.evidence
            if item.object_id == "public.a"
        ).reason_codes
    }


def test_complete_primary_key_evidence_explains_table_grain() -> None:
    outcome = _rerank(
        ("b", "a"),
        (),
        direct=frozenset({"public.a", "public.b"}),
        fusion_scores={"public.a": 0.1, "public.b": 0.1},
        grain_key_coverage={
            "public.a": True,
            "public.b": False,
        },
    )

    assert outcome.ranked_table_ids == ("public.a", "public.b")
    evidence = next(
        item
        for item in outcome.evidence
        if item.object_id == "public.a"
    )
    assert evidence.grain_key_coverage is True
    assert "grain_key_coverage" in {
        reason.value for reason in evidence.reason_codes
    }


def test_single_candidate_has_no_non_effective_reason_codes() -> None:
    outcome = _rerank(
        ("a",),
        (),
        field_counts={"public.a": 1},
        alias_counts={"public.a": 1},
        direct=frozenset({"public.a"}),
        fusion_scores={"public.a": 0.2},
    )

    assert outcome.evidence[0].reason_codes == ()


def test_rerank_is_closed_and_deeply_immutable() -> None:
    from app.schema_linking.rerank import rerank_schema_candidates

    outcome = rerank_schema_candidates(
        ranked_table_ids=("public.a", "public.b"),
        fusion_scores={"public.a": 0.2, "public.b": 0.1},
        direct_field_counts={"public.a": 0, "public.b": 0},
        approved_alias_counts={"public.a": 0, "public.b": 0},
        grain_key_coverage={
            "public.a": False,
            "public.b": False,
        },
        direct_evidence_table_ids=frozenset(
            {"public.a", "public.b"}
        ),
        authorized_snapshot=_snapshot(
            ("a", "b", "bridge"),
            (("a", "bridge"), ("bridge", "b")),
        ),
    )

    assert set(outcome.ranked_table_ids) == {
        "public.a",
        "public.b",
    }
    with pytest.raises(FrozenInstanceError):
        outcome.degraded = True  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        outcome.evidence[0].rerank_rank = 2  # type: ignore[misc]


def test_probe_keeps_fusion_baseline_and_materialization_uses_rerank(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.schema_linking.linker as linker_module
    from app.schema_linking import (
        EmbeddingIndexRegistry,
        RerankEvidence,
        RetrievalRuntime,
        link_schema,
    )
    from app.schema_linking.rerank import RerankOutcome
    from tests.unit.test_schema_embedding_index import (
        StubEmbeddingProvider,
    )

    names = ("a", "b", "c", "d", "e", "f")
    snapshot = _snapshot(names, ())
    allowed_tables = tuple(
        f"public.{name}" for name in names
    )

    def reverse_rerank(**kwargs: object) -> RerankOutcome:
        ranked = kwargs["ranked_table_ids"]
        scores = kwargs["fusion_scores"]
        assert isinstance(ranked, tuple)
        assert isinstance(scores, dict)
        reversed_ids = tuple(reversed(ranked))
        return RerankOutcome(
            ranked_table_ids=reversed_ids,
            evidence=tuple(
                RerankEvidence(
                    object_id=object_id,
                    fusion_rank=ranked.index(object_id) + 1,
                    rerank_rank=rank,
                    fusion_score=float(scores[object_id]),
                    direct_field_count=0,
                    approved_alias_count=0,
                    required_bridge=False,
                    join_connected=False,
                    relevant_path_edges=None,
                    has_direct_evidence=False,
                    reason_codes=(),
                )
                for rank, object_id in enumerate(
                    reversed_ids,
                    start=1,
                )
            ),
        )

    monkeypatch.setattr(
        linker_module,
        "rerank_schema_candidates",
        reverse_rerank,
    )
    runtime = RetrievalRuntime(
        provider=StubEmbeddingProvider(),
        registry=EmbeddingIndexRegistry(),
        semantic_version="semantic-v1",
    )
    probe = link_schema(
        "unmatched",
        datasource_id="pagila",
        allowed_schemas=("public",),
        allowed_tables=allowed_tables,
        snapshot=snapshot,
        top_k=20,
        retrieval_runtime=runtime,
    )
    assert probe.retrieval_pool is not None

    materialized = link_schema(
        "unmatched",
        datasource_id="pagila",
        allowed_schemas=("public",),
        allowed_tables=allowed_tables,
        snapshot=snapshot,
        top_k=5,
        retrieval_runtime=runtime,
        prepared_pool=probe.retrieval_pool,
    )

    assert tuple(
        item.object_id for item in probe.candidate_tables
    ) == probe.retrieval_pool.ranked_table_ids
    assert tuple(
        item.object_id for item in materialized.candidate_tables
    ) == probe.retrieval_pool.reranked_table_ids[:5]


def test_rerank_internal_error_falls_back_atomically_without_reembedding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.schema_linking.linker as linker_module
    from app.schema_linking import (
        EmbeddingIndexRegistry,
        RetrievalRuntime,
        link_schema,
    )
    from tests.unit.test_schema_embedding_index import (
        StubEmbeddingProvider,
    )

    monkeypatch.setattr(
        linker_module,
        "rerank_schema_candidates",
        lambda **kwargs: (_ for _ in ()).throw(
            RuntimeError("partial private rerank state")
        ),
    )
    snapshot = _snapshot(("a", "b"), ())
    provider = StubEmbeddingProvider()
    runtime = RetrievalRuntime(
        provider=provider,
        registry=EmbeddingIndexRegistry(),
        semantic_version="semantic-v1",
    )
    probe = link_schema(
        "unmatched",
        datasource_id="pagila",
        allowed_schemas=("public",),
        allowed_tables=("public.a", "public.b"),
        snapshot=snapshot,
        top_k=20,
        retrieval_runtime=runtime,
    )
    assert probe.retrieval_pool is not None
    calls_after_probe = len(provider.calls)

    materialized = link_schema(
        "unmatched",
        datasource_id="pagila",
        allowed_schemas=("public",),
        allowed_tables=("public.a", "public.b"),
        snapshot=snapshot,
        top_k=5,
        retrieval_runtime=runtime,
        prepared_pool=probe.retrieval_pool,
    )

    pool = probe.retrieval_pool
    assert pool.rerank_degraded is True
    assert pool.reranked_table_ids == pool.ranked_table_ids
    assert len(pool.rerank_evidence) == len(
        pool.ranked_table_ids
    )
    assert tuple(
        item.rerank_rank for item in pool.rerank_evidence
    ) == tuple(range(1, len(pool.ranked_table_ids) + 1))
    assert materialized.retrieval_pool is pool
    assert len(provider.calls) == calls_after_probe == 2


def test_bridge_analysis_failure_uses_atomic_rerank_fallback_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.schema_linking.linker as linker_module
    from app.schema_linking import (
        EmbeddingIndexRegistry,
        RetrievalRuntime,
        link_schema,
    )
    from tests.unit.test_schema_embedding_index import (
        StubEmbeddingProvider,
    )

    bridge_calls = 0

    def fail_bridge_analysis(**kwargs: object):
        del kwargs
        nonlocal bridge_calls
        bridge_calls += 1
        raise RuntimeError("private graph failure")

    monkeypatch.setattr(
        linker_module,
        "find_required_bridge_table_ids",
        fail_bridge_analysis,
    )
    snapshot = _snapshot(("a", "b"), ())
    runtime = RetrievalRuntime(
        provider=StubEmbeddingProvider(),
        registry=EmbeddingIndexRegistry(),
        semantic_version="semantic-v1",
    )
    probe = link_schema(
        "unmatched",
        datasource_id="pagila",
        allowed_schemas=("public",),
        allowed_tables=("public.a", "public.b"),
        snapshot=snapshot,
        top_k=20,
        retrieval_runtime=runtime,
    )
    assert probe.retrieval_pool is not None

    materialized = link_schema(
        "unmatched",
        datasource_id="pagila",
        allowed_schemas=("public",),
        allowed_tables=("public.a", "public.b"),
        snapshot=snapshot,
        top_k=5,
        retrieval_runtime=runtime,
        prepared_pool=probe.retrieval_pool,
    )

    pool = probe.retrieval_pool
    assert bridge_calls == 1
    assert pool.rerank_degraded is True
    assert pool.reranked_table_ids == pool.ranked_table_ids
    assert materialized.retrieval_pool is pool


def test_materialization_does_not_execute_rerank_a_second_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.schema_linking.linker as linker_module
    from app.schema_linking import (
        EmbeddingIndexRegistry,
        RetrievalRuntime,
        link_schema,
    )
    from tests.unit.test_schema_embedding_index import (
        StubEmbeddingProvider,
    )

    real_rerank = linker_module.rerank_schema_candidates
    rerank_calls = 0

    def one_successful_rerank(**kwargs: object):
        nonlocal rerank_calls
        rerank_calls += 1
        if rerank_calls > 1:
            raise RuntimeError("transient private rerank failure")
        return real_rerank(**kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(
        linker_module,
        "rerank_schema_candidates",
        one_successful_rerank,
    )
    snapshot = _snapshot(("a", "b"), ())
    runtime = RetrievalRuntime(
        provider=StubEmbeddingProvider(),
        registry=EmbeddingIndexRegistry(),
        semantic_version="semantic-v1",
    )
    probe = link_schema(
        "unmatched",
        datasource_id="pagila",
        allowed_schemas=("public",),
        allowed_tables=("public.a", "public.b"),
        snapshot=snapshot,
        top_k=20,
        retrieval_runtime=runtime,
    )
    assert probe.retrieval_pool is not None
    assert probe.retrieval_pool.rerank_degraded is False

    materialized = link_schema(
        "unmatched",
        datasource_id="pagila",
        allowed_schemas=("public",),
        allowed_tables=("public.a", "public.b"),
        snapshot=snapshot,
        top_k=5,
        retrieval_runtime=runtime,
        prepared_pool=probe.retrieval_pool,
    )

    assert rerank_calls == 1
    assert materialized.retrieval_pool is probe.retrieval_pool


def test_linker_reranks_only_rrf_candidates_not_lexical_remainder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.schema_linking.linker as linker_module
    from app.schema_linking import (
        EmbeddingIndexRegistry,
        RetrievalRuntime,
        link_schema,
    )
    from tests.unit.test_schema_embedding_index import (
        StubEmbeddingProvider,
    )

    names = tuple(f"table_{number:02d}" for number in range(21))
    tables = tuple(
        replace(_table(name), aliases=("sharedmatch",))
        for name in names
    )
    snapshot = build_schema_snapshot(
        tables=tables,
        primary_keys=(),
        foreign_keys=(),
        unique_constraints=(),
        unique_indexes=(),
    )
    captured_ids: list[tuple[str, ...]] = []
    real_rerank = linker_module.rerank_schema_candidates

    def capture_rerank(**kwargs: object):
        ranked = kwargs["ranked_table_ids"]
        assert isinstance(ranked, tuple)
        captured_ids.append(ranked)
        return real_rerank(**kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(
        linker_module,
        "rerank_schema_candidates",
        capture_rerank,
    )
    result = link_schema(
        "sharedmatch",
        datasource_id="pagila",
        allowed_schemas=("public",),
        allowed_tables=tuple(
            f"public.{name}" for name in names
        ),
        snapshot=snapshot,
        top_k=20,
        retrieval_runtime=RetrievalRuntime(
            provider=StubEmbeddingProvider(),
            registry=EmbeddingIndexRegistry(),
            semantic_version="semantic-v1",
        ),
    )
    assert result.retrieval_pool is not None
    fusion_ids = {
        item.object_id
        for item in result.retrieval_pool.table_evidence
        if item.fusion_rank is not None
    }

    assert len(fusion_ids) == 20
    assert len(captured_ids) == 1
    assert set(captured_ids[0]) == fusion_ids
    assert len(result.retrieval_pool.rerank_evidence) == 20


def test_linker_adds_only_required_bridge_to_rerank_closure() -> None:
    import json

    from app.connectors.metadata import ColumnMetadata
    from app.schema_linking import (
        EmbeddingIndexRegistry,
        RetrievalRuntime,
        link_schema,
    )
    from tests.unit.test_schema_embedding_index import (
        StubEmbeddingProvider,
    )

    def table(name: str, alias: str | None = None):
        return replace(
            _table(name),
            aliases=(alias,) if alias is not None else (),
            columns=(
                ColumnMetadata(
                    schema_name="public",
                    table_name=name,
                    column_name="entity_id",
                    ordinal_position=1,
                    data_type="int4",
                    formatted_type="integer",
                    nullable=False,
                    comment=None,
                ),
            ),
        )

    snapshot = build_schema_snapshot(
        tables=(
            table("alpha", "leftterm"),
            table("beta", "rightterm"),
            table("link"),
            table("orphan"),
        ),
        primary_keys=(),
        foreign_keys=(
            ForeignKeyMetadata(
                constraint_name="alpha_link_fkey",
                source_schema="public",
                source_table="alpha",
                source_columns=("entity_id",),
                target_schema="public",
                target_table="link",
                target_columns=("entity_id",),
            ),
            ForeignKeyMetadata(
                constraint_name="link_beta_fkey",
                source_schema="public",
                source_table="link",
                source_columns=("entity_id",),
                target_schema="public",
                target_table="beta",
                target_columns=("entity_id",),
            ),
        ),
        unique_constraints=(),
        unique_indexes=(),
    )

    class BridgeEmbeddingProvider(StubEmbeddingProvider):
        def embed(self, texts, *, timeout_seconds=None):
            self.calls.append(tuple(texts))
            self.timeouts.append(timeout_seconds)
            return tuple(
                (
                    (1.0, 0.0)
                    if not text.startswith("{")
                    or json.loads(text)["object_id"]
                    in {"public.alpha", "public.beta"}
                    else (-1.0, 0.0)
                )
                for text in texts
            )

    result = link_schema(
        "leftterm rightterm",
        datasource_id="pagila",
        allowed_schemas=("public",),
        allowed_tables=(
            "public.alpha",
            "public.beta",
            "public.link",
            "public.orphan",
        ),
        snapshot=snapshot,
        top_k=20,
        retrieval_runtime=RetrievalRuntime(
            provider=BridgeEmbeddingProvider(),
            registry=EmbeddingIndexRegistry(),
            semantic_version="semantic-v1",
        ),
    )
    assert result.retrieval_pool is not None
    rerank_by_id = {
        item.object_id: item
        for item in result.retrieval_pool.rerank_evidence
    }

    assert set(rerank_by_id) == {
        "public.alpha",
        "public.beta",
        "public.link",
    }
    assert rerank_by_id["public.link"].required_bridge is True
    assert "public.orphan" not in rerank_by_id


@pytest.mark.parametrize(
    "mutation",
    ("unknown_table", "missing_score", "negative_count"),
)
def test_rerank_rejects_invalid_or_unauthorized_input(
    mutation: str,
) -> None:
    from app.schema_linking.rerank import (
        RerankError,
        rerank_schema_candidates,
    )

    ranked = ("public.a", "public.b")
    scores = {"public.a": 0.2, "public.b": 0.1}
    fields = {"public.a": 0, "public.b": 0}
    if mutation == "unknown_table":
        ranked = (*ranked, "private.secret")
        scores["private.secret"] = 1.0
        fields["private.secret"] = 0
    elif mutation == "missing_score":
        scores.pop("public.b")
    else:
        fields["public.b"] = -1

    with pytest.raises(RerankError):
        rerank_schema_candidates(
            ranked_table_ids=ranked,
            fusion_scores=scores,
            direct_field_counts=fields,
            approved_alias_counts={
                object_id: 0 for object_id in ranked
            },
            grain_key_coverage={
                object_id: False for object_id in ranked
            },
            direct_evidence_table_ids=frozenset(),
            authorized_snapshot=_snapshot(("a", "b"), ()),
        )
