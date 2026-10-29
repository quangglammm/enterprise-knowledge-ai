"""Parse document bytes of a known content type into normalized blocks (ING-01)."""

from enterprise_knowledge.domain.documents import ContentType
from enterprise_knowledge.ingestion.errors import CorruptDocumentError, DocumentTooLargeError
from enterprise_knowledge.ingestion.limits import IngestionLimits
from enterprise_knowledge.ingestion.parsing.html import parse_html
from enterprise_knowledge.ingestion.parsing.model import Block, BlockKind, ParsedDocument
from enterprise_knowledge.ingestion.parsing.pdf import parse_pdf
from enterprise_knowledge.ingestion.parsing.text import parse_text
from enterprise_knowledge.ingestion.parsing.word import parse_docx

__all__ = ["Block", "BlockKind", "ParsedDocument", "parse_document"]


def parse_document(
    data: bytes, content_type: ContentType, limits: IngestionLimits | None = None
) -> ParsedDocument:
    """CPU-bound and synchronous; async callers run it with ``asyncio.to_thread``."""
    limits = limits or IngestionLimits()
    if len(data) > limits.max_bytes:
        raise DocumentTooLargeError(f"document is {len(data)} bytes; limit is {limits.max_bytes}")

    match content_type:
        case ContentType.PDF:
            return parse_pdf(data, limits)
        case ContentType.DOCX:
            return parse_docx(data)
        case ContentType.HTML:
            return parse_html(_decode(data, lenient=True))
        case ContentType.MARKDOWN:
            return parse_text(_decode(data), markdown=True)
        case ContentType.TEXT:
            return parse_text(_decode(data), markdown=False)


def _decode(data: bytes, *, lenient: bool = False) -> str:
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        if lenient:
            # Real-world HTML is often mislabeled; replacement keeps the rest usable.
            return data.decode("utf-8", errors="replace")
        raise CorruptDocumentError("text is not valid UTF-8") from exc
