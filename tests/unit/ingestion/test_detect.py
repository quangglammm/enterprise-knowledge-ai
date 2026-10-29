import io
import zipfile

import pytest

from enterprise_knowledge.domain.documents import ContentType
from enterprise_knowledge.ingestion.detect import detect_content_type
from enterprise_knowledge.ingestion.errors import (
    DocumentTooLargeError,
    EmptyDocumentError,
    UnsupportedFormatError,
)
from enterprise_knowledge.ingestion.limits import IngestionLimits
from tests.unit.ingestion.conftest import fixture_bytes


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("leave-policy-vi.pdf", ContentType.PDF),
        ("vpn-runbook-en.docx", ContentType.DOCX),
        ("handbook-mixed.html", ContentType.HTML),
        ("onboarding-vi.md", ContentType.MARKDOWN),
    ],
)
def test_detects_fixture_formats_from_content(name: str, expected: ContentType) -> None:
    assert detect_content_type(fixture_bytes(name), filename=name) is expected


def test_content_wins_over_misleading_extension() -> None:
    assert detect_content_type(fixture_bytes("leave-policy-vi.pdf"), filename="notes.txt") is (
        ContentType.PDF
    )


def test_declared_type_contradicting_content_is_rejected() -> None:
    with pytest.raises(UnsupportedFormatError, match="declared"):
        detect_content_type(
            fixture_bytes("leave-policy-vi.pdf"), filename="x.pdf", declared=ContentType.DOCX
        )


def test_plain_text_by_extension() -> None:
    assert detect_content_type("Xin chào".encode(), filename="note.txt") is ContentType.TEXT


def test_zip_that_is_not_docx_is_unsupported() -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("data.csv", "a,b")

    with pytest.raises(UnsupportedFormatError):
        detect_content_type(buffer.getvalue(), filename="data.docx")


@pytest.mark.parametrize(
    ("data", "filename"),
    [
        (b"\x89PNG\r\n\x1a\n" + b"\x00" * 20, "image.png"),
        (b"\xff\xfe\x00\x00binary", "file.md"),
        (b"plain text without known extension", "file.bin"),
    ],
)
def test_unknown_or_binary_content_is_unsupported(data: bytes, filename: str) -> None:
    with pytest.raises(UnsupportedFormatError):
        detect_content_type(data, filename=filename)


def test_empty_input_is_rejected_before_detection() -> None:
    with pytest.raises(EmptyDocumentError):
        detect_content_type(b"", filename="empty.pdf")


def test_oversized_input_is_rejected() -> None:
    limits = IngestionLimits(max_bytes=10)

    with pytest.raises(DocumentTooLargeError):
        detect_content_type(fixture_bytes("onboarding-vi.md"), filename="a.md", limits=limits)
