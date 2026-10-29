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


class ModelProviderError(DomainError):
    """A model provider call failed (ADR-0010). Messages never carry prompts, bodies or keys.

    ``retryable`` tells a caller (for example the Week 5 worker) whether trying the same
    work later can succeed; the adapter has already spent its own retry budget.
    """

    category: ClassVar[str] = "model_provider_error"
    retryable: ClassVar[bool] = False


class ModelRateLimitedError(ModelProviderError):
    category: ClassVar[str] = "model_rate_limited"
    retryable: ClassVar[bool] = True


class ModelUnavailableError(ModelProviderError):
    """Server errors, connection failures or timeouts that outlasted the retries."""

    category: ClassVar[str] = "model_unavailable"
    retryable: ClassVar[bool] = True


class ModelAuthenticationError(ModelProviderError):
    category: ClassVar[str] = "model_auth_failed"


class ModelRequestRejectedError(ModelProviderError):
    """The provider refused the request itself (unknown model, bad parameters)."""

    category: ClassVar[str] = "model_request_rejected"


class ModelResponseError(ModelProviderError):
    """A success status with a body that is not the expected shape."""

    category: ClassVar[str] = "model_invalid_response"
