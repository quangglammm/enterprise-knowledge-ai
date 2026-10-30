"""Asynchronous ingestion (JOB-01, ADR-0016): submit in the API, process in the worker.

``SubmitDocument`` does only what is cheap and must be synchronous: the size limit, format
sniffing and checksum deduplication. It then stores the original, creates a pending version
and a job, and enqueues it. ``ProcessIngestionJob`` parses, chunks, embeds and indexes.

Delivery is at least once, so processing is idempotent: a finished job is skipped, a job
found RUNNING (its worker stopped mid-attempt) counts that attempt as interrupted, and
re-indexing a version replaces its chunks (ING-03). Transient failures (a retryable
provider error, an unexpected error) requeue until ``max_attempts``; anything else fails
the job and the version with a stable category. Logs carry IDs and categories only.
"""

import asyncio
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import PurePosixPath

from pydantic import BaseModel, ConfigDict

from enterprise_knowledge.domain.access import AccessPolicy
from enterprise_knowledge.domain.documents import (
    ContentType,
    Document,
    DocumentStatus,
    Language,
)
from enterprise_knowledge.domain.errors import (
    BlobNotFoundError,
    DomainError,
    ModelProviderError,
)
from enterprise_knowledge.domain.ids import DocumentId, JobId, new_document_id, new_job_id
from enterprise_knowledge.domain.jobs import IngestionJob, JobStatus
from enterprise_knowledge.domain.ports import (
    BlobStore,
    DocumentRepository,
    Embedder,
    JobQueue,
    JobRepository,
)
from enterprise_knowledge.ingestion.chunking import ChunkingSettings, build_chunks
from enterprise_knowledge.ingestion.detect import detect_content_type
from enterprise_knowledge.ingestion.errors import IngestionError
from enterprise_knowledge.ingestion.indexing import blob_key, embed_chunks, next_version
from enterprise_knowledge.ingestion.limits import IngestionLimits
from enterprise_knowledge.ingestion.normalize import normalize_text
from enterprise_knowledge.ingestion.prepare import prepare_document, sha256_hex

logger = logging.getLogger(__name__)

DEFAULT_MAX_ATTEMPTS = 3
INTERRUPTED = "worker_interrupted"
DOCUMENT_DELETED = "document_deleted"
ENQUEUE_FAILED = "enqueue_failed"
UNEXPECTED = "indexing_error"


class SubmitResult(BaseModel):
    """``job`` is None only for a duplicate of an already indexed version."""

    model_config = ConfigDict(frozen=True)

    document: Document
    job: IngestionJob | None
    duplicate: bool


class SubmitDocument:
    def __init__(
        self,
        *,
        documents: DocumentRepository,
        jobs: JobRepository,
        queue: JobQueue,
        blobs: BlobStore,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        limits: IngestionLimits | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        new_document_id: Callable[[], DocumentId] = new_document_id,
        new_job_id: Callable[[], JobId] = new_job_id,
    ) -> None:
        self._documents = documents
        self._jobs = jobs
        self._queue = queue
        self._blobs = blobs
        self._max_attempts = max_attempts
        self._limits = limits or IngestionLimits()
        self._clock = clock
        self._new_document_id = new_document_id
        self._new_job_id = new_job_id

    async def __call__(
        self,
        *,
        data: bytes,
        filename: str,
        access: AccessPolicy,
        declared: ContentType | None = None,
        document_id: DocumentId | None = None,
        title: str | None = None,
    ) -> SubmitResult:
        # Typed errors (empty, too large, unsupported) propagate before anything is stored.
        content_type = detect_content_type(
            data, filename=filename, declared=declared, limits=self._limits
        )
        checksum = sha256_hex(data)

        existing = await self._documents.find_by_checksum(access.tenant_id, checksum)
        if existing is not None and document_id in (None, existing.id):
            duplicate = await self._duplicate_of(existing, access)
            if duplicate is not None:
                return duplicate
            # Same bytes with a new policy, or an earlier failed attempt: a new version.
            document_id = existing.id

        now = self._clock()
        document = Document(
            id=document_id or self._new_document_id(),
            title=title or normalize_text(PurePosixPath(filename).stem) or "untitled",
            filename=filename,
            content_type=content_type,
            checksum=checksum,
            version=await next_version(self._documents, access.tenant_id, document_id),
            status=DocumentStatus.PENDING,
            access=access,
            language=Language.UNKNOWN,  # set by the worker once parsed
            created_at=now,
            updated_at=now,
        )
        await self._documents.add_document(document)
        await self._blobs.put(
            blob_key(document.tenant_id, document.id, document.version),
            data,
            content_type=document.content_type,
        )
        job = IngestionJob.new(
            job_id=self._new_job_id(),
            tenant_id=document.tenant_id,
            document_id=document.id,
            document_version=document.version,
            max_attempts=self._max_attempts,
            now=now,
            use_parsed_title=title is None,
        )
        await self._jobs.add_job(job)
        try:
            await self._queue.enqueue(job.id)
        except Exception:
            # Nothing will ever deliver this job: record why, then let the caller fail.
            await self._jobs.update_job(
                job.abandon(now=self._clock(), error_category=ENQUEUE_FAILED)
            )
            await self._documents.update_document(
                document.with_status(
                    DocumentStatus.FAILED, now=self._clock(), error_category=ENQUEUE_FAILED
                )
            )
            raise
        logger.info(
            "ingestion job submitted",
            extra={"job_id": job.id, "document_id": document.id, "version": document.version},
        )
        return SubmitResult(document=document, job=job, duplicate=False)

    async def _duplicate_of(self, existing: Document, access: AccessPolicy) -> SubmitResult | None:
        if existing.access != access:
            return None
        if existing.status is DocumentStatus.INDEXED:
            return SubmitResult(document=existing, job=None, duplicate=True)
        if existing.status is DocumentStatus.PENDING:
            job = await self._jobs.latest_job_for(existing.tenant_id, existing.id, existing.version)
            if job is not None and not job.is_terminal:
                return SubmitResult(document=existing, job=job, duplicate=True)
        return None


class ProcessIngestionJob:
    def __init__(
        self,
        *,
        documents: DocumentRepository,
        jobs: JobRepository,
        blobs: BlobStore,
        embedder: Embedder,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        limits: IngestionLimits | None = None,
        chunking: ChunkingSettings | None = None,
        embedding_header: bool = True,
    ) -> None:
        self._documents = documents
        self._jobs = jobs
        self._blobs = blobs
        self._embedder = embedder
        self._clock = clock
        self._limits = limits or IngestionLimits()
        self._chunking = chunking or ChunkingSettings()
        self._embedding_header = embedding_header

    async def __call__(self, job_id: JobId) -> IngestionJob | None:
        """The job after this delivery; QUEUED means the caller should requeue it."""
        job = await self._jobs.get_job(job_id)
        if job is None:
            logger.warning("ingestion job not found", extra={"job_id": job_id})
            return None
        if job.is_terminal:
            return job  # a duplicate delivery of finished work
        if job.status is JobStatus.RUNNING:
            job = job.fail(now=self._clock(), error_category=INTERRUPTED, retryable=True)
            await self._jobs.update_job(job)
            if job.status is JobStatus.FAILED:
                await self._fail_document(job)
                return job

        job = job.start(now=self._clock())
        await self._jobs.update_job(job)
        try:
            chunk_count = await self._index(job)
        except Exception as exc:  # noqa: BLE001 - job boundary: every failure is recorded
            return await self._record_failure(job, exc)

        job = job.succeed(now=self._clock())
        await self._jobs.update_job(job)
        logger.info(
            "ingestion job succeeded",
            extra={"job_id": job.id, "attempts": job.attempts, "chunks": chunk_count},
        )
        return job

    async def _index(self, job: IngestionJob) -> int:
        document = await self._documents.get_document_version(
            job.tenant_id, job.document_id, job.document_version
        )
        if document is None or document.status is DocumentStatus.DELETED:
            raise _DocumentGoneError(f"{job.document_id} v{job.document_version} is gone")
        try:
            data = await self._blobs.get(
                blob_key(job.tenant_id, job.document_id, job.document_version)
            )
        except BlobNotFoundError as exc:
            raise _DocumentGoneError(f"original of {job.document_id} is gone") from exc

        prepared = await asyncio.to_thread(
            prepare_document,
            data,
            filename=document.filename,
            declared=document.content_type,
            limits=self._limits,
            chunking=self._chunking,
        )
        document = document.model_validate(
            document.model_dump()
            | {
                "title": prepared.title if job.use_parsed_title else document.title,
                "language": prepared.language,
            }
        )
        chunks = build_chunks(document, prepared.chunks)
        embeddings = await embed_chunks(
            self._embedder, document, chunks, embedding_header=self._embedding_header
        )
        await self._documents.replace_chunks(document, chunks, embeddings)
        await self._documents.update_document(
            document.with_status(DocumentStatus.INDEXED, now=self._clock())
        )
        return len(chunks)

    async def _record_failure(self, job: IngestionJob, exc: Exception) -> IngestionJob:
        category, retryable = _classify(exc)
        job = job.fail(now=self._clock(), error_category=category, retryable=retryable)
        await self._jobs.update_job(job)
        extra = {"job_id": job.id, "attempts": job.attempts, "error_category": category}
        if job.status is JobStatus.FAILED:
            await self._fail_document(job)
            logger.warning("ingestion job failed", extra=extra)
        elif category == UNEXPECTED:
            logger.exception("ingestion attempt failed; will retry", extra=extra)
        else:
            logger.warning("ingestion attempt failed; will retry", extra=extra)
        return job

    async def _fail_document(self, job: IngestionJob) -> None:
        document = await self._documents.get_document_version(
            job.tenant_id, job.document_id, job.document_version
        )
        if document is None or document.status is DocumentStatus.DELETED:
            return
        await self._documents.update_document(
            document.with_status(
                DocumentStatus.FAILED,
                now=self._clock(),
                error_category=job.error_category or UNEXPECTED,
            )
        )


class _DocumentGoneError(DomainError):
    """The version was deleted, or its original removed, before the worker got to it."""

    category = DOCUMENT_DELETED


def _classify(exc: Exception) -> tuple[str, bool]:
    """(category, retryable). Unknown errors are assumed transient, within max_attempts."""
    if isinstance(exc, ModelProviderError):
        return exc.category, exc.retryable
    if isinstance(exc, IngestionError | _DocumentGoneError):
        return exc.category, False
    if isinstance(exc, DomainError):
        return exc.category, False
    return UNEXPECTED, True
