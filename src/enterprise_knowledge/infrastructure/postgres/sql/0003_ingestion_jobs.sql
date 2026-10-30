-- 0003: ingestion jobs and the Postgres job queue (JOB-01, ADR-0016).
-- The queue has SQS semantics: a received message is leased (available_at moves into the
-- future) and is delivered again unless acked before the lease ends. Week 8 replaces the
-- queue table with SQS behind the same port; ingestion_jobs stays.

CREATE TABLE ingestion_jobs (
    id               text        PRIMARY KEY,
    tenant_id        text        NOT NULL,
    document_id      text        NOT NULL,
    document_version integer     NOT NULL CHECK (document_version >= 1),
    status           text        NOT NULL
                     CHECK (status IN ('queued', 'running', 'succeeded', 'failed')),
    attempts         integer     NOT NULL CHECK (attempts >= 0),
    max_attempts     integer     NOT NULL CHECK (max_attempts >= 1),
    error_category   text,
    use_parsed_title boolean     NOT NULL,
    created_at       timestamptz NOT NULL,
    updated_at       timestamptz NOT NULL,
    CHECK (status <> 'failed' OR error_category IS NOT NULL)
);

CREATE INDEX ingestion_jobs_document_idx
    ON ingestion_jobs (tenant_id, document_id, document_version, created_at);

CREATE TABLE job_queue (
    id           bigserial   PRIMARY KEY,
    job_id       text        NOT NULL,
    available_at timestamptz NOT NULL,
    deliveries   integer     NOT NULL DEFAULT 0,
    receipt      text        UNIQUE
);

CREATE INDEX job_queue_available_idx ON job_queue (available_at, id);
