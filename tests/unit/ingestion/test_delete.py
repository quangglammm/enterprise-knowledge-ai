"""DeleteDocument: a deleted document leaves search, its chunks and its stored files."""

import pytest

from enterprise_knowledge.domain.documents import DocumentStatus
from enterprise_knowledge.domain.errors import DocumentNotFoundError
from enterprise_knowledge.domain.ids import DocumentId, TenantId
from tests.factories import TENANT, make_policy, make_principal
from tests.unit.ingestion.conftest import Harness, fixture_bytes

PDF = fixture_bytes("leave-policy-vi.pdf")
DOCX = fixture_bytes("vpn-runbook-en.docx")
DOC = DocumentId("doc-1")


async def ingest_two_versions(harness: Harness) -> None:
    await harness.ingest(data=PDF, filename="leave.pdf", access=make_policy())
    await harness.ingest(data=DOCX, filename="v2.docx", access=make_policy(), document_id=DOC)


async def test_deleted_document_is_no_longer_searchable(harness: Harness) -> None:
    await harness.ingest(data=PDF, filename="leave.pdf", access=make_policy())

    await harness.delete(principal=make_principal(), document_id=DOC)

    assert await harness.search("số ngày nghỉ phép năm") == []
    current = await harness.store.get_document(TENANT, DOC)
    assert current is not None
    assert current.status is DocumentStatus.DELETED


async def test_delete_removes_chunks_and_files_of_every_version(harness: Harness) -> None:
    await ingest_two_versions(harness)

    await harness.delete(principal=make_principal(), document_id=DOC)

    assert harness.blobs.objects == {}
    for version in (1, 2):
        assert await harness.store.list_chunks(TENANT, DOC, version) == []


async def test_delete_is_idempotent(harness: Harness) -> None:
    await harness.ingest(data=PDF, filename="leave.pdf", access=make_policy())

    await harness.delete(principal=make_principal(), document_id=DOC)
    await harness.delete(principal=make_principal(), document_id=DOC)

    assert harness.blobs.objects == {}


async def test_retrying_a_failed_delete_removes_the_remaining_files(harness: Harness) -> None:
    await ingest_two_versions(harness)
    harness.blobs.fail_deletes_with = OSError("disk unavailable")
    with pytest.raises(OSError, match="disk unavailable"):
        await harness.delete(principal=make_principal(), document_id=DOC)
    harness.blobs.fail_deletes_with = None

    await harness.delete(principal=make_principal(), document_id=DOC)

    assert harness.blobs.objects == {}


async def test_search_forgets_the_document_even_if_file_deletion_fails(harness: Harness) -> None:
    await harness.ingest(data=PDF, filename="leave.pdf", access=make_policy())
    harness.blobs.fail_deletes_with = OSError("disk unavailable")

    with pytest.raises(OSError, match="disk unavailable"):
        await harness.delete(principal=make_principal(), document_id=DOC)

    assert await harness.search("số ngày nghỉ phép năm") == []


@pytest.mark.parametrize(
    ("tenant", "groups"),
    [(TENANT, ("all-staff",)), (TenantId("other-co"), ("hr",))],
    ids=["other-group", "other-tenant"],
)
async def test_principal_who_cannot_read_the_document_cannot_delete_it(
    harness: Harness, tenant: TenantId, groups: tuple[str, ...]
) -> None:
    await harness.ingest(data=PDF, filename="leave.pdf", access=make_policy(TENANT, "hr"))

    with pytest.raises(DocumentNotFoundError):
        await harness.delete(principal=make_principal(tenant, *groups), document_id=DOC)

    assert await harness.search("số ngày nghỉ phép năm", "hr") == [("doc-1", 1)]
    assert len(harness.blobs.objects) == 1


async def test_deleting_an_unknown_document_raises_not_found(harness: Harness) -> None:
    with pytest.raises(DocumentNotFoundError):
        await harness.delete(principal=make_principal(), document_id=DocumentId("missing"))
