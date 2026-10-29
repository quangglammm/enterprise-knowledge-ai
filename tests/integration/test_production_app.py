"""The production composition root against a real database."""

import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from enterprise_knowledge.api.app import create_production_app
from enterprise_knowledge.config import Environment, Settings
from enterprise_knowledge.infrastructure.postgres.store import SchemaMismatchError
from tests.contract.conftest import reset_database
from tests.unit.ingestion.conftest import fixture_bytes

pytestmark = pytest.mark.integration


def settings_for(url: str, **overrides: object) -> Settings:
    values: dict[str, object] = {
        "environment": Environment.TEST,
        "database_url": SecretStr(url),
    }
    values.update(overrides)
    return Settings.model_validate(values)


def test_readiness_reports_database(postgres_url: str) -> None:
    app = create_production_app(settings_for(postgres_url))

    with TestClient(app) as client:  # the context manager runs startup and shutdown
        response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "checks": {"database": "ok"}}


def test_startup_fails_fast_on_wrong_embedding_dimension(postgres_url: str) -> None:
    app = create_production_app(settings_for(postgres_url, embedding_dimension=768))

    with pytest.raises(SchemaMismatchError), TestClient(app):
        pass


def test_upload_then_search_end_to_end(postgres_url: str, tmp_path: Path) -> None:
    """The v0.1 vertical slice: upload -> parse -> chunk -> embed -> persist -> search."""
    asyncio.run(reset_database(postgres_url))
    app = create_production_app(settings_for(postgres_url, blob_dir=tmp_path))
    headers = {"x-tenant-id": "bamboo-harbor", "x-user-id": "an", "x-user-groups": "all-staff"}

    with TestClient(app) as client:
        created = client.post(
            "/v1/documents",
            headers=headers,
            files={"file": ("leave.pdf", fixture_bytes("leave-policy-vi.pdf"))},
            data={"allowed_groups": "all-staff"},
        )
        doc_id = created.json()["document"]["id"]
        results = client.post(
            "/v1/search", headers=headers, json={"query": "số ngày nghỉ phép năm", "k": 3}
        ).json()["results"]
        chunks = client.get(f"/v1/documents/{doc_id}/chunks", headers=headers).json()

    assert created.status_code == 201
    assert results[0]["document_id"] == doc_id
    assert len(chunks) == created.json()["chunk_count"]
    assert (tmp_path / "bamboo-harbor" / doc_id / "v1").read_bytes()[:5] == b"%PDF-"


def test_delete_removes_document_and_files_end_to_end(postgres_url: str, tmp_path: Path) -> None:
    asyncio.run(reset_database(postgres_url))
    app = create_production_app(settings_for(postgres_url, blob_dir=tmp_path))
    headers = {"x-tenant-id": "bamboo-harbor", "x-user-id": "an", "x-user-groups": "all-staff"}

    with TestClient(app) as client:
        doc_id = client.post(
            "/v1/documents",
            headers=headers,
            files={"file": ("leave.pdf", fixture_bytes("leave-policy-vi.pdf"))},
            data={"allowed_groups": "all-staff"},
        ).json()["document"]["id"]
        client.post(
            "/v1/documents",
            headers=headers,
            files={"file": ("onboarding.md", fixture_bytes("onboarding-vi.md"))},
            data={"allowed_groups": "all-staff", "document_id": doc_id},
        )
        deleted = client.delete(f"/v1/documents/{doc_id}", headers=headers)
        results = client.post(
            "/v1/search", headers=headers, json={"query": "nghỉ phép", "k": 5}
        ).json()["results"]
        lookup = client.get(f"/v1/documents/{doc_id}", headers=headers)

    assert deleted.status_code == 204
    assert results == []
    assert lookup.status_code == 404
    assert list((tmp_path / "bamboo-harbor" / doc_id).iterdir()) == []
