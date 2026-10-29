# ADR-0001: Foundation stack and repository structure

- Status: Accepted
- Date: 2026-10-29

## Context

The project must show production-oriented GenAI engineering: reproducible local development, testable layers, asynchronous ingestion, evaluation and an AWS deployment. The author has strong RAG experience and is new to AWS, so the local system must work end to end before cloud services are introduced, and every external dependency must be swappable for a deterministic fake in tests and CI.

## Decisions

1. **Python 3.12, FastAPI, Pydantic v2.** Async HTTP with typed request/response schemas. The same Pydantic models validate LLM structured output later.
2. **uv with `pyproject.toml` and a committed `uv.lock`.** One tool for environments, locking and running. Production and dev dependencies are separate groups. CI and the Docker image install with `--locked`, so a stale lockfile fails the build instead of silently resolving new versions.
3. **One installable package under `src/enterprise_knowledge/`**, including the API (`api/`) and, later, the worker. The original plan placed `apps/api` and `workers/` outside the package; that gives three import roots that only work when the current directory is on `sys.path`, and complicates mypy, pytest and the Docker image. Entry points are console scripts (`eka-api`, later `eka-worker`).
4. **Packages are created when their first feature lands**, not as an empty skeleton. The planned boundaries still hold: `domain/` (models and ports, no SDK imports), feature packages (`ingestion/`, `retrieval/`, `generation/`, `agents/`, `evaluation/`), `infrastructure/` (Postgres, S3, SQS and model-provider adapters), and `api/` / `worker/` as thin delivery layers.
5. **PostgreSQL + pgvector as the single store for metadata and vectors.** Runs locally in Docker Compose, supports transactional updates of document versions and their chunks, and supports hybrid retrieval via built-in full-text search. A managed vector store is evaluated later behind the same repository interface.
6. **Typed settings with `pydantic-settings`.** `EKA_`-prefixed environment variables; required settings have no default; secrets are `SecretStr`.
7. **Structured JSON logs with a request ID from day one.** A pure ASGI middleware sets a context variable; a log record factory stamps it onto every record. The same mechanism carries the job ID in the worker and is the anchor for OpenTelemetry traces later.
8. **Liveness and readiness are separate.** Liveness never checks dependencies, so a database outage does not cause ECS to restart healthy containers. Readiness runs registered checks and returns 503 with per-check status (details only in logs).

## Consequences

- A fresh clone needs only uv and Docker; `uv sync && uv run pytest` works without services.
- Adding a dependency always updates `uv.lock`, which must be committed.
- Readiness checks are registered when each dependency is introduced (Postgres in Week 1, queue in Week 5).
- Decisions still open, to be recorded in later ADRs: embedding model and vector dimension, chunk ACL model, demo corpus, agent workflow implementation, AWS network layout.
