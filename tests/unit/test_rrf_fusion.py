from dataclasses import FrozenInstanceError
from inspect import signature

import pytest


def test_rrf_uses_one_based_rank_and_not_raw_channel_scores() -> None:
    from app.schema_linking.fusion import reciprocal_rank_fusion

    result = reciprocal_rank_fusion(
        {
            "bm25": (
                "public.film",
                "public.actor",
                "public.payment",
            ),
            "embedding": (
                "public.actor",
                "public.payment",
                "public.film",
            ),
        },
        k=60,
    )

    assert tuple(item.object_id for item in result) == (
        "public.actor",
        "public.film",
        "public.payment",
    )
    actor = result[0]
    assert actor.score == pytest.approx(1 / 62 + 1 / 61)
    assert tuple(
        (contribution.channel, contribution.rank)
        for contribution in actor.contributions
    ) == (("bm25", 2), ("embedding", 1))
    assert tuple(
        contribution.value
        for contribution in actor.contributions
    ) == pytest.approx((1 / 62, 1 / 61))


def test_rrf_exact_score_tie_uses_canonical_object_id() -> None:
    from app.schema_linking.fusion import reciprocal_rank_fusion

    result = reciprocal_rank_fusion(
        {
            "bm25": ("public.beta", "public.alpha"),
            "embedding": ("public.alpha", "public.beta"),
        }
    )

    assert tuple(item.object_id for item in result) == (
        "public.alpha",
        "public.beta",
    )
    assert result[0].score == result[1].score


def test_rrf_keeps_only_the_first_duplicate_rank_per_channel() -> None:
    from app.schema_linking.fusion import reciprocal_rank_fusion

    result = reciprocal_rank_fusion(
        {
            "bm25": (
                "public.film",
                "public.film",
                "public.actor",
            ),
            "embedding": (),
        }
    )

    assert tuple(item.object_id for item in result) == (
        "public.film",
        "public.actor",
    )
    assert result[0].contributions[0].rank == 1
    assert result[1].contributions[0].rank == 2


@pytest.mark.parametrize(
    "channels",
    (
        {},
        {"bm25": ()},
        {"embedding": ()},
        {"bm25": (), "embedding": ()},
    ),
)
def test_rrf_accepts_missing_or_empty_channels(
    channels: dict[str, tuple[str, ...]],
) -> None:
    from app.schema_linking.fusion import reciprocal_rank_fusion

    assert reciprocal_rank_fusion(channels) == ()


def test_rrf_keeps_a_candidate_missing_from_one_channel() -> None:
    from app.schema_linking.fusion import reciprocal_rank_fusion

    result = reciprocal_rank_fusion(
        {
            "embedding": (
                "public.actor",
                "public.film",
            )
        }
    )

    assert tuple(item.object_id for item in result) == (
        "public.actor",
        "public.film",
    )
    assert result[0].contributions[0].value == pytest.approx(1 / 61)


def test_rrf_channel_mapping_order_does_not_change_evidence_order() -> None:
    from app.schema_linking.fusion import reciprocal_rank_fusion

    forward = reciprocal_rank_fusion(
        {
            "bm25": ("public.film", "public.actor"),
            "embedding": ("public.actor", "public.film"),
        }
    )
    reversed_channels = reciprocal_rank_fusion(
        {
            "embedding": ("public.actor", "public.film"),
            "bm25": ("public.film", "public.actor"),
        }
    )

    assert forward == reversed_channels
    assert tuple(
        contribution.channel
        for contribution in forward[0].contributions
    ) == ("bm25", "embedding")


def test_rrf_rejects_raw_scores_and_exposes_no_score_parameters() -> None:
    from app.schema_linking.fusion import reciprocal_rank_fusion

    with pytest.raises(
        ValueError,
        match=r"^RRF input is invalid$",
    ):
        reciprocal_rank_fusion(
            {
                "bm25": (
                    ("public.film", 999.0),
                ),
            }  # type: ignore[arg-type]
        )

    parameters = signature(
        reciprocal_rank_fusion
    ).parameters
    assert tuple(parameters) == ("channels", "k")
    assert not {
        "scores",
        "weights",
        "similarities",
    }.intersection(parameters)


@pytest.mark.parametrize("k", (True, 0, -1, 60.0, "60"))
def test_rrf_rejects_invalid_k(k: object) -> None:
    from app.schema_linking.fusion import reciprocal_rank_fusion

    with pytest.raises(
        ValueError,
        match=r"^RRF input is invalid$",
    ):
        reciprocal_rank_fusion(
            {"bm25": ("public.film",)},
            k=k,  # type: ignore[arg-type]
        )


@pytest.mark.parametrize(
    "channels",
    (
        {"unknown": ("public.film",)},
        {"bm25": ["public.film"]},
        {"bm25": ("",)},
        {"bm25": (" public.film",)},
        {"bm25": (1,)},
    ),
)
def test_rrf_rejects_invalid_channel_ranks(
    channels: object,
) -> None:
    from app.schema_linking.fusion import reciprocal_rank_fusion

    with pytest.raises(
        ValueError,
        match=r"^RRF input is invalid$",
    ):
        reciprocal_rank_fusion(channels)  # type: ignore[arg-type]


def test_rrf_results_are_deeply_immutable() -> None:
    from app.schema_linking.fusion import reciprocal_rank_fusion

    result = reciprocal_rank_fusion(
        {"bm25": ("public.film",)}
    )

    with pytest.raises(FrozenInstanceError):
        result[0].score = 0  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        result[0].contributions[0].rank = 2  # type: ignore[misc]
