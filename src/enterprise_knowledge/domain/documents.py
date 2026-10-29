"""Documents, their chunks and embeddings."""

import math
from collections.abc import Iterable, Sequence
from enum import StrEnum
from typing import Annotated, Self

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

from enterprise_knowledge.domain.access import AccessPolicy
from enterprise_knowledge.domain.ids import ChunkId, DocumentId, TenantId, chunk_id_for
from enterprise_knowledge.domain.text import normalize_nfc

Sha256Hex = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


def _non_blank_nfc(value: str) -> str:
    normalized = normalize_nfc(value)
    if not normalized.strip():
        raise ValueError("text must not be blank")
    return normalized


NonBlankText = Annotated[str, AfterValidator(_non_blank_nfc)]


class ContentType(StrEnum):
    PDF = "application/pdf"
    DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    HTML = "text/html"
    MARKDOWN = "text/markdown"
    TEXT = "text/plain"


class Language(StrEnum):
    VI = "vi"
    EN = "en"
    MIXED = "mixed"
    UNKNOWN = "und"


class DocumentStatus(StrEnum):
    PENDING = "pending"
    INDEXED = "indexed"
    FAILED = "failed"
    DELETED = "deleted"


class Document(BaseModel):
    """One version of a source document. A content change creates a new version (ING-03)."""

    model_config = ConfigDict(frozen=True)

    id: DocumentId
    title: NonBlankText = Field(max_length=500)
    filename: str = Field(min_length=1, max_length=255)
    content_type: ContentType
    checksum: Sha256Hex
    version: int = Field(ge=1)
    status: DocumentStatus
    access: AccessPolicy
    language: Language
    created_at: AwareDatetime
    updated_at: AwareDatetime
    error_category: str | None = None

    @model_validator(mode="after")
    def _failed_needs_category(self) -> Self:
        if self.status is DocumentStatus.FAILED and not self.error_category:
            raise ValueError("error_category is required when status is failed")
        return self

    @property
    def tenant_id(self) -> TenantId:
        return self.access.tenant_id

    def with_status(
        self, status: DocumentStatus, *, now: AwareDatetime, error_category: str | None = None
    ) -> "Document":
        return self.model_validate(
            self.model_dump()
            | {"status": status, "updated_at": now, "error_category": error_category}
        )


class SourceLocation(BaseModel):
    """Where a chunk came from, for citations. Fields are optional because formats differ."""

    model_config = ConfigDict(frozen=True)

    page: int | None = Field(default=None, ge=1)
    section: str | None = Field(default=None, max_length=500)
    char_start: int | None = Field(default=None, ge=0)
    char_end: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _span_is_ordered(self) -> Self:
        start, end = self.char_start, self.char_end
        if start is not None and end is not None and end <= start:
            raise ValueError("char_end must be greater than char_start")
        return self


class DocumentChunk(BaseModel):
    """A retrievable span of one document version. Its ID is derived, never chosen."""

    model_config = ConfigDict(frozen=True)

    id: ChunkId
    document_id: DocumentId
    document_version: int = Field(ge=1)
    chunk_index: int = Field(ge=0)
    text: NonBlankText
    source: SourceLocation
    access: AccessPolicy
    language: Language

    @model_validator(mode="after")
    def _id_is_derived(self) -> Self:
        expected = chunk_id_for(self.document_id, self.document_version, self.chunk_index)
        if self.id != expected:
            raise ValueError("chunk id must equal chunk_id_for(document_id, version, index)")
        return self

    @classmethod
    def for_document(
        cls,
        document: Document,
        *,
        index: int,
        text: str,
        source: SourceLocation,
        language: Language | None = None,
    ) -> "DocumentChunk":
        return cls(
            id=chunk_id_for(document.id, document.version, index),
            document_id=document.id,
            document_version=document.version,
            chunk_index=index,
            text=text,
            source=source,
            access=document.access,
            language=language or document.language,
        )


class Embedding(BaseModel):
    """A chunk's vector, tagged with the model that produced it (ADR-0004)."""

    model_config = ConfigDict(frozen=True)

    chunk_id: ChunkId
    model: str = Field(min_length=1)
    dimension: int = Field(ge=1)
    vector: tuple[float, ...]

    @model_validator(mode="after")
    def _vector_matches_dimension(self) -> Self:
        if len(self.vector) != self.dimension:
            raise ValueError(f"vector length {len(self.vector)} != dimension {self.dimension}")
        if not all(math.isfinite(v) for v in self.vector):
            raise ValueError("vector values must be finite")
        return self


def serving_version(versions: Iterable[Document]) -> int | None:
    """The version search should serve: the highest one that is indexed (ADR-0007).

    A newer pending or failed version does not hide the previous indexed one, so a
    re-upload is never a search outage for that document.
    """
    indexed = [d.version for d in versions if d.status is DocumentStatus.INDEXED]
    return max(indexed, default=None)


def validate_chunk_set(
    document: Document, chunks: Sequence[DocumentChunk], embeddings: Sequence[Embedding]
) -> None:
    """Rules every repository enforces before replacing a version's chunks."""
    for chunk in chunks:
        if (chunk.document_id, chunk.document_version) != (document.id, document.version):
            raise ValueError(
                f"chunk {chunk.id} does not belong to {document.id} v{document.version}"
            )
        if chunk.access.tenant_id != document.tenant_id:
            raise ValueError(f"chunk {chunk.id} belongs to another tenant")
    chunk_ids = [c.id for c in chunks]
    if len(set(chunk_ids)) != len(chunk_ids):
        raise ValueError("duplicate chunks")
    if sorted(chunk_ids) != sorted(e.chunk_id for e in embeddings):
        raise ValueError("every chunk needs exactly one embedding")
    if len({e.model for e in embeddings}) > 1:
        raise ValueError("all embeddings of a version must come from one model")
