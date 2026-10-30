"""The ingestion worker loop (JOB-01): receive, process, requeue with backoff, ack."""

import asyncio
from datetime import UTC, datetime

import pytest

from enterprise_knowledge.domain.ids import DocumentId, JobId, TenantId
from enterprise_knowledge.domain.jobs import IngestionJob
from enterprise_knowledge.observability.logging import request_id_var
from enterprise_knowledge.worker.loop import IngestionWorker, retry_delay
from tests.fakes.queue import InMemoryJobQueue

T0 = datetime(2026, 10, 30, tzinfo=UTC)


def job(job_id: JobId, *, attempts: int, queued: bool) -> IngestionJob:
    fresh = IngestionJob.new(
        job_id=job_id,
        tenant_id=TenantId("acme"),
        document_id=DocumentId("doc-1"),
        document_version=1,
        max_attempts=5,
        now=T0,
    )
    for _ in range(attempts):
        fresh = fresh.start(now=T0).fail(
            now=T0, error_category="model_rate_limited", retryable=True
        )
    return fresh if queued else fresh.start(now=T0).succeed(now=T0)


class ScriptedProcess:
    """Returns the scripted job state per call (or raises), recording the log context."""

    def __init__(self, *results: IngestionJob | Exception | None) -> None:
        self._results = list(results)
        self.contexts: list[str | None] = []

    async def __call__(self, job_id: JobId) -> IngestionJob | None:
        self.contexts.append(request_id_var.get())
        result = self._results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def worker(queue: InMemoryJobQueue, process: ScriptedProcess) -> IngestionWorker:
    return IngestionWorker(
        queue=queue,
        process=process,
        wait_seconds=0,
        retry_base_seconds=10,
        retry_max_seconds=300,
        jitter=lambda: 1.0,
    )


async def test_processed_message_is_acked() -> None:
    queue = InMemoryJobQueue()
    await queue.enqueue(JobId("j1"))
    process = ScriptedProcess(job(JobId("j1"), attempts=0, queued=False))

    handled = await worker(queue, process).run_once()

    assert handled == 1
    assert queue.depth == 0
    assert process.contexts == ["job-j1"]  # logs during processing carry the job ID


async def test_job_left_queued_is_requeued_with_backoff_and_acked() -> None:
    queue = InMemoryJobQueue()
    await queue.enqueue(JobId("j1"))
    process = ScriptedProcess(job(JobId("j1"), attempts=2, queued=True))

    await worker(queue, process).run_once()

    assert queue.enqueued[-1] == (JobId("j1"), 20.0)  # 10 s * 2^(2-1)
    assert queue.depth == 1  # the original was acked; only the delayed retry remains
    assert await queue.receive(max_messages=10, wait_seconds=0) == []


@pytest.mark.parametrize(
    ("attempts", "delay"), [(1, 10.0), (2, 20.0), (3, 40.0), (10, 300.0)], ids=str
)
def test_retry_delay_doubles_up_to_a_cap(attempts: int, delay: float) -> None:
    assert retry_delay(attempts, base_seconds=10, max_seconds=300, jitter=1.0) == delay


def test_jitter_only_shortens_the_delay() -> None:
    assert retry_delay(3, base_seconds=10, max_seconds=300, jitter=0.5) == 20.0


async def test_unexpected_error_leaves_the_message_for_redelivery() -> None:
    queue = InMemoryJobQueue(visibility_seconds=0)
    await queue.enqueue(JobId("j1"))
    process = ScriptedProcess(
        RuntimeError("database down"), job(JobId("j1"), attempts=0, queued=False)
    )
    loop = worker(queue, process)

    first = await loop.run_once()
    second = await loop.run_once()

    assert (first, second) == (1, 1)
    assert queue.depth == 0  # the redelivery succeeded and was acked


async def test_unknown_job_is_acked_and_dropped() -> None:
    queue = InMemoryJobQueue()
    await queue.enqueue(JobId("ghost"))

    await worker(queue, ScriptedProcess(None)).run_once()

    assert queue.depth == 0


async def test_run_stops_when_asked() -> None:
    queue = InMemoryJobQueue()
    stop = asyncio.Event()
    loop = IngestionWorker(
        queue=queue, process=ScriptedProcess(), wait_seconds=0.01, idle_sleep_seconds=0.01
    )

    task = asyncio.create_task(loop.run(stop))
    await asyncio.sleep(0.05)
    stop.set()

    await asyncio.wait_for(task, timeout=1)
