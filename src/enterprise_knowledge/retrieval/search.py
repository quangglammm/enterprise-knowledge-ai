"""SearchKnowledge use case: query text to ranked, access-checked evidence."""

import re

from enterprise_knowledge.domain.access import Principal, ensure_accessible
from enterprise_knowledge.domain.ports import ChunkSearch, Embedder
from enterprise_knowledge.domain.retrieval import RetrievedEvidence
from enterprise_knowledge.domain.text import normalize_nfc
from enterprise_knowledge.retrieval.errors import InvalidQueryError

MAX_QUERY_CHARS = 2000
MAX_K = 20
_HAS_WORD = re.compile(r"\w", re.UNICODE)


class SearchKnowledge:
    def __init__(self, *, search: ChunkSearch, embedder: Embedder, max_k: int = MAX_K) -> None:
        self._search = search
        self._embedder = embedder
        self._max_k = max_k

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
        hits = await self._search.search(
            principal, vector, k=k, embedding_model=self._embedder.model
        )
        ensure_accessible(principal, hits)  # ADR-0003 defense in depth
        return hits
