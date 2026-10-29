"""Recall@k and MRR over evidence groups: deterministic, defined for every edge case."""

import pytest

from enterprise_knowledge.domain.ids import ChunkId
from enterprise_knowledge.evaluation.retrieval_metrics import (
    mean,
    recall_at_k,
    reciprocal_rank,
)

A, B, C, D, E = (ChunkId(x) for x in "abcde")


@pytest.mark.parametrize(
    ("ranked", "groups", "k", "expected"),
    [
        ([A, B, C], [{A}], 1, 1.0),
        ([B, A, C], [{A}], 1, 0.0),
        ([B, A, C], [{A}], 2, 1.0),
        ([A, D, E], [{A}, {B}], 3, 0.5),
        ([A, B, E], [{A}, {B}], 3, 1.0),
        ([C, E, D], [{A, C}], 3, 1.0),
        ([], [{A}], 5, 0.0),
    ],
    ids=[
        "top1-hit",
        "top1-miss",
        "top2-hit",
        "half-of-groups",
        "all-groups",
        "any-in-group",
        "nothing",
    ],
)
def test_recall_at_k_is_the_share_of_evidence_groups_covered(
    ranked: list[ChunkId], groups: list[set[ChunkId]], k: int, expected: float
) -> None:
    assert recall_at_k(ranked, groups, k=k) == expected


def test_one_chunk_can_cover_several_groups() -> None:
    assert recall_at_k([A], [{A}, {A, B}], k=1) == 1.0


@pytest.mark.parametrize(
    ("ranked", "groups", "expected"),
    [
        ([A, B, C], [{A}], 1.0),
        ([B, A, C], [{A}], 0.5),
        ([B, C, A], [{A}, {C}], 0.5),
        ([B, D, E], [{A}], 0.0),
        ([], [{A}], 0.0),
    ],
    ids=["first", "second", "first-of-any-group", "absent", "empty"],
)
def test_reciprocal_rank_uses_the_first_relevant_chunk(
    ranked: list[ChunkId], groups: list[set[ChunkId]], expected: float
) -> None:
    assert reciprocal_rank(ranked, groups) == expected


def test_questions_without_evidence_are_undefined_not_zero() -> None:
    """Unanswerable questions are scored separately; they must not drag recall down."""
    with pytest.raises(ValueError, match="evidence"):
        recall_at_k([A], [], k=1)
    with pytest.raises(ValueError, match="evidence"):
        reciprocal_rank([A], [])


def test_k_must_be_positive() -> None:
    with pytest.raises(ValueError, match="k"):
        recall_at_k([A], [{A}], k=0)


def test_empty_groups_are_rejected() -> None:
    with pytest.raises(ValueError, match="empty"):
        recall_at_k([A], [set()], k=1)


def test_mean_of_nothing_is_none() -> None:
    assert mean([]) is None
    assert mean([1.0, 0.0, 0.5]) == 0.5
