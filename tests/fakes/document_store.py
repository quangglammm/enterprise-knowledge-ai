"""In-memory DocumentRepository + ChunkSearch with the same semantics as the Postgres adapter.

The search applies access, version and model filters *before* ranking, mirroring the SQL
WHERE clause (ADR-0003). Contract tests in tests/contract run against this and Postgres.
Lexical search approximates Postgres's ``simple`` text-search parser: lowercase words, with
dotted tokens such as ``gov.uk`` or ``1.500.000`` kept whole (ADR-0014).
"""

import math
import re
from collections.abc import Iterator, Sequence

from enterprise_knowledge.domain.access import Principal
from enterprise_knowledge.domain.documents import (
    Document,
    DocumentChunk,
    DocumentStatus,
    Embedding,
    serving_version,
    validate_chunk_set,
)
from enterprise_knowledge.domain.errors import DocumentAlreadyExistsError, DocumentNotFoundError
from enterprise_knowledge.domain.ids import ChunkId, DocumentId, TenantId
from enterprise_knowledge.domain.ports import Vector
from enterprise_knowledge.domain.retrieval import RetrievedEvidence

_Key = tuple[TenantId, DocumentId, int]
_TOKEN = re.compile(r"\w+(?:\.\w+)*")


class InMemoryDocumentStore:
    def __init__(self) -> None:
        self._documents: dict[_Key, Document] = {}
        self._chunks: dict[_Key, list[DocumentChunk]] = {}
        self._embeddings: dict[ChunkId, Embedding] = {}

    # --- DocumentRepository -------------------------------------------------------------

    async def add_document(self, document: Document) -> None:
        key = _key(document)
        if key in self._documents:
            raise DocumentAlreadyExistsError(f"{document.id} v{document.version} exists")
        self._documents[key] = document

    async def get_document(self, tenant_id: TenantId, document_id: DocumentId) -> Document | None:
        versions = [
            d for (t, i, _), d in self._documents.items() if t == tenant_id and i == document_id
        ]
        return max(versions, key=lambda d: d.version, default=None)

    async def find_by_checksum(self, tenant_id: TenantId, checksum: str) -> Document | None:
        matches = [
            d
            for d in self._documents.values()
            if d.tenant_id == tenant_id
            and d.checksum == checksum
            and d.status is not DocumentStatus.DELETED
        ]
        return max(matches, key=lambda d: (d.id, d.version), default=None)

    async def update_document(self, document: Document) -> None:
        key = _key(document)
        if key not in self._documents:
            raise DocumentNotFoundError(f"{document.id} v{document.version} not found")
        self._documents[key] = document
        # ADR-0003: a policy change propagates to the version's chunks atomically.
        self._chunks[key] = [
            DocumentChunk.model_validate(c.model_dump() | {"access": document.access})
            for c in self._chunks.get(key, [])
        ]
        self._prune_superseded(document.tenant_id, document.id)

    async def replace_chunks(
        self,
        document: Document,
        chunks: Sequence[DocumentChunk],
        embeddings: Sequence[Embedding],
    ) -> None:
        key = _key(document)
        if key not in self._documents:
            raise DocumentNotFoundError(f"{document.id} v{document.version} not found")
        validate_chunk_set(document, chunks, embeddings)

        for old in self._chunks.get(key, []):
            self._embeddings.pop(old.id, None)
        self._chunks[key] = sorted(chunks, key=lambda c: c.chunk_index)
        self._embeddings.update({e.chunk_id: e for e in embeddings})
        self._prune_superseded(document.tenant_id, document.id)

    async def list_chunks(
        self, tenant_id: TenantId, document_id: DocumentId, version: int
    ) -> list[DocumentChunk]:
        return list(self._chunks.get((tenant_id, document_id, version), []))

    async def delete_document(self, tenant_id: TenantId, document_id: DocumentId) -> None:
        for key, document in list(self._documents.items()):
            if key[0] == tenant_id and key[1] == document_id:
                self._documents[key] = document.model_validate(
                    document.model_dump() | {"status": DocumentStatus.DELETED}
                )
                for chunk in self._chunks.pop(key, []):
                    self._embeddings.pop(chunk.id, None)

    # --- ChunkSearch --------------------------------------------------------------------

    async def search(
        self,
        principal: Principal,
        query_vector: Vector,
        *,
        k: int,
        embedding_model: str,
    ) -> list[RetrievedEvidence]:
        if k < 1:
            raise ValueError("k must be at least 1")

        scored = [
            (_cosine(query_vector, self._embeddings[chunk.id].vector), chunk, document)
            for chunk, document in self._visible(principal, embedding_model)
        ]
        scored.sort(key=lambda item: (-item[0], item[1].id))
        return [_evidence(score, chunk, document) for score, chunk, document in scored[:k]]

    async def search_lexical(
        self,
        principal: Principal,
        query_text: str,
        query_vector: Vector,
        *,
        k: int,
        embedding_model: str,
    ) -> list[RetrievedEvidence]:
        if k < 1:
            raise ValueError("k must be at least 1")

        visible = [
            (chunk, document, _terms(document.title, chunk.source.section or "", chunk.text))
            for chunk, document in self._visible(principal, embedding_model)
        ]
        query = _terms(query_text)
        df = {t: sum(1 for _, _, terms in visible if t in terms) for t in query}
        n = len(visible)
        idf = {t: math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5)) for t in query if df[t]}
        ranked = sorted(
            (
                (sum(idf[t] for t in idf if t in terms), chunk, document)
                for chunk, document, terms in visible
                if terms & idf.keys()
            ),
            key=lambda item: (-item[0], item[1].id),
        )
        return [
            _evidence(_cosine(query_vector, self._embeddings[chunk.id].vector), chunk, document)
            for _, chunk, document in ranked[:k]
        ]

    def _visible(
        self, principal: Principal, embedding_model: str
    ) -> Iterator[tuple[DocumentChunk, Document]]:
        """Chunks search may rank: served version, readable, embedded by the model."""
        for key, chunks in self._chunks.items():
            document = self._documents[key]
            if document.version != self._serving_version(document.tenant_id, document.id):
                continue
            for chunk in chunks:
                if not principal.can_access(chunk.access):  # filter before ranking
                    continue
                if self._embeddings[chunk.id].model != embedding_model:
                    continue
                yield chunk, document

    def _serving_version(self, tenant_id: TenantId, document_id: DocumentId) -> int | None:
        return serving_version(
            d for (t, i, _), d in self._documents.items() if t == tenant_id and i == document_id
        )

    def _prune_superseded(self, tenant_id: TenantId, document_id: DocumentId) -> None:
        """Drop chunks of versions older than the serving one (ADR-0008)."""
        serving = self._serving_version(tenant_id, document_id)
        if serving is None:
            return
        for key in list(self._chunks):
            if key[0] == tenant_id and key[1] == document_id and key[2] < serving:
                for chunk in self._chunks.pop(key):
                    self._embeddings.pop(chunk.id, None)


def _key(document: Document) -> _Key:
    return (document.tenant_id, document.id, document.version)


def _terms(*texts: str) -> set[str]:
    return {t for text in texts for t in _TOKEN.findall(text.lower())}


def _cosine(a: Vector, b: Vector) -> float:
    if len(a) != len(b):
        raise ValueError(f"vector dimensions differ: {len(a)} != {len(b)}")
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return 0.0 if norm == 0 else sum(x * y for x, y in zip(a, b, strict=True)) / norm


def _evidence(score: float, chunk: DocumentChunk, document: Document) -> RetrievedEvidence:
    return RetrievedEvidence(
        chunk_id=chunk.id,
        document_id=chunk.document_id,
        document_version=chunk.document_version,
        title=document.title,
        text=chunk.text,
        score=score,
        source=chunk.source,
        access=chunk.access,
        language=chunk.language,
    )
