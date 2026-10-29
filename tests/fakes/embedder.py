"""Deterministic embedder for tests: hashed bag of words, L2-normalized.

Texts sharing words get similar vectors, so retrieval tests are meaningful without a model.
Dimension defaults to the production dimension (ADR-0004) so schemas stay identical.
"""

import hashlib
import math
import re
from collections.abc import Sequence

from enterprise_knowledge.domain.ports import Vector
from enterprise_knowledge.domain.text import normalize_nfc

PRODUCTION_DIMENSION = 1024
_TOKEN = re.compile(r"\w+", re.UNICODE)


class HashEmbedder:
    def __init__(self, *, dimension: int = PRODUCTION_DIMENSION, model: str = "fake-hash") -> None:
        self._dimension = dimension
        self._model = model
        self.calls = 0

    @property
    def model(self) -> str:
        return self._model

    @property
    def dimension(self) -> int:
        return self._dimension

    async def embed_documents(self, texts: Sequence[str]) -> list[Vector]:
        self.calls += 1
        return [self._embed(t) for t in texts]

    async def embed_query(self, text: str) -> Vector:
        self.calls += 1
        return self._embed(text)

    def _embed(self, text: str) -> Vector:
        tokens = _TOKEN.findall(normalize_nfc(text).casefold())
        if not tokens:
            raise ValueError("cannot embed text without word characters")
        vector = [0.0] * self._dimension
        for token in tokens:
            digest = hashlib.blake2b(token.encode(), digest_size=8).digest()
            index = int.from_bytes(digest[:4], "big") % self._dimension
            vector[index] += 1.0 if digest[4] & 1 else -1.0
        norm = math.sqrt(sum(v * v for v in vector)) or 1.0
        return tuple(v / norm for v in vector)
