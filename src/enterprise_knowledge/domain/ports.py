"""Ports: the only way use cases reach storage, queues and models (ADR-0002).

Adapters in ``infrastructure/`` implement these; tests use the fakes in ``tests/fakes/``.
"""

from collections.abc import Sequence
from typing import Protocol

from pydantic import BaseModel, ConfigDict

from enterprise_knowledge.domain.access import Principal
from enterprise_knowledge.domain.chat import ChatRequest, ChatResponse
from enterprise_knowledge.domain.documents import Document, DocumentChunk, Embedding
from enterprise_knowledge.domain.ids import DocumentId, JobId, TenantId
from enterprise_knowledge.domain.jobs import IngestionJob
from enterprise_knowledge.domain.retrieval import RetrievedEvidence

Vector = tuple[float, ...]


class DocumentRepository(Protocol):
    """Document metadata and chunks. Each method is atomic.

    Every write applies the serving rule (ADR-0007, ADR-0008): search serves a document's
    highest indexed version, and chunks of older versions are deleted in the same write.
    Document rows of all versions are kept as history.
    """

    async def add_document(self, document: Document) -> None:
        """Insert a new document version. Raises if (id, version) already exists."""
        ...

    async def get_document(self, tenant_id: TenantId, document_id: DocumentId) -> Document | None:
        """Return the current (highest) version, or None if absent or in another tenant."""
        ...

    async def get_document_version(
        self, tenant_id: TenantId, document_id: DocumentId, version: int
    ) -> Document | None:
        """Return one specific version, or None if absent or in another tenant."""
        ...

    async def find_by_checksum(self, tenant_id: TenantId, checksum: str) -> Document | None:
        """Return a non-deleted version with identical content in the tenant, for dedup."""
        ...

    async def update_document(self, document: Document) -> None:
        """Replace the stored state of an existing (id, version)."""
        ...

    async def replace_chunks(
        self,
        document: Document,
        chunks: Sequence[DocumentChunk],
        embeddings: Sequence[Embedding],
    ) -> None:
        """Atomically set the chunks of one document version. Idempotent: re-running with
        the same input leaves exactly one copy. Every chunk needs exactly one embedding."""
        ...

    async def list_chunks(
        self, tenant_id: TenantId, document_id: DocumentId, version: int
    ) -> list[DocumentChunk]:
        """Chunks of one version, ordered by chunk index."""
        ...

    async def delete_document(self, tenant_id: TenantId, document_id: DocumentId) -> None:
        """Mark every version deleted and remove all their chunks. Idempotent.

        ``get_document`` still returns the deleted version, so callers can tell deleted
        from absent; nothing else about a deleted document is served."""
        ...


class ChunkSearch(Protocol):
    async def search(
        self,
        principal: Principal,
        query_vector: Vector,
        *,
        k: int,
        embedding_model: str,
    ) -> list[RetrievedEvidence]:
        """Top-k chunks by similarity, best first.

        Must apply, inside the query and before ranking (ADR-0003):
        - the principal's tenant and groups,
        - only the current version of indexed documents,
        - only embeddings produced by ``embedding_model``.
        May return fewer than k results.
        """
        ...

    async def search_lexical(
        self,
        principal: Principal,
        query_text: str,
        query_vector: Vector,
        *,
        k: int,
        embedding_model: str,
    ) -> list[RetrievedEvidence]:
        """Top-k chunks by full-text relevance to ``query_text``, best first (ADR-0014).

        Same filters as ``search``, inside the query. Relevance is the sum of BM25-style
        IDF over the query terms a chunk's title, section or text contains, with document
        frequencies counted over the chunks the principal can see; ties by chunk ID. Chunks
        matching no term are not returned. ``score`` is still the cosine similarity to
        ``query_vector``, so every search mode reports evidence on one scale.
        """
        ...


class Embedder(Protocol):
    @property
    def model(self) -> str: ...

    @property
    def dimension(self) -> int: ...

    async def embed_documents(self, texts: Sequence[str]) -> list[Vector]: ...

    async def embed_query(self, text: str) -> Vector: ...


class ChatModel(Protocol):
    @property
    def model_id(self) -> str: ...

    async def complete(self, request: ChatRequest) -> ChatResponse: ...


class QueueMessage(BaseModel):
    model_config = ConfigDict(frozen=True)

    job_id: JobId
    receipt: str
    delivery_count: int


class JobQueue(Protocol):
    """At-least-once delivery: consumers must be idempotent (JOB-01, ADR-0016).

    A received message is leased for the queue's visibility timeout; unless acked in that
    time it is delivered again with a higher ``delivery_count``. Concurrent consumers never
    hold the same message at once.
    """

    async def enqueue(self, job_id: JobId, *, delay_seconds: float = 0.0) -> None:
        """Make a message for ``job_id`` receivable after ``delay_seconds``."""
        ...

    async def receive(self, *, max_messages: int, wait_seconds: float) -> list[QueueMessage]:
        """Lease up to ``max_messages`` ready messages, waiting up to ``wait_seconds``."""
        ...

    async def ack(self, message: QueueMessage) -> None:
        """Remove a leased message. Acking a message whose lease expired is a no-op."""
        ...


class JobRepository(Protocol):
    """Ingestion job state (JOB-01). Jobs are looked up by ID; callers check the tenant."""

    async def add_job(self, job: IngestionJob) -> None:
        """Insert a new job. Raises if the ID exists."""
        ...

    async def get_job(self, job_id: JobId) -> IngestionJob | None: ...

    async def update_job(self, job: IngestionJob) -> None:
        """Replace the stored state of an existing job."""
        ...

    async def latest_job_for(
        self, tenant_id: TenantId, document_id: DocumentId, version: int
    ) -> IngestionJob | None:
        """The most recently created job for one document version."""
        ...


class BlobStore(Protocol):
    """Original uploaded files (S3 in AWS, local filesystem or memory otherwise)."""

    async def put(self, key: str, data: bytes, *, content_type: str) -> None: ...

    async def get(self, key: str) -> bytes: ...

    async def delete(self, key: str) -> None: ...
