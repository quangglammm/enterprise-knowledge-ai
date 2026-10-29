"""Retrieval metrics over evidence groups (EVAL-01).

A question's ground truth is a list of evidence groups: each group is a set of chunks, any
one of which supplies that piece of evidence. A single-fact question has one group; a
multi-document question has one group per required fact. Rankings come from the search,
which breaks score ties by chunk ID (ADR-0007), so these numbers are deterministic.
"""

from collections.abc import Iterable, Sequence, Set

from enterprise_knowledge.domain.ids import ChunkId


def recall_at_k(ranked: Sequence[ChunkId], groups: Sequence[Set[ChunkId]], *, k: int) -> float:
    """Share of evidence groups with at least one chunk in the top ``k``."""
    _check(groups)
    if k < 1:
        raise ValueError("k must be at least 1")
    top = set(ranked[:k])
    return sum(1 for group in groups if group & top) / len(groups)


def reciprocal_rank(ranked: Sequence[ChunkId], groups: Sequence[Set[ChunkId]]) -> float:
    """1 / rank of the first chunk from any group; 0 when none was retrieved."""
    _check(groups)
    relevant = set().union(*groups)
    for rank, chunk_id in enumerate(ranked, start=1):
        if chunk_id in relevant:
            return 1.0 / rank
    return 0.0


def mean(values: Iterable[float]) -> float | None:
    items = list(values)
    return sum(items) / len(items) if items else None


def _check(groups: Sequence[Set[ChunkId]]) -> None:
    if not groups:
        raise ValueError("a question without evidence has no recall; score it as unanswerable")
    if any(not group for group in groups):
        raise ValueError("evidence groups must not be empty")
