"""Test embedder: the dev hashing embedder plus a record of what it was asked to embed."""

from collections.abc import Sequence

from enterprise_knowledge.domain.ports import Vector
from enterprise_knowledge.infrastructure.embeddings.hashing import (
    DEFAULT_DIMENSION,
    HashingEmbedder,
)

PRODUCTION_DIMENSION = DEFAULT_DIMENSION


class HashEmbedder(HashingEmbedder):
    def __init__(self, *, dimension: int = PRODUCTION_DIMENSION, model: str = "fake-hash") -> None:
        super().__init__(dimension=dimension, model=model)
        self.calls = 0
        self.document_inputs: list[str] = []
        self.fail_with: Exception | None = None

    async def embed_documents(self, texts: Sequence[str]) -> list[Vector]:
        self.calls += 1
        if self.fail_with is not None:
            raise self.fail_with
        self.document_inputs.extend(texts)
        return await super().embed_documents(texts)

    async def embed_query(self, text: str) -> Vector:
        self.calls += 1
        return await super().embed_query(text)
