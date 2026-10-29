# Enterprise Knowledge AI

A document-grounded knowledge assistant. It ingests enterprise documents asynchronously, answers questions with verifiable citations, abstains when evidence is insufficient, routes complex questions through a bounded agent workflow, and measures answer quality, latency, reliability and cost against a versioned benchmark.

**Stack:** Python 3.12 · FastAPI · PostgreSQL + pgvector · FPT AI Marketplace (LLM and Vietnamese embeddings) · AWS for deployment (S3, SQS, ECS Fargate, CDK) · OpenTelemetry

**Corpus:** bilingual Vietnamese and English documents from a fictional company, with tenants, access groups and document versions.

> Status: **v0.1 (Week 1, foundation).** Documents can be uploaded, parsed, chunked, indexed in Postgres and searched with access control. Embeddings come from a development-only hashing embedder until the FPT adapter lands in Week 3, so search is lexical, not semantic; there is no answer generation yet. See [the roadmap](#roadmap) and the full [implementation plan](docs/implementation-plan.md).

## Quick start

Prerequisites: [uv](https://docs.astral.sh/uv/) and Docker.

```bash
git clone https://github.com/quangglammm/enterprise-knowledge-ai.git
cd enterprise-knowledge-ai
cp .env.example .env

uv sync                       # installs exact versions from uv.lock
docker compose up -d postgres # local Postgres + pgvector
uv run eka-migrate            # apply database migrations
uv run eka-api                # http://127.0.0.1:8000/docs
```

Or run everything in containers:

```bash
docker compose up --build      # postgres, then migrations, then the API
curl -i http://localhost:8000/health/ready
```

## Development commands

| Task | Command |
| --- | --- |
| Format | `uv run ruff format .` |
| Lint | `uv run ruff check .` |
| Type check | `uv run mypy src tests` |
| Architecture contracts | `uv run lint-imports` |
| Unit tests | `uv run pytest` |
| Integration tests | `docker compose up -d postgres` then `EKA_TEST_DATABASE_URL=postgresql://eka:eka@localhost:5432/eka_test uv run pytest -m integration` |
| Apply migrations | `uv run eka-migrate` |
| Retrieval benchmark | `uv run python scripts/run_benchmark.py --database-url postgresql://eka:eka@localhost:5432/eka_test` (wipes that database; add `--embedding fpt` for real retrieval, paid) |
| Add a dependency | `uv add <pkg>` (dev: `uv add --dev <pkg>`) |

CI runs the same checks on every pull request (`.github/workflows/ci.yml`).

## Working with Claude Code

The repository ships its own Claude Code setup, loaded automatically when you run `claude` from the repo root:

| Path | Purpose |
| --- | --- |
| `CLAUDE.md` | Project context, commands, architecture boundaries, git conventions |
| `.claude/rules/` | Python, testing, domain, API and GenAI-safety rules, scoped to matching paths |
| `.claude/skills/` | `/implement <ID>`, `/check`, `/review-code`, `/adr <title>`, `/commit` |
| `.claude/hooks/` | Auto-format and lint edited Python files; block non-conventional or attributed commit messages |
| `.claude/settings.json` | Shared permissions (deny `.env` reads and `uv.lock` edits, ask before `git push`) and hooks |

Personal overrides go in `CLAUDE.local.md` and `.claude/settings.local.json` (both gitignored).

## Configuration

All settings are environment variables prefixed with `EKA_`; see [`.env.example`](.env.example). Required values (currently `EKA_DATABASE_URL`) have no default, so the process fails at startup with a validation error naming the missing variable. Secrets are never committed: use `.env` locally and a secret manager when deployed.

Model providers (ADR-0010). By default everything runs offline: the dev-only hashing embedder and no chat model, so `/v1/answers` returns `503`. To use FPT AI Marketplace, set in `.env`:

| Variable | Purpose |
| --- | --- |
| `EKA_LLM_API_KEY`, `EKA_LLM_MODEL` | Enables `/v1/answers` with that chat model. The ADR-0004 model trial chose `Llama-3.3-70B-Instruct`; rerun it with `uv run python scripts/model_trial.py` (paid calls). |
| `EKA_LLM_JSON_MODE` | Sends `response_format: json_object`; leave `false` until the trial confirms FPT supports it. |
| `EKA_EMBEDDING_PROVIDER=fpt`, `EKA_EMBEDDING_API_KEY` | Real embeddings (`Vietnamese_Embedding`, 1024 dimensions). Changing provider or model needs a re-upload of documents. |
| `EKA_ANSWER_TOP_K`, `EKA_ANSWER_MIN_SCORE`, `EKA_ANSWER_TIMEOUT_SECONDS` | Retrieval depth, evidence score gate and per-answer deadline. |

Tests and CI never call a model provider.

## API

| Endpoint | Purpose |
| --- | --- |
| `GET /health/live` | Process is running. Never checks dependencies. |
| `GET /health/ready` | Instance can serve traffic. Checks the database; `503` if any check fails. |
| `POST /v1/documents` | Upload a file (`multipart/form-data`: `file`, `allowed_groups`, optional `title`, optional `document_id` for a new version). `201` when indexed, `200` when identical content is already indexed. |
| `GET /v1/documents/{id}` | Current version's metadata and status. `404` once deleted. |
| `GET /v1/documents/{id}/chunks` | Chunks of the current (or `?version=`) version, with page, section and character offsets. Superseded versions have no chunks (ADR-0008). |
| `DELETE /v1/documents/{id}` | Remove every version from search and storage. `204`, also when already deleted. |
| `POST /v1/search` | `{"query": "...", "k": 5}` returns access-checked evidence. |
| `POST /v1/answers` | `{"question": "..."}` returns an answer with validated citations, or `status: insufficient_evidence`. Model failures are `502`/`504`. Provider failures are `502`, or `503` when throttled. Returns `503` when no chat model is configured (`EKA_LLM_API_KEY`). |

Interactive docs are at `/docs` when the API runs.

**Identity (development only).** Requests identify the caller with `X-Tenant-ID`, `X-User-ID` and `X-User-Groups` (comma-separated). Anyone can claim any identity this way, so the settings refuse it outside local and test environments; real authentication is SEC-01. Uploaders may only share with groups they belong to, and documents a caller cannot read return `404`, the same as missing ones.

```bash
H='-H X-Tenant-ID:bamboo-harbor -H X-User-ID:an -H X-User-Groups:all-staff'
curl -s $H -F file=@datasets/fixtures/leave-policy-vi.pdf -F allowed_groups=all-staff \
  http://localhost:8000/v1/documents
curl -s $H -H 'Content-Type: application/json' \
  -d '{"query": "số ngày nghỉ phép năm", "k": 3}' http://localhost:8000/v1/search
```

**Errors** always have the same shape, with a stable category and the request ID that also appears in the logs:

```json
{"error": {"category": "corrupt_document", "message": "PDF could not be read", "request_id": "..."}}
```

Every response carries an `X-Request-ID` header. A caller-supplied ID is reused if it is safe (`[A-Za-z0-9._-]{1,64}`); otherwise a new one is generated.

## Repository layout

```
src/enterprise_knowledge/
  domain/         models, access policy, job state machine, ports (no SDK imports)
  ingestion/      format detection, parsing, normalization, chunking, IngestDocument and DeleteDocument use cases
  retrieval/      SearchKnowledge use case
  generation/     AnswerQuestion and GenerateAnswer use cases, versioned prompt, answer parsing and citation checks
  evaluation/     retrieval benchmark, Recall@k and MRR, model trial scoring
  infrastructure/ adapters: Postgres store and vector search, migrations, blob store, FPT chat and embeddings, dev embedder
  api/            HTTP layer only (routes, middleware, app factory)
  observability/  structured logging, later tracing and metrics
  config.py       typed settings
tests/
  unit/           fast tests, no external services
  contract/       behavior every port implementation must have (fake and Postgres)
  integration/    Postgres-specific tests (marked `integration`, need a database)
  fakes/          in-memory implementations of the ports
  architecture/   import-linter contracts run as a test
datasets/
  fixtures/       small synthetic bilingual documents for parser tests
  corpus/v1/      bilingual Bamboo Harbor corpus (21 documents, 2 tenants) and its manifest
  benchmark/v1/   50 labelled retrieval questions (ADR-0011)
  model_trial/    versioned grounded-answer cases for the ADR-0004 model trial
scripts/          fixtures, benchmark builder and runner, chunk viewer, FPT smoke test, model trial
docs/
  adr/            architecture decision records
  evaluation/     recorded trial and benchmark results (no answer text)
```

More packages (`agents`, `worker`) are added when their first feature lands, rather than as empty folders.

## Roadmap

| Week | Focus | Milestone |
| --- | --- | --- |
| 1 | Foundation | Local API starts reproducibly; CI runs lint and tests |
| 2 | Ingestion and ETL | A document is parsed, chunked and inspectable |
| 3 | Baseline RAG | Cited answers; abstention on unsupported questions |
| 4 | Evaluation | Baseline report plus two comparison experiments |
| 5 | Async ingestion | Reliable worker under duplicate events and failures |
| 6 | Agentic workflow | Bounded workflow for complex questions only |
| 7 | AWS deployment | Endpoint on ECS Fargate with a demo dataset |
| 8 | AWS managed services | S3 → SQS → worker → FPT models end to end in AWS |
| 9 | Reliability and security | Tracing, injection tests, cost and CI regression gates |
| 10 | Case study | Docs, benchmark write-up, demo, teardown |

## Plan and architecture decisions

- [Implementation plan](docs/implementation-plan.md)
- [ADR-0001: Foundation stack and repository structure](docs/adr/0001-foundation-stack.md)
- [ADR-0002: Enforced layered (clean) architecture](docs/adr/0002-enforced-layered-architecture.md)
- [ADR-0003: Access control model](docs/adr/0003-access-control-model.md)
- [ADR-0004: Model and embedding providers](docs/adr/0004-model-and-embedding-providers.md)
- [ADR-0005: Bilingual demo corpus](docs/adr/0005-bilingual-demo-corpus.md)
- [ADR-0006: Document parsing and chunking](docs/adr/0006-document-parsing-and-chunking.md)
- [ADR-0007: Postgres persistence and vector search](docs/adr/0007-postgres-persistence.md)
- [ADR-0008: Document lifecycle: superseded versions and deletion](docs/adr/0008-document-lifecycle.md)
- [ADR-0009: Grounded answer generation and citation validation](docs/adr/0009-grounded-answer-generation.md)
- [ADR-0010: FPT model adapters: transport, retries and errors](docs/adr/0010-fpt-model-adapters.md)
- [ADR-0011: Benchmark v1: corpus, chunk-ID labels and retrieval metrics](docs/adr/0011-benchmark-v1.md)

## Data

The project uses only synthetic or public documents. No confidential material is stored in this repository.
