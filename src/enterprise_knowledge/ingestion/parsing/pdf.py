"""PDF text extraction with pypdf (ADR-0006).

pypdf returns one string per page with lines broken wherever the renderer wrapped them and
no paragraph markers. Paragraphs are rebuilt by joining lines until one ends a sentence;
headings are recognized by patterns common in Vietnamese and English policy documents.
"""

import io
import re

from pypdf import PdfReader
from pypdf.errors import PdfReadError, PdfStreamError

from enterprise_knowledge.ingestion.errors import (
    CorruptDocumentError,
    DocumentTooLargeError,
    EncryptedDocumentError,
)
from enterprise_knowledge.ingestion.limits import IngestionLimits
from enterprise_knowledge.ingestion.normalize import normalize_text
from enterprise_knowledge.ingestion.parsing.model import BlockBuilder, BlockKind, ParsedDocument

_KEYWORD_HEADING = re.compile(
    r"^(chương|phần|mục|điều|chapter|section|article|part)\s+[0-9ivxlc]+[.:]?(\s|$)",
    re.IGNORECASE,
)
_NUMBERED_HEADING = re.compile(r"^\d+(\.\d+)*\.?\s+\S")
_MAX_NUMBERED_HEADING_CHARS = 80
_SENTENCE_END = (".", "!", "?", "…", ":", ";")


def parse_pdf(data: bytes, limits: IngestionLimits) -> ParsedDocument:
    reader = _open(data)
    page_count = len(reader.pages)
    if page_count > limits.max_pages:
        raise DocumentTooLargeError(f"{page_count} pages; limit is {limits.max_pages} pages")

    builder = BlockBuilder()
    try:
        for page_number, page in enumerate(reader.pages, start=1):
            _add_page(builder, page.extract_text() or "", page_number)
        metadata_title = reader.metadata.title if reader.metadata else None
    except (PdfReadError, PdfStreamError, ValueError, KeyError) as exc:
        raise CorruptDocumentError("PDF content could not be extracted") from exc

    title = normalize_text(metadata_title) if metadata_title else None
    return builder.build(title=title, page_count=page_count)


def _open(data: bytes) -> PdfReader:
    try:
        reader = PdfReader(io.BytesIO(data), strict=False)
        if reader.is_encrypted and not reader.decrypt(""):
            raise EncryptedDocumentError("PDF requires a password")
        _ = len(reader.pages)  # forces the page tree to load
    except EncryptedDocumentError:
        raise
    except Exception as exc:
        # pypdf raises a wide variety of errors on malformed files; all mean "corrupt".
        raise CorruptDocumentError("PDF could not be read") from exc
    return reader


def _add_page(builder: BlockBuilder, page_text: str, page_number: int) -> None:
    paragraph: list[str] = []

    def flush() -> None:
        if paragraph:
            builder.add(BlockKind.PARAGRAPH, " ".join(paragraph), page=page_number)
            paragraph.clear()

    for raw_line in page_text.splitlines():
        line = normalize_text(raw_line)
        if not line:
            flush()
            continue
        if _is_heading(line):
            flush()
            builder.add(BlockKind.HEADING, line, page=page_number)
            continue
        paragraph.append(line)
        if line.endswith(_SENTENCE_END):
            flush()
    flush()


def _is_heading(line: str) -> bool:
    if _KEYWORD_HEADING.match(line):
        return True
    return (
        bool(_NUMBERED_HEADING.match(line))
        and len(line) <= _MAX_NUMBERED_HEADING_CHARS
        and not line.endswith((".", ",", ";", ":"))
    )
