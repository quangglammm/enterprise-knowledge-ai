"""End-to-end preparation of raw bytes: detect, parse, normalize, chunk, fingerprint."""

import hashlib

import pytest

from enterprise_knowledge.domain.documents import ContentType, Language
from enterprise_knowledge.ingestion.errors import UnsupportedFormatError
from enterprise_knowledge.ingestion.prepare import prepare_document
from tests.unit.ingestion.conftest import fixture_bytes


@pytest.mark.parametrize(
    ("name", "content_type", "language", "title"),
    [
        ("leave-policy-vi.pdf", ContentType.PDF, Language.VI, "Quy chế nghỉ phép"),
        ("vpn-runbook-en.docx", ContentType.DOCX, Language.EN, "VPN access runbook"),
        (
            "handbook-mixed.html",
            ContentType.HTML,
            Language.MIXED,
            "Sổ tay nhân viên - Employee Handbook",
        ),
        ("onboarding-vi.md", ContentType.MARKDOWN, Language.VI, "Hướng dẫn hội nhập nhân viên mới"),
    ],
)
def test_prepares_each_fixture(
    name: str, content_type: ContentType, language: Language, title: str
) -> None:
    data = fixture_bytes(name)

    prepared = prepare_document(data, filename=name)

    assert prepared.content_type is content_type
    assert prepared.language is language
    assert prepared.title == title
    assert prepared.checksum == hashlib.sha256(data).hexdigest()
    assert prepared.chunks
    assert all(prepared.text[c.char_start : c.char_end] == c.text for c in prepared.chunks)


def test_same_bytes_give_identical_preparation() -> None:
    data = fixture_bytes("vpn-runbook-en.docx")

    assert prepare_document(data, filename="a.docx") == prepare_document(data, filename="a.docx")


def test_title_falls_back_to_filename_stem() -> None:
    prepared = prepare_document(b"Just one paragraph of plain text.", filename="notes-2026.txt")

    assert prepared.title == "notes-2026"


def test_declared_type_mismatch_is_rejected() -> None:
    with pytest.raises(UnsupportedFormatError):
        prepare_document(
            fixture_bytes("onboarding-vi.md"), filename="x.md", declared=ContentType.PDF
        )
