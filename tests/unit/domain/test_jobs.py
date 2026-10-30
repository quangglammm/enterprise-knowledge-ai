from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import pytest

from enterprise_knowledge.domain.errors import InvalidJobTransitionError
from enterprise_knowledge.domain.ids import DocumentId, JobId, TenantId
from enterprise_knowledge.domain.jobs import IngestionJob, JobStatus

T0 = datetime(2026, 1, 1, tzinfo=UTC)


def new_job(max_attempts: int = 3) -> IngestionJob:
    return IngestionJob.new(
        job_id=JobId("job-1"),
        tenant_id=TenantId("acme"),
        document_id=DocumentId("doc-1"),
        document_version=1,
        max_attempts=max_attempts,
        now=T0,
    )


def test_new_job_is_queued_with_no_attempts() -> None:
    job = new_job()

    assert job.status is JobStatus.QUEUED
    assert job.attempts == 0


def test_happy_path_queued_running_succeeded() -> None:
    job = new_job().start(now=T0 + timedelta(seconds=1))
    done = job.succeed(now=T0 + timedelta(seconds=2))

    assert job.status is JobStatus.RUNNING
    assert job.attempts == 1
    assert done.status is JobStatus.SUCCEEDED
    assert done.is_terminal
    assert done.updated_at == T0 + timedelta(seconds=2)


def test_retryable_failure_requeues_until_attempts_exhausted() -> None:
    job = new_job(max_attempts=2)

    first = job.start(now=T0).fail(now=T0, error_category="throttled", retryable=True)
    second = first.start(now=T0).fail(now=T0, error_category="throttled", retryable=True)

    assert first.status is JobStatus.QUEUED
    assert first.error_category == "throttled"
    assert second.status is JobStatus.FAILED
    assert second.attempts == 2
    assert second.is_terminal


def test_permanent_failure_fails_immediately() -> None:
    failed = new_job().start(now=T0).fail(now=T0, error_category="corrupt", retryable=False)

    assert failed.status is JobStatus.FAILED
    assert failed.attempts == 1


def test_success_clears_previous_error_category() -> None:
    retried = new_job().start(now=T0).fail(now=T0, error_category="throttled", retryable=True)

    done = retried.start(now=T0).succeed(now=T0)

    assert done.error_category is None


def job_in(status: JobStatus) -> IngestionJob:
    job = new_job()
    if status is JobStatus.QUEUED:
        return job
    running = job.start(now=T0)
    if status is JobStatus.RUNNING:
        return running
    if status is JobStatus.SUCCEEDED:
        return running.succeed(now=T0)
    return running.fail(now=T0, error_category="corrupt", retryable=False)


Action = Callable[[IngestionJob], IngestionJob]


def START(job: IngestionJob) -> IngestionJob:
    return job.start(now=T0)


def SUCCEED(job: IngestionJob) -> IngestionJob:
    return job.succeed(now=T0)


def FAIL(job: IngestionJob) -> IngestionJob:
    return job.fail(now=T0, error_category="x", retryable=True)


@pytest.mark.parametrize(
    ("status", "action"),
    [
        (JobStatus.QUEUED, SUCCEED),
        (JobStatus.QUEUED, FAIL),
        (JobStatus.RUNNING, START),
        (JobStatus.SUCCEEDED, START),
        (JobStatus.SUCCEEDED, FAIL),
        (JobStatus.FAILED, START),
        (JobStatus.FAILED, SUCCEED),
    ],
)
def test_invalid_transitions_raise(status: JobStatus, action: Action) -> None:
    job = job_in(status)

    with pytest.raises(InvalidJobTransitionError):
        action(job)


def test_max_attempts_must_be_positive() -> None:
    with pytest.raises(ValueError, match="max_attempts"):
        new_job(max_attempts=0)


def test_a_job_that_never_started_can_be_abandoned() -> None:
    abandoned = new_job().abandon(now=T0, error_category="enqueue_failed")

    assert (abandoned.status, abandoned.attempts) == (JobStatus.FAILED, 0)
    assert abandoned.error_category == "enqueue_failed"
    with pytest.raises(InvalidJobTransitionError):
        new_job().start(now=T0).abandon(now=T0, error_category="x")
