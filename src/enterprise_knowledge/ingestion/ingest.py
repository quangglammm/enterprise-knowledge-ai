"""IngestDocument use case: upload bytes to an indexed, searchable document version.

Synchronous within a request for the v0.1 slice. Week 5 moves the same steps behind a job
queue (JOB-01) without changing this logic.
"""

import asyncio
import logging
from collections.abc import Callable, Sequence
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict

from enterprise_knowledge.domain.access import AccessPolicy
from enterprise_knowledge.domain.documents import (
    ContentType,
    Document,
    DocumentChunk,
    DocumentStatus,
    Embedding,
)
from enterprise_knowledge.domain.errors import DocumentNotFoundError
from enterprise_knowledge.domain.ids import DocumentId, TenantId, new_document_id
from enterprise_knowledge.domain.ports import BlobStore, DocumentRepository, Embedder
from enterprise_knowledge.ingestion.chunking import ChunkingSettings, build_chunks
from enterprise_knowledge.ingestion.limits import IngestionLimits
from enterprise_knowledge.ingestion.prepare import PreparedDocument, prepare_document

logger = logging.getLogger(__name__)

EMBED_BATCH_SIZE = 32
# "Title > Section" header for embedding input; U+203A reads naturally in both languages.
HEADER_SEPARATOR = " \u203a "
_UNCATEGORIZED_FAILURE = "indexing_error"


class IngestResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    document: Document
    chunk_count: int
    duplicate: bool


def embedding_input(title: str, section: str | None, text: str) -> str:
    """Contextual header for the embedder (ADR-0006); stored chunk text stays unchanged."""
    header = f"{title}{HEADER_SEPARATOR}{section}" if section and section != title else title
    return f"{header}\n\n{text}"


def blob_key(tenant_id: TenantId, document_id: DocumentId, version: int) -> str:
    """Where a version's original upload is stored. Versions are numbered 1..N."""
    return f"{tenant_id}/{document_id}/v{version}"


class IngestDocument:
    def __init__(
        self,
        *,
        documents: DocumentRepository,
        embedder: Embedder,
        blobs: BlobStore,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        new_document_id: Callable[[], DocumentId] = new_document_id,
        limits: IngestionLimits | None = None,
        chunking: ChunkingSettings | None = None,
        embedding_header: bool = True,
    ) -> None:
        self._documents = documents
        self._embedder = embedder
        self._blobs = blobs
        self._clock = clock
        self._new_id = new_document_id
        self._limits = limits or IngestionLimits()
        self._chunking = chunking or ChunkingSettings()
        # Off only for the Week 4 experiment that measures the header (ADR-0006, ADR-0013).
        self._embedding_header = embedding_header

    async def __call__(
        self,
        *,
        data: bytes,
        filename: str,
        access: AccessPolicy,
        declared: ContentType | None = None,
        document_id: DocumentId | None = None,
        title: str | None = None,
    ) -> IngestResult:
        # Parsing is CPU-bound; keep it off the event loop. Typed errors propagate and
        # nothing has been stored yet.
        prepared = await asyncio.to_thread(
            prepare_document,
            data,
            filename=filename,
            declared=declared,
            limits=self._limits,
            chunking=self._chunking,
        )

        existing = await self._documents.find_by_checksum(access.tenant_id, prepared.checksum)
        if existing is not None and document_id in (None, existing.id):
            if existing.status is DocumentStatus.INDEXED and existing.access == access:
                chunks = await self._documents.list_chunks(
                    existing.tenant_id, existing.id, existing.version
                )
                return IngestResult(document=existing, chunk_count=len(chunks), duplicate=True)
            # Same bytes but a new policy, or a previous attempt that failed: new version.
            document_id = existing.id

        document = await self._create_version(prepared, access, filename, document_id, title)
        try:
            chunks = build_chunks(document, prepared.chunks)
            await self._blobs.put(
                blob_key(document.tenant_id, document.id, document.version),
                data,
                content_type=document.content_type,
            )
            embeddings = await self._embed(document, chunks)
            await self._documents.replace_chunks(document, chunks, embeddings)
            indexed = document.with_status(DocumentStatus.INDEXED, now=self._clock())
            await self._documents.update_document(indexed)
        except Exception as exc:
            # Record the failure on this version, then let the caller see the original error.
            category = str(getattr(exc, "category", _UNCATEGORIZED_FAILURE))
            failed = document.with_status(
                DocumentStatus.FAILED, now=self._clock(), error_category=category
            )
            await self._documents.update_document(failed)
            logger.warning(
                "document indexing failed",
                extra={
                    "document_id": document.id,
                    "version": document.version,
                    "error_category": category,
                },
            )
            raise

        logger.info(
            "document indexed",
            extra={
                "document_id": indexed.id,
                "version": indexed.version,
                "chunks": len(chunks),
                "language": indexed.language.value,
            },
        )
        return IngestResult(document=indexed, chunk_count=len(chunks), duplicate=False)

    async def _create_version(
        self,
        prepared: PreparedDocument,
        access: AccessPolicy,
        filename: str,
        document_id: DocumentId | None,
        title: str | None,
    ) -> Document:
        version = 1
        if document_id is None:
            document_id = self._new_id()
        else:
            current = await self._documents.get_document(access.tenant_id, document_id)
            # A deleted document stays deleted (ADR-0008); re-upload creates a new one.
            if current is None or current.status is DocumentStatus.DELETED:
                raise DocumentNotFoundError(f"document {document_id} not found")
            version = current.version + 1

        now = self._clock()
        document = Document(
            id=document_id,
            title=title or prepared.title,
            filename=filename,
            content_type=prepared.content_type,
            checksum=prepared.checksum,
            version=version,
            status=DocumentStatus.PENDING,
            access=access,
            language=prepared.language,
            created_at=now,
            updated_at=now,
        )
        await self._documents.add_document(document)
        return document

    async def _embed(self, document: Document, chunks: Sequence[DocumentChunk]) -> list[Embedding]:
        embeddings: list[Embedding] = []
        for start in range(0, len(chunks), EMBED_BATCH_SIZE):
            batch = chunks[start : start + EMBED_BATCH_SIZE]
            vectors = await self._embedder.embed_documents(
                [
                    embedding_input(document.title, c.source.section, c.text)
                    if self._embedding_header
                    else c.text
                    for c in batch
                ]
            )
            embeddings.extend(
                Embedding(
                    chunk_id=chunk.id,
                    model=self._embedder.model,
                    dimension=self._embedder.dimension,
                    vector=vector,
                )
                for chunk, vector in zip(batch, vectors, strict=True)
            )
        return embeddings
