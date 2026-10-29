# Enterprise Knowledge AI

A document-grounded knowledge assistant. It ingests enterprise documents asynchronously, answers questions with verifiable citations, abstains when evidence is insufficient, routes complex questions through a bounded agent workflow, and measures answer quality, latency, reliability and cost against a versioned benchmark.

**Stack:** Python 3.12 · FastAPI · PostgreSQL + pgvector · FPT AI Marketplace (LLM and Vietnamese embeddings) · AWS for deployment (S3, SQS, ECS Fargate, CDK) · OpenTelemetry

**Corpus:** bilingual Vietnamese and English documents from a fictional company, with tenants, access groups and document versions.

> Status: **v0.1 in progress (Week 1, foundation).** Only the API skeleton and health endpoints exist so far. See [the roadmap](#roadmap) and the full [implementation plan](docs/implementation-plan.md).

## Quick start

Prerequisites: [uv](https://docs.astral.sh/uv/) and Docker.

```bash
git clone https://github.com/quangglammm/enterprise-knowledge-ai.git
cd enterprise-knowledge-ai
cp .env.example .env

uv sync                       # installs exact versions from uv.lock
docker compose up -d postgres # local Postgres + pgvector
uv run eka-api                # http://127.0.0.1:8000/docs
```

Or run everything in containers:

```bash
docker compose up --build
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

## API

| Endpoint | Purpose |
| --- | --- |
| `GET /health/live` | Process is running. Never checks dependencies. |
| `GET /health/ready` | Instance can serve traffic. Runs dependency checks; `503` if any fail. |

Every response carries an `X-Request-ID` header. A caller-supplied ID is reused if it is safe (`[A-Za-z0-9._-]{1,64}`); otherwise a new one is generated. The same ID appears on every log line for that request.

## Repository layout

```
src/enterprise_knowledge/
  domain/         models, access policy, job state machine, ports (no SDK imports)
  api/            HTTP layer only (routes, middleware, app factory)
  observability/  structured logging, later tracing and metrics
  config.py       typed settings
tests/
  unit/           fast tests, no external services
  contract/       behavior every port implementation must have (fakes now, Postgres later)
  fakes/          in-memory implementations of the ports
  architecture/   import-linter contracts run as a test
docs/
  adr/            architecture decision records
```

More packages (`ingestion`, `retrieval`, `generation`, `agents`, `evaluation`, `worker`) are added when their first feature lands, rather than as empty folders.

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

## Data

The project uses only synthetic or public documents. No confidential material is stored in this repository.
