"""Typed ingestion failures. All are permanent: retrying the same bytes cannot succeed."""

from typing import ClassVar

from enterprise_knowledge.domain.errors import DomainError


class IngestionError(DomainError):
    category: ClassVar[str] = "ingestion_error"
    retryable: ClassVar[bool] = False


class UnsupportedFormatError(IngestionError):
    category: ClassVar[str] = "unsupported_format"


class CorruptDocumentError(IngestionError):
    category: ClassVar[str] = "corrupt_document"


class EncryptedDocumentError(IngestionError):
    category: ClassVar[str] = "encrypted_document"


class EmptyDocumentError(IngestionError):
    category: ClassVar[str] = "empty_document"


class DocumentTooLargeError(IngestionError):
    category: ClassVar[str] = "document_too_large"
