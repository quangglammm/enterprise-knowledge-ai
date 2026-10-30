"""The production composition root against a real database."""

import asyncio
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from enterprise_knowledge.api.app import create_production_app
from enterprise_knowledge.config import Environment, Settings
from enterprise_knowledge.infrastructure.postgres.store import SchemaMismatchError
from enterprise_knowledge.worker.app import build_worker
from enterprise_knowledge.worker.loop import IngestionWorker
from tests.contract.conftest import reset_database
from tests.unit.ingestion.conftest import fixture_bytes

pytestmark = pytest.mark.integration

STAFF = {"x-tenant-id": "bamboo-harbor", "x-user-id": "an", "x-user-groups": "all-staff"}


def settings_for(url: str, **overrides: object) -> Settings:
    values: dict[str, object] = {
        "environment": Environment.TEST,
        "database_url": SecretStr(url),
    }
    values.update(overrides)
    return Settings.model_validate(values)


async def drain(settings: Settings, *, workers: int = 1) -> None:
    """Run ``workers`` production workers side by side until the queue is empty."""
    async with AsyncExitStack() as stack:
        pool = [await build_worker(settings, stack) for _ in range(workers)]

        async def until_idle(worker: IngestionWorker) -> None:
            while await worker.run_once():
                pass

        await asyncio.gather(*(until_idle(w) for w in pool))


def reset(url: str) -> None:
    async def truncate() -> None:
        await reset_database(url)
        async with await psycopg.AsyncConnection.connect(url, autocommit=True) as conn:
            await conn.execute("TRUNCATE ingestion_jobs, job_queue")

    asyncio.run(truncate())


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


def upload(client: TestClient, name: str, data: bytes, **form: str) -> dict[str, Any]:
    response = client.post(
        "/v1/documents",
        headers=STAFF,
        files={"file": (name, data)},
        data={"allowed_groups": "all-staff", **form},
    )
    assert response.status_code == 202, response.text
    body: dict[str, Any] = response.json()
    return body


def test_upload_worker_search_end_to_end(postgres_url: str, tmp_path: Path) -> None:
    """API accepts the upload as a job; the worker parses, embeds and indexes it (JOB-01)."""
    reset(postgres_url)
    settings = settings_for(postgres_url, blob_dir=tmp_path, worker_wait_seconds=0)

    with TestClient(create_production_app(settings)) as client:
        accepted = upload(client, "leave.pdf", fixture_bytes("leave-policy-vi.pdf"))
        job_id = accepted["job"]["id"]
        doc_id = accepted["document"]["id"]
        before = client.post("/v1/search", headers=STAFF, json={"query": "nghỉ phép năm"})
        asyncio.run(drain(settings))
        job = client.get(f"/v1/jobs/{job_id}", headers=STAFF).json()
        results = client.post(
            "/v1/search", headers=STAFF, json={"query": "số ngày nghỉ phép năm", "k": 3}
        ).json()["results"]

    assert before.json()["results"] == []
    assert (job["status"], job["attempts"]) == ("succeeded", 1)
    assert results[0]["document_id"] == doc_id
    assert (tmp_path / "bamboo-harbor" / str(doc_id) / "v1").read_bytes()[:5] == b"%PDF-"


def test_corrupt_upload_fails_its_job_end_to_end(postgres_url: str, tmp_path: Path) -> None:
    reset(postgres_url)
    settings = settings_for(postgres_url, blob_dir=tmp_path, worker_wait_seconds=0)

    with TestClient(create_production_app(settings)) as client:
        job_id = upload(client, "bad.pdf", b"%PDF-1.7 broken")["job"]["id"]
        asyncio.run(drain(settings))
        job = client.get(f"/v1/jobs/{job_id}", headers=STAFF).json()

    assert (job["status"], job["error_category"], job["attempts"]) == (
        "failed",
        "corrupt_document",
        1,
    )


def test_concurrent_workers_process_each_job_once(postgres_url: str, tmp_path: Path) -> None:
    reset(postgres_url)
    settings = settings_for(postgres_url, blob_dir=tmp_path, worker_wait_seconds=0)
    files = [
        ("leave.pdf", fixture_bytes("leave-policy-vi.pdf")),
        ("onboarding.md", fixture_bytes("onboarding-vi.md")),
        ("handbook.html", fixture_bytes("handbook-mixed.html")),
        ("vpn.docx", fixture_bytes("vpn-runbook-en.docx")),
    ]

    with TestClient(create_production_app(settings)) as client:
        job_ids = [upload(client, name, data)["job"]["id"] for name, data in files]
        asyncio.run(drain(settings, workers=3))
        jobs = [client.get(f"/v1/jobs/{j}", headers=STAFF).json() for j in job_ids]

    assert [(j["status"], j["attempts"]) for j in jobs] == [("succeeded", 1)] * len(files)


def test_delete_removes_document_and_files_end_to_end(postgres_url: str, tmp_path: Path) -> None:
    reset(postgres_url)
    settings = settings_for(postgres_url, blob_dir=tmp_path, worker_wait_seconds=0)
    headers = STAFF

    with TestClient(create_production_app(settings)) as client:
        doc_id = upload(client, "leave.pdf", fixture_bytes("leave-policy-vi.pdf"))["document"]["id"]
        upload(client, "onboarding.md", fixture_bytes("onboarding-vi.md"), document_id=str(doc_id))
        asyncio.run(drain(settings))
        deleted = client.delete(f"/v1/documents/{doc_id}", headers=headers)
        results = client.post(
            "/v1/search", headers=headers, json={"query": "nghỉ phép", "k": 5}
        ).json()["results"]
        lookup = client.get(f"/v1/documents/{doc_id}", headers=headers)

    assert deleted.status_code == 204
    assert results == []
    assert lookup.status_code == 404
    assert list((tmp_path / "bamboo-harbor" / doc_id).iterdir()) == []


def test_answers_return_503_without_an_llm_key(postgres_url: str) -> None:
    app = create_production_app(settings_for(postgres_url))

    with TestClient(app) as client:
        response = client.post("/v1/answers", headers=STAFF, json={"question": "nghỉ phép?"})

    assert response.status_code == 503


def test_answers_are_wired_when_an_llm_key_is_configured(postgres_url: str) -> None:
    """With no documents the use case abstains before any model call, so no network."""
    asyncio.run(reset_database(postgres_url))
    app = create_production_app(
        settings_for(postgres_url, llm_api_key="sk-unused", llm_model="Llama-3.3-70B-Instruct")
    )

    with TestClient(app) as client:
        response = client.post("/v1/answers", headers=STAFF, json={"question": "nghỉ phép?"})

    assert response.status_code == 200
    assert response.json()["abstention_reason"] == "no_relevant_evidence"
