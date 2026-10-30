"""SearchKnowledge use case: query text to ranked, access-checked evidence.

``vector`` mode ranks by embedding similarity. ``hybrid`` mode (ADR-0014) also runs
full-text search and fuses the two rankings with reciprocal rank fusion. Both lists are
filtered by tenant, groups and version inside their own queries (ADR-0003); fusion only
reorders evidence the principal may already read.
"""

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from enterprise_knowledge.domain.access import Principal, ensure_accessible
from enterprise_knowledge.domain.ports import ChunkSearch, Embedder, Vector
from enterprise_knowledge.domain.retrieval import RetrievedEvidence
from enterprise_knowledge.domain.text import normalize_nfc
from enterprise_knowledge.retrieval.errors import InvalidQueryError
from enterprise_knowledge.retrieval.fusion import reciprocal_rank_fusion

MAX_QUERY_CHARS = 2000
MAX_K = 20
_HAS_WORD = re.compile(r"\w", re.UNICODE)


class RetrievalSettings(BaseModel):
    """How chunks are ranked. Recorded with every evaluation run (ADR-0013)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    mode: Literal["vector", "hybrid"] = "vector"
    rrf_k: int = Field(default=60, ge=1)  # the constant from the RRF paper
    candidates: int = Field(default=50, ge=1)  # per list in hybrid mode, at least k


class SearchKnowledge:
    def __init__(
        self,
        *,
        search: ChunkSearch,
        embedder: Embedder,
        max_k: int = MAX_K,
        retrieval: RetrievalSettings | None = None,
    ) -> None:
        self._search = search
        self._embedder = embedder
        self._max_k = max_k
        self._retrieval = retrieval or RetrievalSettings()

    async def __call__(
        self, principal: Principal, query: str, *, k: int
    ) -> list[RetrievedEvidence]:
        text = normalize_nfc(query).strip()
        if not _HAS_WORD.search(text):
            raise InvalidQueryError("query must contain at least one word")
        if len(text) > MAX_QUERY_CHARS:
            raise InvalidQueryError(f"query is longer than {MAX_QUERY_CHARS} characters")
        if not 1 <= k <= self._max_k:
            raise InvalidQueryError(f"k must be between 1 and {self._max_k}")

        vector = await self._embedder.embed_query(text)
        if self._retrieval.mode == "hybrid":
            hits = await self._hybrid(principal, text, vector, k=k)
        else:
            hits = await self._search.search(
                principal, vector, k=k, embedding_model=self._embedder.model
            )
        ensure_accessible(principal, hits)  # ADR-0003 defense in depth
        return hits

    async def _hybrid(
        self, principal: Principal, text: str, vector: Vector, *, k: int
    ) -> list[RetrievedEvidence]:
        depth = max(k, self._retrieval.candidates)
        model = self._embedder.model
        semantic = await self._search.search(principal, vector, k=depth, embedding_model=model)
        lexical = await self._search.search_lexical(
            principal, text, vector, k=depth, embedding_model=model
        )
        by_id = {hit.chunk_id: hit for hit in (*semantic, *lexical)}
        fused = reciprocal_rank_fusion(
            [[h.chunk_id for h in semantic], [h.chunk_id for h in lexical]],
            rrf_k=self._retrieval.rrf_k,
        )
        return [by_id[chunk_id] for chunk_id, _ in fused[:k]]
