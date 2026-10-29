"""DeleteDocument use case: remove a document from search, then its stored files (ADR-0008).

The repository step comes first and is atomic, so search forgets the document even if a
file deletion fails afterwards. Deleting again is safe and retries the file deletions.
"""

import logging

from enterprise_knowledge.domain.access import Principal
from enterprise_knowledge.domain.errors import DocumentNotFoundError
from enterprise_knowledge.domain.ids import DocumentId
from enterprise_knowledge.domain.ports import BlobStore, DocumentRepository
from enterprise_knowledge.ingestion.ingest import blob_key

logger = logging.getLogger(__name__)


class DeleteDocument:
    def __init__(self, *, documents: DocumentRepository, blobs: BlobStore) -> None:
        self._documents = documents
        self._blobs = blobs

    async def __call__(self, *, principal: Principal, document_id: DocumentId) -> None:
        current = await self._documents.get_document(principal.tenant_id, document_id)
        # Anyone who can read a document may delete it; others cannot tell it exists.
        if current is None or not principal.can_access(current.access):
            raise DocumentNotFoundError(f"document {document_id} not found")

        await self._documents.delete_document(current.tenant_id, current.id)
        for version in range(1, current.version + 1):
            await self._blobs.delete(blob_key(current.tenant_id, current.id, version))

        logger.info(
            "document deleted",
            extra={"document_id": current.id, "versions": current.version},
        )
