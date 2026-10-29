"""HTTP behavior of /v1 documents and search, with in-memory adapters."""

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError

from enterprise_knowledge.api.app import create_app
from enterprise_knowledge.api.services import Services
from enterprise_knowledge.config import Environment, Settings
from enterprise_knowledge.domain.documents import Document
from enterprise_knowledge.domain.errors import DocumentAlreadyExistsError
from enterprise_knowledge.ingestion.delete import DeleteDocument
from enterprise_knowledge.ingestion.ingest import IngestDocument
from enterprise_knowledge.ingestion.limits import IngestionLimits
from enterprise_knowledge.retrieval.search import SearchKnowledge
from tests.fakes.blob_store import InMemoryBlobStore
from tests.fakes.document_store import InMemoryDocumentStore
from tests.fakes.embedder import HashEmbedder
from tests.unit.ingestion.conftest import fixture_bytes

TENANT = "bamboo-harbor"
STAFF = {"x-tenant-id": TENANT, "x-user-id": "an", "x-user-groups": "all-staff"}
HR = {"x-tenant-id": TENANT, "x-user-id": "binh", "x-user-groups": "all-staff,hr"}
OTHER_TENANT = {"x-tenant-id": "other-co", "x-user-id": "x", "x-user-groups": "all-staff,hr"}
PDF = fixture_bytes("leave-policy-vi.pdf")
MAX_UPLOAD = 100_000


def make_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "environment": Environment.TEST,
        "database_url": SecretStr("postgresql://unused@localhost/unused"),
    }
    values.update(overrides)
    return Settings.model_validate(values)


def make_services(store: InMemoryDocumentStore) -> Services:
    embedder = HashEmbedder()
    blobs = InMemoryBlobStore()
    return Services(
        documents=store,
        ingest=IngestDocument(
            documents=store,
            embedder=embedder,
            blobs=blobs,
            limits=IngestionLimits(max_bytes=MAX_UPLOAD),
        ),
        delete=DeleteDocument(documents=store, blobs=blobs),
        search=SearchKnowledge(search=store, embedder=embedder),
        max_upload_bytes=MAX_UPLOAD,
    )


@pytest.fixture
def client() -> Iterator[TestClient]:
    services = make_services(InMemoryDocumentStore())
    with TestClient(create_app(make_settings(), services=services)) as test_client:
        yield test_client


@dataclass(frozen=True)
class Result:
    status: int
    body: dict[str, Any]
    request_id: str


def upload(
    client: TestClient,
    headers: dict[str, str],
    data: bytes = PDF,
    filename: str = "leave-policy.pdf",
    groups: str = "all-staff",
    **form: str,
) -> Result:
    response = client.post(
        "/v1/documents",
        headers=headers,
        files={"file": (filename, data)},
        data={"allowed_groups": groups, **form},
    )
    return Result(response.status_code, response.json(), response.headers["x-request-id"])


def assert_error(result: Result, status: int, category: str) -> None:
    assert result.status == status, result
    assert result.body["error"]["category"] == category
    assert result.body["error"]["request_id"] == result.request_id


# --- happy path ----------------------------------------------------------------------


def test_upload_inspect_and_search(client: TestClient) -> None:
    created = upload(client, STAFF)

    assert created.status == 201
    body = created.body
    document = body["document"]
    assert (document["version"], document["status"], document["language"]) == (1, "indexed", "vi")
    assert document["title"] == "Quy chế nghỉ phép"
    assert body["chunk_count"] > 0
    assert body["duplicate"] is False

    doc_id = document["id"]
    assert client.get(f"/v1/documents/{doc_id}", headers=STAFF).json()["id"] == doc_id
    chunks = client.get(f"/v1/documents/{doc_id}/chunks", headers=STAFF).json()
    assert chunks[0]["section"] == "Điều 1. Phạm vi áp dụng"
    assert [c["index"] for c in chunks] == list(range(len(chunks)))

    results = client.post(
        "/v1/search", headers=STAFF, json={"query": "số ngày nghỉ phép năm", "k": 3}
    ).json()["results"]
    assert results[0]["document_id"] == doc_id
    assert "12 ngày" in " ".join(r["text"] for r in results)


def test_identical_upload_returns_200_and_existing_document(client: TestClient) -> None:
    first = upload(client, STAFF)
    second = upload(client, STAFF, filename="copy.pdf")

    assert second.status == 200
    assert second.body["duplicate"] is True
    assert second.body["document"] == first.body["document"]


def test_new_version_of_existing_document(client: TestClient) -> None:
    doc_id = upload(client, STAFF).body["document"]["id"]

    result = upload(
        client, STAFF, data=fixture_bytes("onboarding-vi.md"), filename="v2.md", document_id=doc_id
    )

    assert result.status == 201
    assert result.body["document"]["version"] == 2


def test_delete_returns_204_and_removes_the_document(client: TestClient) -> None:
    doc_id = upload(client, STAFF).body["document"]["id"]

    response = client.delete(f"/v1/documents/{doc_id}", headers=STAFF)

    assert response.status_code == 204
    assert client.get(f"/v1/documents/{doc_id}", headers=STAFF).status_code == 404
    assert client.get(f"/v1/documents/{doc_id}/chunks", headers=STAFF).status_code == 404
    search = client.post("/v1/search", headers=STAFF, json={"query": "nghỉ phép năm"})
    assert search.json()["results"] == []


def test_deleting_twice_is_204(client: TestClient) -> None:
    doc_id = upload(client, STAFF).body["document"]["id"]
    client.delete(f"/v1/documents/{doc_id}", headers=STAFF)

    response = client.delete(f"/v1/documents/{doc_id}", headers=STAFF)

    assert response.status_code == 204


def test_deleted_document_cannot_get_a_new_version(client: TestClient) -> None:
    doc_id = upload(client, STAFF).body["document"]["id"]
    client.delete(f"/v1/documents/{doc_id}", headers=STAFF)

    result = upload(client, STAFF, filename="x.md", data=b"# T\n\ntext", document_id=doc_id)

    assert_error(result, 404, "document_not_found")


class _LosesVersionRace(InMemoryDocumentStore):
    """Another request created the same version between our read and our insert."""

    async def add_document(self, document: Document) -> None:
        if document.version > 1:
            raise DocumentAlreadyExistsError(f"{document.id} v{document.version} exists")
        await super().add_document(document)


def test_concurrent_new_version_upload_is_409() -> None:
    services = make_services(_LosesVersionRace())
    with TestClient(create_app(make_settings(), services=services)) as racing:
        doc_id = upload(racing, STAFF).body["document"]["id"]

        result = upload(racing, STAFF, filename="x.md", data=b"# T\n\ntext", document_id=doc_id)

    assert_error(result, 409, "document_exists")


# --- access control ------------------------------------------------------------------


def test_restricted_document_is_invisible_to_other_groups_and_tenants(client: TestClient) -> None:
    doc_id = upload(client, HR, groups="hr").body["document"]["id"]

    for headers in (STAFF, OTHER_TENANT):
        assert client.get(f"/v1/documents/{doc_id}", headers=headers).status_code == 404
        assert client.get(f"/v1/documents/{doc_id}/chunks", headers=headers).status_code == 404
        search = client.post("/v1/search", headers=headers, json={"query": "nghỉ phép năm"})
        assert search.json()["results"] == []
    assert client.get(f"/v1/documents/{doc_id}", headers=HR).status_code == 200


def test_cannot_share_with_a_group_you_do_not_belong_to(client: TestClient) -> None:
    assert_error(upload(client, STAFF, groups="hr"), 403, "forbidden")


def test_cannot_version_a_document_you_cannot_read(client: TestClient) -> None:
    doc_id = upload(client, HR, groups="hr").body["document"]["id"]

    result = upload(client, STAFF, filename="x.md", data=b"# T\n\ntext", document_id=doc_id)

    assert_error(result, 404, "document_not_found")


def test_cannot_delete_a_document_you_cannot_read(client: TestClient) -> None:
    doc_id = upload(client, HR, groups="hr").body["document"]["id"]

    response = client.delete(f"/v1/documents/{doc_id}", headers=STAFF)

    assert response.status_code == 404
    assert response.json()["error"]["category"] == "document_not_found"
    assert client.get(f"/v1/documents/{doc_id}", headers=HR).status_code == 200


@pytest.mark.parametrize(
    "headers",
    [{}, {"x-tenant-id": TENANT}, {"x-tenant-id": "Bad Tenant!", "x-user-id": "u"}],
    ids=["none", "no-user", "invalid-tenant"],
)
def test_missing_or_invalid_identity_is_401(client: TestClient, headers: dict[str, str]) -> None:
    response = client.post("/v1/search", headers=headers, json={"query": "x"})

    assert response.status_code == 401
    assert response.json()["error"]["category"] == "unauthenticated"


# --- input errors --------------------------------------------------------------------


def test_corrupt_upload_is_422_with_category(client: TestClient) -> None:
    assert_error(upload(client, STAFF, data=b"%PDF-1.7 broken"), 422, "corrupt_document")


def test_unsupported_format_is_415(client: TestClient) -> None:
    result = upload(client, STAFF, data=b"\x89PNG\r\n\x1a\n" + b"\0" * 32, filename="a.png")

    assert_error(result, 415, "unsupported_format")


def test_oversized_upload_is_413(client: TestClient) -> None:
    assert_error(
        upload(client, STAFF, data=b"a" * (MAX_UPLOAD + 1), filename="a.txt"),
        413,
        "document_too_large",
    )


def test_missing_file_is_422_invalid_request(client: TestClient) -> None:
    response = client.post("/v1/documents", headers=STAFF, data={"allowed_groups": "all-staff"})

    assert response.status_code == 422
    assert response.json()["error"]["category"] == "invalid_request"


def test_query_without_words_is_422(client: TestClient) -> None:
    response = client.post("/v1/search", headers=STAFF, json={"query": "?!"})

    assert response.status_code == 422
    assert response.json()["error"]["category"] == "invalid_query"


def test_unknown_route_uses_error_shape(client: TestClient) -> None:
    response = client.get("/v1/nope", headers=STAFF)

    assert response.status_code == 404
    assert response.json()["error"]["category"] == "not_found"


def test_endpoints_return_503_until_services_are_wired() -> None:
    with TestClient(create_app(make_settings())) as bare:
        response = bare.post("/v1/search", headers=STAFF, json={"query": "x"})

    assert response.status_code == 503
    assert response.json()["error"]["category"] == "service_unavailable"


# --- dev-only settings guard ---------------------------------------------------------


@pytest.mark.parametrize("environment", [Environment.DEV, Environment.PROD])
def test_dev_identity_and_hashing_embedder_are_refused_when_deployed(
    environment: Environment,
) -> None:
    with pytest.raises(ValidationError, match="dev-headers"):
        make_settings(environment=environment)
