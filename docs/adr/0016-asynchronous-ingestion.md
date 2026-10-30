# ADR-0016: Asynchronous ingestion with a Postgres job queue

- Status: Accepted
- Date: 2026-10-30

## Context

JOB-01:
- the upload returns a job ID;
- its status can be queried;
- transient failures retry with limits;
- persistent failures are observable.

The API rules say long-running work is never done in the request. The plan puts SQS and a dead-letter queue in Week 8; until then the queue must work locally and in tests with no paid or cloud services.

Already in place: a job state machine, an at-least-once `JobQueue` port, and `retryable` flags on provider errors (ADR-0010).

## Options considered

Queue:
1. **A Postgres table leased with `FOR UPDATE SKIP LOCKED`**, with SQS semantics. Pros: no new infrastructure, and the job state and the queue sit in the same database. Cons: polling, and a second implementation once SQS lands.
2. **LocalStack SQS with a boto3 adapter now.** Closest to AWS, but it adds a container and an SDK now, and job state still needs a Postgres table, so there are two stores to keep consistent.

API split:
1. **Validate, store and enqueue in the request.** The size limit, format sniffing and checksum dedupe run synchronously; parsing happens in the worker.
2. **Also parse in the request.** Corrupt files keep their synchronous `422`, but PDF parsing is CPU-bound work inside the request.

## Decision

Queue option 1 and API split option 1.

- **Upload** (`SubmitDocument`):
  - `413`, `415` and empty-file errors stay synchronous.
  - An identical upload of an indexed version returns `200` with no job.
  - An identical upload that is still pending returns `202` with its existing job.
  - Otherwise the request stores the original and creates a pending version (language `und`) and a job, enqueues the job, and returns `202`.
  - If enqueueing fails, the job is abandoned (`QUEUED → FAILED`, `enqueue_failed`) and so is the version, so nothing waits forever.
- **Worker** (`ProcessIngestionJob`, `eka-worker`):
  - It parses, chunks and embeds the version, then indexes it with the parsed title (unless the uploader gave one) and language.
  - **Idempotent under at-least-once delivery:**
    - a finished job is skipped;
    - a job found `RUNNING` (its worker stopped mid-attempt) has that attempt recorded as `worker_interrupted`;
    - re-indexing replaces the version's chunks (ING-03).
  - **Failure classes:**
    - Retryable, up to `EKA_JOB_MAX_ATTEMPTS` (default 3): provider errors marked `retryable`, and unexpected errors (`indexing_error`).
    - Never retried: typed ingestion errors (`corrupt_document`, `empty_document`, and so on), `document_deleted`, and non-retryable provider errors.
    - A final failure marks the job and the version `failed` with the category. Logs carry IDs and categories only, and the worker's log records carry `job-<id>` as their request ID.
- **Loop:**
  - It acks a message only after the job's new state is stored.
  - A job left `QUEUED` is enqueued again with a delay: `min(max, base · 2^(attempts−1))` scaled by a jitter in [0.5, 1], with base `EKA_JOB_RETRY_BASE_SECONDS` = 10 and max `EKA_JOB_RETRY_MAX_SECONDS` = 300.
  - An error that escapes processing leaves the message unacked, so it is delivered again.
  - SIGTERM finishes the job in hand, then exits.
- **Postgres queue** (migration `0003`, `PostgresJobStore`):
  - `job_queue` rows are leased by moving `available_at` forward by `EKA_JOB_VISIBILITY_SECONDS` (default 300) under `SKIP LOCKED`. An unacked lease therefore ends in redelivery, with the delivery count incremented.
  - Times come from the database clock.
  - `ingestion_jobs` holds the job state and stays when Week 8 replaces the queue table with SQS behind the same port.
- **Status:** `GET /v1/jobs/{id}` shows a job to whoever may read its document version; otherwise it returns `404` (`job_not_found`), so job IDs cannot be used to probe for documents.
- `IngestDocument` (synchronous) stays for benchmarks and evaluation scripts. Both paths share `ingestion/indexing.py`.

## Consequences

- **API contract change:** an upload now returns `202` and a job, not `201` with chunk counts, so clients poll the job. A parse error appears on the job and the document, not as a `422`.
- **Verified:**
  - The contract tests run the same queue semantics on the fake and on Postgres: leases, redelivery, delays, `max_messages`, and no shared message between concurrent consumers.
  - An integration test runs three production workers on four uploads; each job succeeds exactly once.
  - `docker compose up` runs the worker as its own service.
- **No dead-letter queue yet.** A failed job stays queryable as `failed` in `ingestion_jobs`, which is the local dead-letter record; SQS's redrive policy and alarms are AWS-02 (Week 8).
- **Polling cost:** each idle worker issues one short query per `EKA_WORKER_WAIT_SECONDS` window. That is fine at this scale and moot with SQS long polling.
- **Visibility timeout:** it must exceed the slowest ingestion, or a slow job is processed twice. That is harmless, because processing is idempotent, but it is wasted work.
