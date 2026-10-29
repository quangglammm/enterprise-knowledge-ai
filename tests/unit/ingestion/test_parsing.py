"""ING-01: supported formats produce normalized text and metadata; bad input gives typed errors."""

import io
import unicodedata
import zipfile

import pytest
from pypdf import PdfWriter

from enterprise_knowledge.domain.documents import ContentType
from enterprise_knowledge.ingestion.errors import (
    CorruptDocumentError,
    DocumentTooLargeError,
    EmptyDocumentError,
    EncryptedDocumentError,
    IngestionError,
)
from enterprise_knowledge.ingestion.limits import IngestionLimits
from enterprise_knowledge.ingestion.parsing import BlockKind, ParsedDocument, parse_document
from tests.unit.ingestion.conftest import fixture_bytes

PDF_OWNER_KEY = "owner-key-for-tests"
PDF_USER_KEY = "user-key-for-tests"


def parse_fixture(name: str, content_type: ContentType) -> ParsedDocument:
    return parse_document(fixture_bytes(name), content_type)


def texts(parsed: ParsedDocument, kind: BlockKind | None = None) -> list[str]:
    return [b.text for b in parsed.blocks if kind is None or b.kind is kind]


# --- PDF -----------------------------------------------------------------------------


def test_pdf_extracts_vietnamese_headings_paragraphs_and_pages() -> None:
    parsed = parse_fixture("leave-policy-vi.pdf", ContentType.PDF)

    assert parsed.title == "Quy chế nghỉ phép"
    assert parsed.page_count == 2
    assert texts(parsed, BlockKind.HEADING) == [
        "Điều 1. Phạm vi áp dụng",
        "Điều 2. Số ngày nghỉ phép năm",
        "Điều 3. Thủ tục xin nghỉ phép",
    ]
    assert {b.page for b in parsed.blocks if b.text.startswith("Điều 3")} == {2}


def test_pdf_rejoins_wrapped_lines_into_one_paragraph() -> None:
    parsed = parse_fixture("leave-policy-vi.pdf", ContentType.PDF)

    paragraph = next(t for t in texts(parsed, BlockKind.PARAGRAPH) if t.startswith("Quy chế"))

    assert paragraph.endswith("chi nhánh Thành phố Hồ Chí Minh.")
    assert "  " not in paragraph


def test_pdf_blocks_know_their_section() -> None:
    parsed = parse_fixture("leave-policy-vi.pdf", ContentType.PDF)

    block = next(b for b in parsed.blocks if "12 ngày làm việc" in b.text)

    assert block.section == "Điều 2. Số ngày nghỉ phép năm"


def test_pdf_with_only_owner_password_is_readable() -> None:
    writer = PdfWriter(clone_from=io.BytesIO(fixture_bytes("leave-policy-vi.pdf")))
    writer.encrypt(user_password="", owner_password=PDF_OWNER_KEY)
    data = io.BytesIO()
    writer.write(data)

    parsed = parse_document(data.getvalue(), ContentType.PDF)

    assert parsed.page_count == 2


def test_password_protected_pdf_raises_encrypted() -> None:
    writer = PdfWriter(clone_from=io.BytesIO(fixture_bytes("leave-policy-vi.pdf")))
    writer.encrypt(user_password=PDF_USER_KEY)
    data = io.BytesIO()
    writer.write(data)

    with pytest.raises(EncryptedDocumentError):
        parse_document(data.getvalue(), ContentType.PDF)


def test_pdf_without_text_raises_empty() -> None:
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    data = io.BytesIO()
    writer.write(data)

    with pytest.raises(EmptyDocumentError):
        parse_document(data.getvalue(), ContentType.PDF)


def test_pdf_over_page_limit_raises_too_large() -> None:
    with pytest.raises(DocumentTooLargeError, match="pages"):
        parse_document(
            fixture_bytes("leave-policy-vi.pdf"), ContentType.PDF, IngestionLimits(max_pages=1)
        )


# --- DOCX ----------------------------------------------------------------------------


def test_docx_uses_heading_styles_lists_and_tables_in_order() -> None:
    parsed = parse_fixture("vpn-runbook-en.docx", ContentType.DOCX)

    assert parsed.title == "VPN access runbook"
    assert texts(parsed, BlockKind.HEADING)[:3] == [
        "VPN access runbook",
        "Purpose",
        "Prerequisites",
    ]
    assert texts(parsed, BlockKind.TABLE) == [
        "Gateway | Region | Address",
        "HN-1 | Hanoi | vpn-hn.example.internal",
        "HCM-1 | Ho Chi Minh City | vpn-hcm.example.internal",
    ]
    steps = texts(parsed, BlockKind.LIST_ITEM)
    assert steps[0].startswith("Open the VPN client")
    kinds = [b.kind for b in parsed.blocks]
    assert kinds.index(BlockKind.TABLE) < texts(parsed).index("Connection steps")


def test_docx_table_rows_belong_to_their_section() -> None:
    parsed = parse_fixture("vpn-runbook-en.docx", ContentType.DOCX)

    sections = {b.section for b in parsed.blocks if b.kind is BlockKind.TABLE}

    assert sections == {"Prerequisites"}


# --- HTML ----------------------------------------------------------------------------


def test_html_keeps_content_and_drops_boilerplate_and_hidden_elements() -> None:
    parsed = parse_fixture("handbook-mixed.html", ContentType.HTML)
    joined = "\n".join(texts(parsed))

    assert parsed.title == "Sổ tay nhân viên - Employee Handbook"
    assert "Giờ làm việc tiêu chuẩn từ 8 giờ 30 đến 17 giờ 30" in joined
    assert "respond to pages within 15 minutes" in joined
    for leaked in ("analytics", "Bamboo Harbor Intranet", "Hidden tracking", "©", "font-family"):
        assert leaked not in joined


def test_html_headings_and_list_items() -> None:
    parsed = parse_fixture("handbook-mixed.html", ContentType.HTML)

    assert texts(parsed, BlockKind.HEADING) == [
        "Sổ tay nhân viên",
        "Giờ làm việc",
        "Working hours for engineering on-call",
    ]
    assert len(texts(parsed, BlockKind.LIST_ITEM)) == 2


def test_html_with_only_boilerplate_raises_empty() -> None:
    html = b"<html><body><nav>Menu</nav><script>x()</script></body></html>"

    with pytest.raises(EmptyDocumentError):
        parse_document(html, ContentType.HTML)


# --- Markdown and text ---------------------------------------------------------------


def test_markdown_headings_become_sections() -> None:
    parsed = parse_fixture("onboarding-vi.md", ContentType.MARKDOWN)

    assert parsed.title == "Hướng dẫn hội nhập nhân viên mới"
    assert texts(parsed, BlockKind.HEADING) == [
        "Hướng dẫn hội nhập nhân viên mới",
        "Tuần đầu tiên",
        "Tài khoản và công cụ",
    ]
    paragraph = next(b for b in parsed.blocks if b.text.startswith("Trong tuần đầu tiên"))
    assert paragraph.section == "Tuần đầu tiên"
    assert paragraph.text.endswith("nhận laptop từ phòng IT.")


def test_text_with_bom_and_nfd_is_normalized() -> None:
    data = b"\xef\xbb\xbf" + unicodedata.normalize("NFD", "Quy định\n\nĐoạn hai").encode()

    parsed = parse_document(data, ContentType.TEXT)

    assert texts(parsed) == ["Quy định", "Đoạn hai"]


def test_invalid_utf8_text_raises_corrupt() -> None:
    with pytest.raises(CorruptDocumentError):
        parse_document(b"\xff\xfe\xfa not utf-8", ContentType.MARKDOWN)


# --- Corrupt input for every binary format -------------------------------------------


@pytest.mark.parametrize(
    ("data", "content_type"),
    [
        (b"%PDF-1.7\n garbage that is not a pdf", ContentType.PDF),
        (fixture_bytes("leave-policy-vi.pdf")[:500], ContentType.PDF),
        (b"PK\x03\x04 truncated zip", ContentType.DOCX),
    ],
    ids=["pdf-garbage", "pdf-truncated", "docx-truncated"],
)
def test_corrupt_documents_raise_corrupt(data: bytes, content_type: ContentType) -> None:
    with pytest.raises(CorruptDocumentError):
        parse_document(data, content_type)


def test_docx_zip_without_document_xml_raises_corrupt() -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")

    with pytest.raises(CorruptDocumentError):
        parse_document(buffer.getvalue(), ContentType.DOCX)


# --- Error contract ------------------------------------------------------------------


@pytest.mark.parametrize(
    "error",
    [CorruptDocumentError, EmptyDocumentError, EncryptedDocumentError, DocumentTooLargeError],
)
def test_ingestion_errors_are_permanent_with_stable_categories(
    error: type[IngestionError],
) -> None:
    assert error.retryable is False
    assert error.category.isidentifier()
    assert issubclass(error, IngestionError)


def test_all_blocks_are_nfc_and_non_blank() -> None:
    for name, content_type in [
        ("leave-policy-vi.pdf", ContentType.PDF),
        ("vpn-runbook-en.docx", ContentType.DOCX),
        ("handbook-mixed.html", ContentType.HTML),
        ("onboarding-vi.md", ContentType.MARKDOWN),
    ]:
        for block in parse_fixture(name, content_type).blocks:
            assert block.text.strip() == block.text != ""
            assert unicodedata.is_normalized("NFC", block.text)
