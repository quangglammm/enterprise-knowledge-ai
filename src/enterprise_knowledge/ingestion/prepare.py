"""Prepare raw upload bytes for indexing: detect, parse, normalize, chunk, fingerprint.

Pure and synchronous (CPU-bound). The async ingestion use case runs it in a worker thread
and then persists and embeds the result.
"""

import hashlib
from pathlib import PurePosixPath

from pydantic import BaseModel, ConfigDict

from enterprise_knowledge.domain.documents import ContentType, Language
from enterprise_knowledge.ingestion.chunking import ChunkDraft, ChunkingSettings, chunk_document
from enterprise_knowledge.ingestion.detect import detect_content_type
from enterprise_knowledge.ingestion.language import document_language
from enterprise_knowledge.ingestion.limits import IngestionLimits
from enterprise_knowledge.ingestion.normalize import normalize_text
from enterprise_knowledge.ingestion.parsing import parse_document


class PreparedDocument(BaseModel):
    model_config = ConfigDict(frozen=True)

    checksum: str
    content_type: ContentType
    title: str
    language: Language
    text: str
    page_count: int | None
    chunks: tuple[ChunkDraft, ...]
    chunking: ChunkingSettings


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def prepare_document(
    data: bytes,
    *,
    filename: str,
    declared: ContentType | None = None,
    limits: IngestionLimits | None = None,
    chunking: ChunkingSettings | None = None,
) -> PreparedDocument:
    limits = limits or IngestionLimits()
    chunking = chunking or ChunkingSettings()

    content_type = detect_content_type(data, filename=filename, declared=declared, limits=limits)
    parsed = parse_document(data, content_type, limits)
    text, drafts = chunk_document(parsed, chunking)

    return PreparedDocument(
        checksum=sha256_hex(data),
        content_type=content_type,
        title=parsed.title or normalize_text(PurePosixPath(filename).stem) or "untitled",
        language=document_language((d.language, len(d.text)) for d in drafts),
        text=text,
        page_count=parsed.page_count,
        chunks=tuple(drafts),
        chunking=chunking,
    )
