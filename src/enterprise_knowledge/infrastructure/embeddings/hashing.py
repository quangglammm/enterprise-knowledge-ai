"""Deterministic hashed bag-of-words embedder. Development and tests only.

Texts sharing words get similar vectors, so the system can be exercised end to end without a
model provider. It has no semantic understanding: never use it for evaluation results. The
real embedder is FptEmbedder (ADR-0010), selected with EKA_EMBEDDING_PROVIDER=fpt.
"""

import hashlib
import math
import re
from collections.abc import Sequence

from enterprise_knowledge.domain.ports import Vector
from enterprise_knowledge.domain.text import normalize_nfc

DEFAULT_DIMENSION = 1024
_TOKEN = re.compile(r"\w+", re.UNICODE)


class HashingEmbedder:
    def __init__(self, *, dimension: int = DEFAULT_DIMENSION, model: str = "hashing-v1") -> None:
        self._dimension = dimension
        self._model = model

    @property
    def model(self) -> str:
        return self._model

    @property
    def dimension(self) -> int:
        return self._dimension

    async def embed_documents(self, texts: Sequence[str]) -> list[Vector]:
        return [self.embed(t) for t in texts]

    async def embed_query(self, text: str) -> Vector:
        return self.embed(text)

    def embed(self, text: str) -> Vector:
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
