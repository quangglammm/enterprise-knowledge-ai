"""Domain error hierarchy. Each error has a stable ``category`` used in logs, jobs and metrics."""

from collections.abc import Iterable
from typing import ClassVar

from enterprise_knowledge.domain.ids import ChunkId


class DomainError(Exception):
    category: ClassVar[str] = "domain_error"


class InvalidJobTransitionError(DomainError):
    category: ClassVar[str] = "invalid_job_transition"


class DocumentAlreadyExistsError(DomainError):
    category: ClassVar[str] = "document_exists"


class DocumentNotFoundError(DomainError):
    category: ClassVar[str] = "document_not_found"


class BlobNotFoundError(DomainError):
    category: ClassVar[str] = "blob_not_found"


class UnknownCitationError(DomainError):
    """An answer cites a chunk that was not in the retrieved evidence."""

    category: ClassVar[str] = "unknown_citation"

    def __init__(self, unknown_ids: Iterable[ChunkId]) -> None:
        self.unknown_ids = frozenset(unknown_ids)
        super().__init__(f"citations not in retrieved evidence: {sorted(self.unknown_ids)}")


class AccessViolationError(DomainError):
    """A search adapter returned content the principal may not see. Always a bug (ADR-0003)."""

    category: ClassVar[str] = "access_violation"

    def __init__(self, chunk_ids: Iterable[ChunkId]) -> None:
        self.chunk_ids = frozenset(chunk_ids)
        super().__init__(f"retrieved chunks outside principal's access: {sorted(self.chunk_ids)}")
