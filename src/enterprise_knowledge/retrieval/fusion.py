"""Reciprocal rank fusion (Cormack et al., 2009) for hybrid retrieval (ADR-0014).

Uses ranks only, so vector cosine similarity and lexical IDF scores, which live on
different scales, never need to be calibrated against each other.
"""

from collections import defaultdict
from collections.abc import Sequence

from enterprise_knowledge.domain.ids import ChunkId


def reciprocal_rank_fusion(
    rankings: Sequence[Sequence[ChunkId]], *, rrf_k: int
) -> list[tuple[ChunkId, float]]:
    """Chunks by fused score ``sum(1 / (rrf_k + rank))``, best first; ties by chunk ID."""
    if rrf_k < 1:
        raise ValueError("rrf_k must be at least 1")
    scores: dict[ChunkId, float] = defaultdict(float)
    for ranking in rankings:
        for rank, chunk_id in enumerate(ranking, start=1):
            scores[chunk_id] += 1.0 / (rrf_k + rank)
    return sorted(scores.items(), key=lambda item: (-item[1], item[0]))
