"""JOB-01: submitting an upload as a job, and processing it in the worker."""

from datetime import UTC, datetime

import pytest

from enterprise_knowledge.domain.documents import ContentType, DocumentStatus, Language
from enterprise_knowledge.domain.errors import DocumentNotFoundError, ModelRateLimitedError
from enterprise_knowledge.domain.ids import DocumentId, JobId
from enterprise_knowledge.domain.jobs import IngestionJob, JobStatus
from enterprise_knowledge.ingestion.errors import (
    DocumentTooLargeError,
    EmptyDocumentError,
    UnsupportedFormatError,
)
from enterprise_knowledge.ingestion.indexing import blob_key
from enterprise_knowledge.ingestion.jobs import ProcessIngestionJob, SubmitDocument
from enterprise_knowledge.ingestion.limits import IngestionLimits
from tests.factories import TENANT, make_policy, make_principal
from tests.fakes.blob_store import InMemoryBlobStore
from tests.fakes.document_store import InMemoryDocumentStore
from tests.fakes.embedder import HashEmbedder
from tests.fakes.job_store import InMemoryJobStore
from tests.fakes.queue import InMemoryJobQueue
from tests.unit.ingestion.conftest import fixture_bytes

T0 = datetime(2026, 10, 30, tzinfo=UTC)
PDF = fixture_bytes("leave-policy-vi.pdf")
MARKDOWN = fixture_bytes("onboarding-vi.md")


class JobHarness:
    def __init__(self, *, max_attempts: int = 3, max_bytes: int | None = None) -> None:
        self.store = InMemoryDocumentStore()
        self.blobs = InMemoryBlobStore()
        self.embedder = HashEmbedder()
        self.jobs = InMemoryJobStore()
        self.queue = InMemoryJobQueue()
        ids = iter(f"doc-{i}" for i in range(1, 100))
        job_ids = iter(f"job-{i}" for i in range(1, 100))
        limits = IngestionLimits(max_bytes=max_bytes) if max_bytes else IngestionLimits()
        self.submit = SubmitDocument(
            documents=self.store,
            jobs=self.jobs,
            queue=self.queue,
            blobs=self.blobs,
            max_attempts=max_attempts,
            limits=limits,
            clock=lambda: T0,
            new_document_id=lambda: DocumentId(next(ids)),
            new_job_id=lambda: JobId(next(job_ids)),
        )
        self.process = ProcessIngestionJob(
            documents=self.store,
            jobs=self.jobs,
            blobs=self.blobs,
            embedder=self.embedder,
            clock=lambda: T0,
        )

    async def search(self, query: str) -> list[str]:
        hits = await self.store.search(
            make_principal(TENANT),
            await self.embedder.embed_query(query),
            k=5,
            embedding_model=self.embedder.model,
        )
        return [h.document_id for h in hits]


@pytest.fixture
def jh() -> JobHarness:
    return JobHarness()


# --- submit -----------------------------------------------------------------------------


async def test_submit_stores_a_pending_version_and_queues_a_job(jh: JobHarness) -> None:
    result = await jh.submit(data=PDF, filename="leave.pdf", access=make_policy())

    document, job = result.document, result.job
    assert job is not None
    assert not result.duplicate
    assert (document.status, document.version, document.language) == (
        DocumentStatus.PENDING,
        1,
        Language.UNKNOWN,
    )
    assert document.content_type is ContentType.PDF
    assert (job.status, job.attempts, job.document_id) == (JobStatus.QUEUED, 0, document.id)
    assert await jh.blobs.get(blob_key(TENANT, document.id, 1)) == PDF
    [message] = await jh.queue.receive(max_messages=10, wait_seconds=0)
    assert message.job_id == job.id
    assert jh.embedder.calls == 0  # parsing and embedding are the worker's job


@pytest.mark.parametrize(
    ("data", "filename", "error"),
    [
        (b"", "empty.md", EmptyDocumentError),
        (b"\x00\x01binary", "tool.exe", UnsupportedFormatError),
        (b"x" * 2048, "big.md", DocumentTooLargeError),
    ],
    ids=["empty", "unsupported", "too-large"],
)
async def test_rejected_upload_stores_nothing(
    data: bytes, filename: str, error: type[Exception]
) -> None:
    jh = JobHarness(max_bytes=1024)

    with pytest.raises(error):
        await jh.submit(data=data, filename=filename, access=make_policy())

    assert await jh.store.get_document(TENANT, DocumentId("doc-1")) is None
    assert jh.queue.depth == 0


async def test_identical_indexed_upload_is_a_duplicate_without_a_job(jh: JobHarness) -> None:
    first = await jh.submit(data=PDF, filename="leave.pdf", access=make_policy())
    assert first.job is not None
    await jh.process(first.job.id)
    await jh.queue.ack((await jh.queue.receive(max_messages=1, wait_seconds=0))[0])

    again = await jh.submit(data=PDF, filename="copy.pdf", access=make_policy())

    assert again.duplicate
    assert again.job is None
    assert again.document.status is DocumentStatus.INDEXED
    assert jh.queue.depth == 0


async def test_identical_upload_still_pending_returns_the_running_job(jh: JobHarness) -> None:
    first = await jh.submit(data=PDF, filename="leave.pdf", access=make_policy())

    again = await jh.submit(data=PDF, filename="leave.pdf", access=make_policy())

    assert again.duplicate
    assert again.job == first.job
    assert jh.queue.depth == 1


async def test_new_version_and_uploader_title(jh: JobHarness) -> None:
    first = await jh.submit(data=PDF, filename="leave.pdf", access=make_policy())

    second = await jh.submit(
        data=MARKDOWN,
        filename="leave-2026.md",
        access=make_policy(),
        document_id=first.document.id,
        title="Quy chế 2026",
    )

    assert second.document.version == 2
    assert second.document.title == "Quy chế 2026"
    assert second.job is not None
    assert not second.job.use_parsed_title


async def test_new_version_of_a_missing_document_is_rejected(jh: JobHarness) -> None:
    with pytest.raises(DocumentNotFoundError):
        await jh.submit(
            data=PDF, filename="x.pdf", access=make_policy(), document_id=DocumentId("nope")
        )


# --- process ----------------------------------------------------------------------------


async def submitted(jh: JobHarness, data: bytes = PDF, filename: str = "leave.pdf") -> JobId:
    result = await jh.submit(data=data, filename=filename, access=make_policy())
    assert result.job is not None
    return result.job.id


async def test_processing_indexes_the_version_with_parsed_title_and_language(
    jh: JobHarness,
) -> None:
    job_id = await submitted(jh)

    job = await jh.process(job_id)

    assert job is not None
    assert (job.status, job.attempts) == (JobStatus.SUCCEEDED, 1)
    document = await jh.store.get_document(TENANT, DocumentId("doc-1"))
    assert document is not None
    assert document.status is DocumentStatus.INDEXED
    assert document.title == "Quy chế nghỉ phép"  # from the PDF, not the filename
    assert document.language is Language.VI
    assert "doc-1" in await jh.search("số ngày nghỉ phép năm")


async def test_uploader_title_is_kept_after_processing(jh: JobHarness) -> None:
    result = await jh.submit(data=PDF, filename="leave.pdf", access=make_policy(), title="Mine")
    assert result.job is not None

    await jh.process(result.job.id)

    document = await jh.store.get_document(TENANT, result.document.id)
    assert document is not None
    assert document.title == "Mine"


async def test_corrupt_document_fails_the_job_and_the_version_without_retry(
    jh: JobHarness,
) -> None:
    job_id = await submitted(jh, data=b"%PDF-1.7 truncated garbage", filename="bad.pdf")

    job = await jh.process(job_id)

    assert job is not None
    assert (job.status, job.error_category) == (JobStatus.FAILED, "corrupt_document")
    document = await jh.store.get_document(TENANT, DocumentId("doc-1"))
    assert document is not None
    assert (document.status, document.error_category) == (
        DocumentStatus.FAILED,
        "corrupt_document",
    )


async def test_transient_failure_requeues_then_succeeds(jh: JobHarness) -> None:
    job_id = await submitted(jh)
    jh.embedder.fail_with = ModelRateLimitedError("throttled")

    retry = await jh.process(job_id)
    pending = await jh.store.get_document_version(TENANT, DocumentId("doc-1"), 1)
    jh.embedder.fail_with = None
    done = await jh.process(job_id)

    assert retry is not None
    assert (retry.status, retry.attempts, retry.error_category) == (
        JobStatus.QUEUED,
        1,
        "model_rate_limited",
    )
    assert pending is not None
    assert pending.status is DocumentStatus.PENDING
    assert done is not None
    assert (done.status, done.attempts) == (JobStatus.SUCCEEDED, 2)


@pytest.mark.parametrize(
    "error", [ModelRateLimitedError("throttled"), RuntimeError("db hiccup")], ids=str
)
async def test_retries_are_bounded_and_end_in_a_recorded_failure(error: Exception) -> None:
    jh = JobHarness(max_attempts=2)
    job_id = await submitted(jh)
    jh.embedder.fail_with = error

    await jh.process(job_id)
    final = await jh.process(job_id)

    assert final is not None
    assert final.status is JobStatus.FAILED
    assert final.attempts == 2
    assert final.error_category in {"model_rate_limited", "indexing_error"}
    document = await jh.store.get_document_version(TENANT, DocumentId("doc-1"), 1)
    assert document is not None
    assert document.status is DocumentStatus.FAILED


async def test_duplicate_delivery_of_a_finished_job_is_a_no_op(jh: JobHarness) -> None:
    job_id = await submitted(jh)
    done = await jh.process(job_id)
    calls = jh.embedder.calls

    again = await jh.process(job_id)

    assert again == done
    assert jh.embedder.calls == calls


async def test_redelivery_after_a_crash_counts_the_interrupted_attempt(jh: JobHarness) -> None:
    job_id = await submitted(jh)
    stored = await jh.jobs.get_job(job_id)
    assert stored is not None
    await jh.jobs.update_job(stored.start(now=T0))  # a worker died while RUNNING

    job = await jh.process(job_id)

    assert job is not None
    assert (job.status, job.attempts) == (JobStatus.SUCCEEDED, 2)
    chunks = await jh.store.list_chunks(TENANT, DocumentId("doc-1"), 1)
    assert len(chunks) == len({c.chunk_index for c in chunks})  # no duplicates


async def test_interrupted_last_attempt_fails_the_job() -> None:
    jh = JobHarness(max_attempts=1)
    job_id = await submitted(jh)
    stored = await jh.jobs.get_job(job_id)
    assert stored is not None
    await jh.jobs.update_job(stored.start(now=T0))

    job = await jh.process(job_id)

    assert job is not None
    assert (job.status, job.error_category) == (JobStatus.FAILED, "worker_interrupted")
    assert jh.embedder.calls == 0


async def test_document_deleted_before_processing_fails_the_job(jh: JobHarness) -> None:
    job_id = await submitted(jh)
    await jh.store.delete_document(TENANT, DocumentId("doc-1"))

    job = await jh.process(job_id)

    assert job is not None
    assert (job.status, job.error_category) == (JobStatus.FAILED, "document_deleted")
    assert await jh.store.list_chunks(TENANT, DocumentId("doc-1"), 1) == []


async def test_unknown_job_is_ignored(jh: JobHarness) -> None:
    assert await jh.process(JobId("missing")) is None


def test_job_records_whether_to_use_the_parsed_title() -> None:
    job = IngestionJob.new(
        job_id=JobId("j"),
        tenant_id=TENANT,
        document_id=DocumentId("d"),
        document_version=1,
        max_attempts=3,
        now=T0,
    )

    assert job.use_parsed_title
