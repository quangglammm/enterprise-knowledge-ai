"""Content-type detection from bytes. The client's filename and declared type are hints only."""

import io
import zipfile
from pathlib import PurePosixPath

from enterprise_knowledge.domain.documents import ContentType
from enterprise_knowledge.ingestion.errors import (
    DocumentTooLargeError,
    EmptyDocumentError,
    UnsupportedFormatError,
)
from enterprise_knowledge.ingestion.limits import IngestionLimits

_TEXT_EXTENSIONS = {
    ".md": ContentType.MARKDOWN,
    ".markdown": ContentType.MARKDOWN,
    ".txt": ContentType.TEXT,
}
_TEXT_LIKE = frozenset({ContentType.MARKDOWN, ContentType.TEXT})
_HTML_SNIFF_BYTES = 2048


def detect_content_type(
    data: bytes,
    *,
    filename: str,
    declared: ContentType | None = None,
    limits: IngestionLimits | None = None,
) -> ContentType:
    limits = limits or IngestionLimits()
    if not data:
        raise EmptyDocumentError("document has no content")
    if len(data) > limits.max_bytes:
        raise DocumentTooLargeError(f"document is {len(data)} bytes; limit is {limits.max_bytes}")

    detected = _sniff(data, filename)
    if declared is not None and declared is not detected:
        if not (declared in _TEXT_LIKE and detected in _TEXT_LIKE):
            raise UnsupportedFormatError(
                f"declared {declared.value} but content is {detected.value}"
            )
        detected = declared
    return detected


def _sniff(data: bytes, filename: str) -> ContentType:
    if data.startswith(b"%PDF-"):
        return ContentType.PDF
    if data.startswith(b"PK\x03\x04"):
        if _is_docx(data):
            return ContentType.DOCX
        raise UnsupportedFormatError("zip archive is not a Word document")

    text = _decode_utf8(data)
    if text is None:
        raise UnsupportedFormatError("binary content of an unsupported format")
    head = text[:_HTML_SNIFF_BYTES].lstrip().lower()
    if head.startswith("<!doctype html") or "<html" in head:
        return ContentType.HTML

    suffix = PurePosixPath(filename).suffix.lower()
    if suffix in _TEXT_EXTENSIONS:
        return _TEXT_EXTENSIONS[suffix]
    raise UnsupportedFormatError(f"unsupported file type {suffix or '(no extension)'}")


def _is_docx(data: bytes) -> bool:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            return "word/document.xml" in archive.namelist()
    except zipfile.BadZipFile:
        return False


def _decode_utf8(data: bytes) -> str | None:
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return None
