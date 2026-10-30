"""IngestDocument use case: upload bytes to an indexed, searchable document version.

Synchronous within a request for the v0.1 slice. Week 5 moves the same steps behind a job
queue (JOB-01) without changing this logic.
"""

import asyncio
import logging
from collections.abc import Callable
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict

from enterprise_knowledge.domain.access import AccessPolicy
from enterprise_knowledge.domain.documents import (
    ContentType,
    Document,
    DocumentStatus,
)
from enterprise_knowledge.domain.ids import DocumentId, new_document_id
from enterprise_knowledge.domain.ports import BlobStore, DocumentRepository, Embedder
from enterprise_knowledge.ingestion.chunking import ChunkingSettings, build_chunks
from enterprise_knowledge.ingestion.indexing import blob_key, embed_chunks, next_version
from enterprise_knowledge.ingestion.limits import IngestionLimits
from enterprise_knowledge.ingestion.prepare import PreparedDocument, prepare_document

logger = logging.getLogger(__name__)

_UNCATEGORIZED_FAILURE = "indexing_error"


class IngestResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    document: Document
    chunk_count: int
    duplicate: bool


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
            embeddings = await embed_chunks(
                self._embedder, document, chunks, embedding_header=self._embedding_header
            )
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
        version = await next_version(self._documents, access.tenant_id, document_id)
        document_id = document_id or self._new_id()

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
