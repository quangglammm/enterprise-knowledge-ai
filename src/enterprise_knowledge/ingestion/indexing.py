"""Indexing and versioning steps shared by synchronous ingestion and the worker (JOB-01)."""

from collections.abc import Sequence

from enterprise_knowledge.domain.documents import (
    Document,
    DocumentChunk,
    DocumentStatus,
    Embedding,
)
from enterprise_knowledge.domain.errors import DocumentNotFoundError
from enterprise_knowledge.domain.ids import DocumentId, TenantId
from enterprise_knowledge.domain.ports import DocumentRepository, Embedder

EMBED_BATCH_SIZE = 32
# "Title > Section" header for embedding input; U+203A reads naturally in both languages.
HEADER_SEPARATOR = " \u203a "


def embedding_input(title: str, section: str | None, text: str) -> str:
    """Contextual header for the embedder (ADR-0006); stored chunk text stays unchanged."""
    header = f"{title}{HEADER_SEPARATOR}{section}" if section and section != title else title
    return f"{header}\n\n{text}"


def blob_key(tenant_id: TenantId, document_id: DocumentId, version: int) -> str:
    """Where a version's original upload is stored. Versions are numbered 1..N."""
    return f"{tenant_id}/{document_id}/v{version}"


async def embed_chunks(
    embedder: Embedder,
    document: Document,
    chunks: Sequence[DocumentChunk],
    *,
    embedding_header: bool = True,
) -> list[Embedding]:
    embeddings: list[Embedding] = []
    for start in range(0, len(chunks), EMBED_BATCH_SIZE):
        batch = chunks[start : start + EMBED_BATCH_SIZE]
        vectors = await embedder.embed_documents(
            [
                embedding_input(document.title, c.source.section, c.text)
                if embedding_header
                else c.text
                for c in batch
            ]
        )
        embeddings.extend(
            Embedding(
                chunk_id=chunk.id,
                model=embedder.model,
                dimension=embedder.dimension,
                vector=vector,
            )
            for chunk, vector in zip(batch, vectors, strict=True)
        )
    return embeddings


async def next_version(
    documents: DocumentRepository, tenant_id: TenantId, document_id: DocumentId | None
) -> int:
    """1 for a new document; otherwise one above the current version.

    A deleted document stays deleted (ADR-0008): a new version of it is refused."""
    if document_id is None:
        return 1
    current = await documents.get_document(tenant_id, document_id)
    if current is None or current.status is DocumentStatus.DELETED:
        raise DocumentNotFoundError(f"document {document_id} not found")
    return current.version + 1
