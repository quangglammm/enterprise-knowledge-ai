"""Behavior every JobRepository + JobQueue implementation must have (JOB-01, ADR-0016).

Runs against the in-memory fakes and, with ``-m integration``, against Postgres.
"""

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Protocol

import psycopg
import pytest

from enterprise_knowledge.domain.errors import JobAlreadyExistsError, JobNotFoundError
from enterprise_knowledge.domain.ids import DocumentId, JobId, TenantId
from enterprise_knowledge.domain.jobs import IngestionJob
from enterprise_knowledge.domain.ports import JobQueue, JobRepository
from enterprise_knowledge.infrastructure.postgres.jobs import PostgresJobStore
from tests.fakes.job_store import InMemoryJobStore
from tests.fakes.queue import InMemoryJobQueue

VISIBILITY = 0.3
T0 = datetime(2026, 10, 30, tzinfo=UTC)


class Jobs(JobRepository, JobQueue, Protocol):
    """Both ports; production uses one Postgres adapter for both."""


class _FakeJobs(InMemoryJobStore, InMemoryJobQueue):
    def __init__(self) -> None:
        InMemoryJobStore.__init__(self)
        InMemoryJobQueue.__init__(self, visibility_seconds=VISIBILITY)


@pytest.fixture(params=["memory", pytest.param("postgres", marks=pytest.mark.integration)])
async def jobs(request: pytest.FixtureRequest) -> AsyncIterator[Jobs]:
    if request.param == "memory":
        yield _FakeJobs()
        return
    url: str = request.getfixturevalue("postgres_url")
    async with await psycopg.AsyncConnection.connect(url, autocommit=True) as conn:
        await conn.execute("TRUNCATE ingestion_jobs, job_queue")
    store = await PostgresJobStore.connect(url, visibility_seconds=VISIBILITY)
    try:
        yield store
    finally:
        await store.close()


def job(
    job_id: str = "job-1", *, tenant: str = "acme", version: int = 1, at: int = 0
) -> IngestionJob:
    return IngestionJob.new(
        job_id=JobId(job_id),
        tenant_id=TenantId(tenant),
        document_id=DocumentId("doc-1"),
        document_version=version,
        max_attempts=3,
        now=T0 + timedelta(seconds=at),
        use_parsed_title=False,
    )


# --- jobs ----------------------------------------------------------------------------------


async def test_job_round_trips(jobs: Jobs) -> None:
    await jobs.add_job(job())

    assert await jobs.get_job(JobId("job-1")) == job()
    assert await jobs.get_job(JobId("missing")) is None


async def test_job_ids_are_unique(jobs: Jobs) -> None:
    await jobs.add_job(job())

    with pytest.raises(JobAlreadyExistsError):
        await jobs.add_job(job())


async def test_update_replaces_state_and_rejects_unknown_jobs(jobs: Jobs) -> None:
    await jobs.add_job(job())
    running = job().start(now=T0 + timedelta(seconds=1))

    await jobs.update_job(running)

    assert await jobs.get_job(JobId("job-1")) == running
    with pytest.raises(JobNotFoundError):
        await jobs.update_job(job("other"))


async def test_latest_job_for_a_version_is_tenant_scoped(jobs: Jobs) -> None:
    await jobs.add_job(job("old", at=0))
    await jobs.add_job(job("new", at=5))
    await jobs.add_job(job("v2", version=2, at=9))
    await jobs.add_job(job("foreign", tenant="other", at=10))

    latest = await jobs.latest_job_for(TenantId("acme"), DocumentId("doc-1"), 1)

    assert latest is not None
    assert latest.id == "new"
    assert await jobs.latest_job_for(TenantId("nobody"), DocumentId("doc-1"), 1) is None


# --- queue ---------------------------------------------------------------------------------


async def test_received_message_is_leased_until_acked(jobs: Jobs) -> None:
    await jobs.enqueue(JobId("job-1"))

    [message] = await jobs.receive(max_messages=10, wait_seconds=0)
    leased = await jobs.receive(max_messages=10, wait_seconds=0)
    await jobs.ack(message)
    await asyncio.sleep(VISIBILITY + 0.1)

    assert (message.job_id, message.delivery_count) == ("job-1", 1)
    assert leased == []
    assert await jobs.receive(max_messages=10, wait_seconds=0) == []


async def test_unacked_message_is_redelivered_after_its_lease(jobs: Jobs) -> None:
    await jobs.enqueue(JobId("job-1"))
    [first] = await jobs.receive(max_messages=10, wait_seconds=0)

    await asyncio.sleep(VISIBILITY + 0.1)
    [again] = await jobs.receive(max_messages=10, wait_seconds=0)
    await jobs.ack(first)  # stale receipt: a no-op

    assert again.job_id == "job-1"
    assert again.delivery_count == 2
    await asyncio.sleep(VISIBILITY + 0.1)
    [third] = await jobs.receive(max_messages=10, wait_seconds=0)
    assert third.delivery_count == 3


async def test_delayed_message_is_not_receivable_early(jobs: Jobs) -> None:
    await jobs.enqueue(JobId("later"), delay_seconds=60)
    await jobs.enqueue(JobId("now"))

    received = await jobs.receive(max_messages=10, wait_seconds=0)

    assert [m.job_id for m in received] == ["now"]


async def test_receive_respects_max_messages(jobs: Jobs) -> None:
    for i in range(3):
        await jobs.enqueue(JobId(f"job-{i}"))

    assert len(await jobs.receive(max_messages=2, wait_seconds=0)) == 2


async def test_concurrent_consumers_never_share_a_message(jobs: Jobs) -> None:
    for i in range(6):
        await jobs.enqueue(JobId(f"job-{i}"))

    first, second = await asyncio.gather(
        jobs.receive(max_messages=6, wait_seconds=0),
        jobs.receive(max_messages=6, wait_seconds=0),
    )

    receipts = [m.receipt for m in (*first, *second)]
    assert len(receipts) == len(set(receipts)) == 6
    assert {m.job_id for m in (*first, *second)} == {f"job-{i}" for i in range(6)}
