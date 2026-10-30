"""Reciprocal rank fusion (ADR-0014): pure, deterministic, rank-based."""

import pytest

from enterprise_knowledge.domain.ids import ChunkId
from enterprise_knowledge.retrieval.fusion import reciprocal_rank_fusion


def ids(*names: str) -> list[ChunkId]:
    return [ChunkId(n) for n in names]


def test_chunks_ranked_well_in_both_lists_come_first() -> None:
    fused = reciprocal_rank_fusion([ids("a", "b", "c"), ids("c", "a", "d")], rrf_k=60)

    assert [chunk for chunk, _ in fused] == ids("a", "c", "b", "d")


def test_score_is_the_sum_of_reciprocal_ranks() -> None:
    fused = dict(reciprocal_rank_fusion([ids("a", "b"), ids("b")], rrf_k=10))

    assert fused[ChunkId("a")] == pytest.approx(1 / 11)
    assert fused[ChunkId("b")] == pytest.approx(1 / 12 + 1 / 11)


def test_ties_are_broken_by_chunk_id() -> None:
    fused = reciprocal_rank_fusion([ids("z", "m"), ids("m", "z")], rrf_k=60)

    assert [chunk for chunk, _ in fused] == ids("m", "z")


def test_empty_rankings_fuse_to_nothing() -> None:
    assert reciprocal_rank_fusion([[], []], rrf_k=60) == []


def test_rrf_k_must_be_positive() -> None:
    with pytest.raises(ValueError, match="rrf_k"):
        reciprocal_rank_fusion([ids("a")], rrf_k=0)
