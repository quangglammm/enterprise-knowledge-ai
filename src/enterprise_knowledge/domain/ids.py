"""Typed identifiers, so a chunk ID cannot be passed where a document ID is expected."""

import uuid
from typing import NewType

TenantId = NewType("TenantId", str)
UserId = NewType("UserId", str)
GroupId = NewType("GroupId", str)
DocumentId = NewType("DocumentId", str)
ChunkId = NewType("ChunkId", str)
JobId = NewType("JobId", str)

# Fixed namespace: changing it changes every chunk ID and forces a full re-index.
_CHUNK_NAMESPACE = uuid.UUID("6f1c3a52-2d4e-4b8a-9a57-3e0c1f7b9d21")


def new_document_id() -> DocumentId:
    return DocumentId(uuid.uuid4().hex)


def new_job_id() -> JobId:
    return JobId(uuid.uuid4().hex)


def chunk_id_for(document_id: DocumentId, version: int, index: int) -> ChunkId:
    """Deterministic chunk ID: reprocessing unchanged input yields identical IDs (ING-02)."""
    return ChunkId(uuid.uuid5(_CHUNK_NAMESPACE, f"{document_id}:{version}:{index}").hex)
