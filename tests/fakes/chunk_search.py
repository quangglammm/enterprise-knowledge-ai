"""ChunkSearch with scripted rankings, for testing fusion without a corpus."""

from collections.abc import Sequence

from enterprise_knowledge.domain.access import Principal
from enterprise_knowledge.domain.ports import Vector
from enterprise_knowledge.domain.retrieval import RetrievedEvidence


class ScriptedChunkSearch:
    """Returns the given rankings (cut to k) and records how it was called."""

    def __init__(
        self,
        *,
        vector: Sequence[RetrievedEvidence] = (),
        lexical: Sequence[RetrievedEvidence] = (),
    ) -> None:
        self._vector = list(vector)
        self._lexical = list(lexical)
        self.vector_calls: list[int] = []  # k of each call
        self.lexical_calls: list[tuple[str, int]] = []  # (query text, k)

    async def search(
        self, principal: Principal, query_vector: Vector, *, k: int, embedding_model: str
    ) -> list[RetrievedEvidence]:
        self.vector_calls.append(k)
        return self._vector[:k]

    async def search_lexical(
        self,
        principal: Principal,
        query_text: str,
        query_vector: Vector,
        *,
        k: int,
        embedding_model: str,
    ) -> list[RetrievedEvidence]:
        self.lexical_calls.append((query_text, k))
        return self._lexical[:k]
