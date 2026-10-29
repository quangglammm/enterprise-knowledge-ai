"""IngestDocument: bytes in, an indexed, searchable document version out."""

import pytest

from enterprise_knowledge.domain.documents import DocumentStatus
from enterprise_knowledge.domain.errors import DocumentNotFoundError, ModelRateLimitedError
from enterprise_knowledge.domain.ids import DocumentId
from enterprise_knowledge.ingestion.errors import CorruptDocumentError
from enterprise_knowledge.ingestion.ingest import HEADER_SEPARATOR, blob_key, embedding_input
from tests.factories import TENANT, make_policy, make_principal
from tests.unit.ingestion.conftest import Harness, fixture_bytes

PDF = fixture_bytes("leave-policy-vi.pdf")
DOCX = fixture_bytes("vpn-runbook-en.docx")


async def test_new_document_is_indexed_stored_and_searchable(harness: Harness) -> None:
    result = await harness.ingest(data=PDF, filename="leave.pdf", access=make_policy())

    document = result.document
    assert not result.duplicate
    assert (document.id, document.version, document.status) == ("doc-1", 1, DocumentStatus.INDEXED)
    assert document.title == "Quy chế nghỉ phép"
    assert result.chunk_count == len(await harness.store.list_chunks(TENANT, document.id, 1)) > 0
    assert await harness.blobs.get(blob_key(TENANT, document.id, 1)) == PDF
    assert ("doc-1", 1) in await harness.search("số ngày nghỉ phép năm")


async def test_embedding_input_carries_title_and_section(harness: Harness) -> None:
    await harness.ingest(data=PDF, filename="leave.pdf", access=make_policy())

    inputs = harness.embedder.document_inputs
    assert all(i.startswith("Quy chế nghỉ phép") for i in inputs)
    assert any("Điều 2. Số ngày nghỉ phép năm" in i for i in inputs)


def test_embedding_input_format() -> None:
    assert embedding_input("Title", "Section", "Body") == f"Title{HEADER_SEPARATOR}Section\n\nBody"
    assert embedding_input("Title", None, "Body") == "Title\n\nBody"


async def test_identical_upload_is_deduplicated(harness: Harness) -> None:
    first = await harness.ingest(data=PDF, filename="leave.pdf", access=make_policy())
    calls = harness.embedder.calls

    again = await harness.ingest(data=PDF, filename="copy-of-leave.pdf", access=make_policy())

    assert again.duplicate
    assert again.document == first.document
    assert harness.embedder.calls == calls  # no re-embedding


async def test_same_content_with_new_access_policy_creates_a_new_version(harness: Harness) -> None:
    await harness.ingest(data=PDF, filename="leave.pdf", access=make_policy())

    restricted = await harness.ingest(
        data=PDF, filename="leave.pdf", access=make_policy(TENANT, "hr")
    )

    assert not restricted.duplicate
    assert (restricted.document.id, restricted.document.version) == ("doc-1", 2)
    assert await harness.search("nghỉ phép năm", "all-staff") == []


async def test_upload_for_existing_document_creates_next_version(harness: Harness) -> None:
    await harness.ingest(data=PDF, filename="leave.pdf", access=make_policy())

    result = await harness.ingest(
        data=DOCX, filename="v2.docx", access=make_policy(), document_id=DocumentId("doc-1")
    )

    assert (result.document.id, result.document.version) == ("doc-1", 2)
    assert await harness.search("VPN client gateway") == [("doc-1", 2)]


async def test_unknown_document_id_is_rejected(harness: Harness) -> None:
    with pytest.raises(DocumentNotFoundError):
        await harness.ingest(
            data=PDF, filename="x.pdf", access=make_policy(), document_id=DocumentId("missing")
        )


async def test_deleted_document_cannot_get_a_new_version(harness: Harness) -> None:
    await harness.ingest(data=PDF, filename="leave.pdf", access=make_policy())
    await harness.delete(principal=make_principal(), document_id=DocumentId("doc-1"))

    with pytest.raises(DocumentNotFoundError):
        await harness.ingest(
            data=DOCX, filename="v2.docx", access=make_policy(), document_id=DocumentId("doc-1")
        )

    assert await harness.search("VPN client gateway") == []


async def test_same_file_after_delete_is_indexed_as_a_new_document(harness: Harness) -> None:
    await harness.ingest(data=PDF, filename="leave.pdf", access=make_policy())
    await harness.delete(principal=make_principal(), document_id=DocumentId("doc-1"))

    again = await harness.ingest(data=PDF, filename="leave.pdf", access=make_policy())

    assert not again.duplicate
    assert (again.document.id, again.document.version) == ("doc-2", 1)
    assert await harness.search("số ngày nghỉ phép năm") == [("doc-2", 1)]


async def test_unparseable_upload_stores_nothing(harness: Harness) -> None:
    with pytest.raises(CorruptDocumentError):
        await harness.ingest(data=b"%PDF-1.7 broken", filename="x.pdf", access=make_policy())

    assert harness.blobs.objects == {}
    assert await harness.store.get_document(TENANT, DocumentId("doc-1")) is None


async def test_embedding_failure_marks_version_failed_and_keeps_previous(
    harness: Harness,
) -> None:
    await harness.ingest(data=PDF, filename="leave.pdf", access=make_policy())
    harness.embedder.fail_with = TimeoutError("provider timed out")

    with pytest.raises(TimeoutError):
        await harness.ingest(
            data=DOCX, filename="v2.docx", access=make_policy(), document_id=DocumentId("doc-1")
        )

    current = await harness.store.get_document(TENANT, DocumentId("doc-1"))
    assert current is not None
    assert (current.version, current.status) == (2, DocumentStatus.FAILED)
    assert current.error_category == "indexing_error"
    assert await harness.search("số ngày nghỉ phép năm") == [("doc-1", 1)]


async def test_provider_failure_is_recorded_with_its_category(harness: Harness) -> None:
    harness.embedder.fail_with = ModelRateLimitedError("POST /embeddings returned 429")

    with pytest.raises(ModelRateLimitedError):
        await harness.ingest(data=PDF, filename="leave.pdf", access=make_policy())

    failed = await harness.store.get_document(TENANT, DocumentId("doc-1"))
    assert failed is not None
    assert (failed.status, failed.error_category) == (DocumentStatus.FAILED, "model_rate_limited")


async def test_reupload_after_failure_retries_instead_of_deduplicating(harness: Harness) -> None:
    harness.embedder.fail_with = TimeoutError("provider timed out")
    with pytest.raises(TimeoutError):
        await harness.ingest(data=PDF, filename="leave.pdf", access=make_policy())
    harness.embedder.fail_with = None

    result = await harness.ingest(data=PDF, filename="leave.pdf", access=make_policy())

    assert not result.duplicate
    assert (result.document.id, result.document.version) == ("doc-1", 2)
    assert result.document.status is DocumentStatus.INDEXED


async def test_explicit_title_overrides_extracted_title(harness: Harness) -> None:
    result = await harness.ingest(
        data=PDF, filename="leave.pdf", access=make_policy(), title="Leave policy 2026"
    )

    assert result.document.title == "Leave policy 2026"
