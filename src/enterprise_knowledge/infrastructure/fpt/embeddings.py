"""Embedder over FPT's OpenAI-style /embeddings (ADR-0004, ADR-0010).

Every vector is checked against the index dimension before it can reach the database, so
a model swap or a provider change fails loudly instead of corrupting the index.
"""

import math
from collections.abc import Sequence
from typing import Any

from enterprise_knowledge.domain.errors import ModelResponseError
from enterprise_knowledge.domain.ports import Vector
from enterprise_knowledge.infrastructure.fpt.client import FptClient

_PATH = "/embeddings"


class FptEmbedder:
    def __init__(self, client: FptClient, *, model: str, dimension: int) -> None:
        self._client = client
        self._model = model
        self._dimension = dimension

    @property
    def model(self) -> str:
        return self._model

    @property
    def dimension(self) -> int:
        return self._dimension

    async def embed_documents(self, texts: Sequence[str]) -> list[Vector]:
        if not texts:
            return []
        body = await self._client.post_json(_PATH, {"model": self._model, "input": list(texts)})
        return self._vectors(body, expected=len(texts))

    async def embed_query(self, text: str) -> Vector:
        [vector] = await self.embed_documents([text])
        return vector

    def _vectors(self, body: dict[str, Any], *, expected: int) -> list[Vector]:
        data = body.get("data")
        if not isinstance(data, list) or len(data) != expected:
            raise ModelResponseError(f"expected {expected} embeddings")
        by_index: dict[int, Vector] = {}
        for position, item in enumerate(data):
            if not isinstance(item, dict):
                raise ModelResponseError("embedding item is not an object")
            index = item.get("index", position)
            if not isinstance(index, int) or not 0 <= index < expected or index in by_index:
                raise ModelResponseError("embedding indexes do not match the inputs")
            by_index[index] = self._vector(item.get("embedding"))
        return [by_index[i] for i in range(expected)]

    def _vector(self, raw: object) -> Vector:
        if not isinstance(raw, list) or len(raw) != self._dimension:
            raise ModelResponseError(f"embedding is not a list of {self._dimension} numbers")
        if not all(isinstance(v, int | float) and not isinstance(v, bool) for v in raw):
            raise ModelResponseError("embedding contains non-numeric values")
        vector = tuple(float(v) for v in raw)
        if not all(math.isfinite(v) for v in vector):
            raise ModelResponseError("embedding contains non-finite values")
        return vector
