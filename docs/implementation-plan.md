# Enterprise Knowledge AI Platform: Implementation Plan

The target is a portfolio project that proves the ability to engineer, evaluate, deploy and operate a production-oriented GenAI application, not just build a chatbot.

The plan runs 10 weeks at roughly 12–16 hours per week, with an optional two-week polish phase. The central strategy is to build a working end-to-end product early, then progressively improve retrieval quality, the agent workflow and production characteristics.

> **Revisions:** where the implementation intentionally differs from this plan, see [Revisions to the original plan](#revisions-to-the-original-plan) at the end. Decisions are recorded as ADRs in [`docs/adr/`](adr/).

## 1. Project definition

**Enterprise Knowledge AI Platform** (Python · FastAPI · RAG · Agentic AI · FPT AI Marketplace · AWS)

A document-grounded knowledge assistant that processes enterprise documents asynchronously, answers questions with verifiable citations, uses bounded agent workflows for complex queries, and continuously measures answer quality, latency, reliability and cost.

### Definition of done

By the end of the core project, a reviewer should be able to:

- Run the application locally using Docker Compose.
- Upload documents and observe ingestion job status.
- Ask questions and receive answers with validated source citations.
- See the system abstain when evidence is insufficient.
- Compare direct RAG with a multi-step agent workflow.
- Run a reproducible evaluation benchmark.
- Deploy the service to AWS and inspect logs, metrics and traces.
- Run automated tests and a CI pipeline.
- Read architecture decisions, a deployment guide and a troubleshooting runbook.

The project uses synthetic or public documents, never confidential company material.

## 2. Architecture decisions

Each architectural choice should solve a requirement in the target job description rather than add technology for its own sake.

### Recommended architecture

| Layer | Components |
| --- | --- |
| Client / REST API | FastAPI · authentication · request validation |
| Ingestion path | S3 → SQS → worker → parsing and indexing |
| Query path | FastAPI → retrieval → answer or agent workflow |
| Shared AI and data services | FPT AI Marketplace models · vector search · PostgreSQL · evaluation |
| Operations and delivery | CloudWatch · OpenTelemetry · pytest · GitHub Actions · AWS CDK |

### Technology choices

| Component | Initial choice | Reason |
| --- | --- | --- |
| Backend | Python 3.12+ and FastAPI | Async APIs, type validation and clear service boundaries |
| Model access | FPT AI Marketplace through provider ports (ADR-0004) | Vietnamese-tuned embeddings and Vietnam data residency, without coupling business logic to one provider |
| Document storage | S3 in AWS; local filesystem or MinIO locally | Separates binary documents from application data |
| Job queue | SQS in AWS; local queue adapter or LocalStack for development | Asynchronous processing and retry handling |
| Vector retrieval | PostgreSQL with pgvector | Easy local development and reproducible testing |
| Managed vector search | OpenSearch Serverless as a later AWS milestone | Managed vector infrastructure (see revisions) |
| Application metadata | PostgreSQL | Documents, versions, jobs, users and evaluation records |
| Worker | Separate Python process/container | Keeps ingestion work out of API request handlers |
| Deployment | Docker locally; ECS Fargate on AWS | Consistent container-based execution |
| Infrastructure | AWS CDK with Python | Version-controlled, repeatable infrastructure |
| Observability | Structured JSON logs, OpenTelemetry and CloudWatch | Debugging, traces, metrics and operational monitoring |

PostgreSQL + pgvector gives a reliable local environment and a clear baseline. The vector repository can move to another store behind an interface; the final system does not need to operate two vector databases.

DynamoDB is not forced into the architecture. A small extension for idempotency records or workflow state is optional if its usefulness can be explained.

## 3. Ten-week roadmap

Each phase ends with a working deliverable, so the project stays demonstrable if work stops early.

| Week | Focus | Hours | Tasks | Milestone |
| --- | --- | --- | --- | --- |
| 1 | Foundation and architecture | 12–14 | Scope, user stories and acceptance criteria; repository, Python environment, Docker Compose and FastAPI skeleton; configuration, logging, linting and CI; architecture diagram and first ADR | Local API starts reproducibly; CI runs linting and tests |
| 2 | Document ingestion and ETL | 14–16 | PDF, DOCX and HTML parsers; normalized text and metadata; chunking, checksums and document versioning; persisted ingestion status and failure reasons | A document can be processed locally and its chunks inspected |
| 3 | Baseline RAG | 14–16 | Embeddings and pgvector; retrieval and metadata filters; grounded answer generation and citation validation; first 50 benchmark questions | End-to-end answers include valid citations and abstain on unsupported questions |
| 4 | Evaluation and retrieval improvements | 14–16 | Recall@k and MRR; answer-quality and citation-support evaluation; compare chunk sizes, top-k and hybrid retrieval; reproducible experiment configurations | Baseline evaluation report and at least two comparison experiments |
| 5 | Asynchronous ingestion | 14–16 | Separate API and worker processes; queued jobs, retry policies and idempotency; duplicate events and malformed documents; reprocessing and deletion tests | Background ingestion is reliable under duplicate events and recoverable failures |
| 6 | Agentic query workflow | 14–16 | Query routing and workflow state; evidence retrieval and verification steps; bounded iterations, timeouts and model calls; compare direct RAG and agent workflows | Complex questions use a controlled workflow; simple questions stay on direct RAG |
| 7 | AWS fundamentals and first deployment | 14–16 | IAM, S3, ECR, ECS and CloudWatch basics; containerize API and worker; deploy to ECS Fargate; secrets, networking and budget alerts | A deployed endpoint works with a controlled demo dataset |
| 8 | AWS ingestion and managed services | 14–16 | S3 events, SQS and dead-letter queue; FPT model calls from AWS with Secrets Manager; managed vector search if budget permits; retry handling and alarms | Cloud ingestion and query paths work end to end |
| 9 | Reliability, security and performance | 14–16 | Request tracing, metrics and structured error categories; access control, prompt injection and failure recovery tests; latency, token usage and cost; CI evaluation regression gates | Documented security boundaries and repeatable reliability tests |
| 10 | Portfolio and technical case study | 12–16 | README, architecture diagram and runbook; benchmark methodology and honest results; demo recording and trade-offs; AWS teardown and cost controls | A reviewer can run, understand, test and evaluate the project from its documentation |

### Scope protection

If AWS learning takes longer than expected, protect these first:

1. Working document ingestion.
2. Grounded RAG with valid citations.
3. A benchmark with reproducible results.
4. Automated tests and a local demo.
5. One working AWS deployment.

Defer a sophisticated frontend, multi-agent framework adoption, multiple vector databases, advanced OCR and elaborate dashboards. The local end-to-end system should work before heavy investment in cloud infrastructure.

## 4. Initial backlog with acceptance criteria

Track work as GitHub Issues with priority and milestone labels, ordered by dependency. Each issue gets a test plan, dependencies and an estimate, and should be completable in roughly 2–6 hours.

Priorities: **P0** required for the core product; **P1** important for the target role; **P2** optional enhancement.

| ID | Priority | Area | Title | Acceptance criteria |
| --- | --- | --- | --- | --- |
| PLAT-01 | P0 | Foundation | Create Python project skeleton | A fresh clone installs from the lockfile; the API starts locally; formatting, linting and tests run with documented commands. |
| PLAT-02 | P0 | Foundation | Add typed configuration and health endpoints | Missing required configuration fails clearly; secrets are not hardcoded; liveness and readiness endpoints return documented responses. |
| ING-01 | P0 | Ingestion | Parse supported document formats | PDF, DOCX and HTML fixtures produce normalized text and metadata; empty or malformed documents produce typed errors. |
| ING-02 | P0 | Ingestion | Implement chunking and source metadata | Each chunk has a stable ID, document version, chunk index and source location where available; output is deterministic for unchanged input. |
| ING-03 | P1 | Ingestion | Add document versions and idempotency | Reprocessing the same version does not duplicate chunks; changed content creates a new version; deletion removes stale indexed data. |
| RAG-01 | P0 | RAG | Implement vector retrieval | Queries return ranked chunks with source metadata; filters are applied before evidence reaches the model; empty results are handled. |
| RAG-02 | P0 | RAG | Generate validated, cited answers | Responses match a Pydantic schema; every citation resolves to retrieved evidence; insufficient evidence triggers abstention. |
| EVAL-01 | P0 | Evaluation | Create benchmark dataset and metrics | Dataset contains answerable, unanswerable and multi-document questions; Recall@k and MRR are calculated deterministically. |
| EVAL-02 | P1 | Evaluation | Add answer-quality evaluation | Faithfulness, citation support and correctness are measured separately; model and dataset versions are recorded for every run. |
| JOB-01 | P1 | Reliability | Move ingestion into background workers | Upload returns a job ID; status can be queried; transient failures retry with limits; persistent failures are observable. |
| AGENT-01 | P1 | Agents | Implement bounded query routing | Direct questions avoid unnecessary agent calls; complex questions follow a documented workflow; step limits and timeouts are enforced. |
| AGENT-02 | P1 | Agents | Verify evidence before final answers | Unsupported claims trigger a retry or abstention; agent outputs use typed schemas; invalid transitions are tested. |
| OBS-01 | P1 | Observability | Add correlated logs and traces | A request ID connects API, retrieval, model and workflow events; errors have stable categories; sensitive content is not logged by default. |
| AWS-01 | P1 | AWS | Deploy API and worker on Fargate | Infrastructure is reproducible from CDK; health checks, least-privilege roles and documented teardown instructions. |
| AWS-02 | P1 | AWS | Connect S3, SQS and the model provider | A document travels from upload to indexed content in AWS; retries, dead-letter handling and model errors are observable. |
| CI-01 | P0 | Quality | Build CI quality gates | Pull requests run linting, type checks and unit tests; integration tests are repeatable; benchmark regressions are reported. |
| SEC-01 | P1 | Security | Test authorization and prompt injection | Unauthorized users cannot retrieve restricted documents; retrieved instructions cannot override system policy or grant tool permissions. |

## 5. Repository structure

A single repository keeps the relationship between API, worker, evaluation suite and infrastructure easy to demonstrate. The current layout is described in the [README](../README.md) and [ADR-0001](adr/0001-foundation-stack.md).

### Clean architecture boundaries

- `domain/`: document, chunk, job and answer models; no AWS or LLM SDK dependencies.
- Feature packages (`ingestion/`, `retrieval/`, `generation/`, `agents/`): domain-specific workflows and their use cases.
- `infrastructure/`: implementations for S3, PostgreSQL, the FPT model API and vector search.
- `api/`: HTTP request/response handling only.
- `worker/`: background job entry point.
- `evaluation/`: offline benchmark runners and metric calculations.

Define interfaces for the model provider, document store, vector repository and job queue. Not every class needs an interface; use abstractions where they make testing, swapping infrastructure or controlling side effects easier.

### Development tooling

- uv with `pyproject.toml` and a committed lockfile.
- Ruff for formatting and linting; mypy (strict) for type checking.
- pytest and pytest-asyncio.
- Docker Compose for local services.
- GitHub Actions for pull-request checks.
- AWS CDK for infrastructure.

Use `.env` for local configuration, `.env.example` for documented variable names, and a secret manager for deployed credentials. Never commit real API keys or AWS credentials.

## 6. Testing strategy

Testing is a core product feature. RAG applications have failure modes conventional API tests cannot catch.

| Layer | Target | Scope |
| --- | --- | --- |
| 1. Unit | Fast, every commit | Parsers, normalization, chunk IDs, metadata validation, retry policies, citation resolution, deterministic metrics. External model calls mocked. |
| 2. Integration | Real component boundaries | Ingestion through persistence, vector retrieval, API serialization, worker retries and deletion. Local Postgres + pgvector, deterministic fake model providers. |
| 3. Security and resilience | Failure and trust boundaries | Unauthorized document access, prompt injection in retrieved text, malformed uploads, duplicate events, timeouts, model throttling, invalid model outputs, bounded agent loops. |
| 4. GenAI evaluation | Changes to prompts, retrieval or model config | Retrieval metrics, citation support, answer correctness, abstention, latency and estimated cost against a versioned benchmark. |

### Tests to implement early

| Test case | Expected behavior |
| --- | --- |
| Same file uploaded twice | No duplicate indexed chunks |
| Document updated | New version indexed; old version no longer returned as current |
| Empty or corrupt PDF | Typed ingestion failure; worker remains healthy |
| No relevant chunks | Clear abstention, not an invented answer |
| Citation references unknown chunk | Response rejected or regenerated |
| Model provider throttles request | Bounded retry; no unbounded loop |
| One agent step fails | Controlled workflow failure or safe fallback |
| Unauthorized query | Restricted documents never enter model context |
| Retrieved text contains malicious instructions | Content treated as untrusted evidence |
| New prompt causes benchmark regression | CI reports failure against agreed quality thresholds |

LLM output is not required to match a reference answer word for word. Semantic correctness, source support and task-specific requirements are evaluated separately.

### CI pipeline

1. Install locked dependencies
2. Ruff and type checking
3. Unit tests
4. Integration tests
5. Security and dependency checks
6. Optional benchmark regression suite
7. Build Docker image

Fast tests run on every pull request. Expensive, model-dependent benchmarks run on relevant changes or on a schedule. CI uses deterministic fake providers so ordinary changes need no paid model calls.

## 7. First sprint (Week 1)

Do not provision AWS services first. Build a small, tested skeleton that makes future components easy to add.

**Day 1: Repository and environment.** README, Python environment with lockfile, package structure and configuration, FastAPI with health and readiness endpoints, Ruff, type checking and pytest, Docker Compose and Dockerfile, GitHub Actions, first ADR. Acceptance: a fresh clone installs dependencies, starts the API and passes tests with documented commands.

**Day 2: Domain models and interfaces.** Independent of FastAPI, boto3 and model SDKs:

- `Document`: ID, filename, checksum, version, content type, processing status.
- `DocumentChunk`: ID, document version, chunk index, text, source location, metadata.
- `IngestionJob`: ID, status, attempt count, timestamps, error category.
- `RetrievedEvidence`: chunk ID, score, text, source metadata.
- `AnswerResponse`: answer, citations, insufficient-evidence status.

**Day 3: Parsing and chunking.** Deterministic parsers for a small set of PDF, DOCX and HTML fixtures: text normalization, stable source metadata, configurable chunk size and overlap, checksums for duplicate detection, typed errors for unsupported, corrupt or empty files. Unit tests before embeddings.

**Day 4: Persistence and local development.** PostgreSQL with pgvector in Docker Compose, migrations, repositories for document metadata and chunks. Verify: create a document record; store text and chunks; retrieve chunks by document ID and version; update status; delete obsolete indexed content.

**Day 5: First vertical slice.** `upload fixture → parse → chunk → persist → retrieve → inspect`, without an LLM. Tag `v0.1.0` and record remaining work as GitHub Issues.

## 8. AWS learning plan

Learn each concept immediately before using it.

| Order | AWS concept | Applied to the project |
| --- | --- | --- |
| 1 | IAM and AWS CLI | Local development access without hardcoded credentials |
| 2 | S3 | Store documents and generated artifacts |
| 3 | SQS and dead-letter queues | Asynchronous jobs and retry handling |
| 4 | ECR and ECS Fargate | Deploy containerized API and worker |
| 5 | Secrets Manager | Store the model provider API key; grant read access to the task role only |
| 6 | CloudWatch | Logs, service health and application metrics |
| 7 | CDK and IAM policies | Recreate the environment through code |
| 8 | OpenSearch Serverless | Managed vector retrieval, only if justified |

**Cost discipline:** set a budget alert before provisioning anything, check service pricing and quotas, and delete unused resources. Some managed services charge even with little traffic; validate the cost of OpenSearch Serverless and private-network resources for Fargate before choosing them.

## 9. Portfolio evidence

Prepare four technical case studies backed by real measurements:

1. **Retrieval quality:** baseline vs hybrid search or reranking on the same benchmark.
2. **Agent orchestration:** when a multi-step workflow improves an answer, and when it only adds latency or cost.
3. **Reliability:** how idempotency, bounded retries and dead-letter handling recover from failures.
4. **Production deployment:** how a request flows through AWS, how permissions are controlled, and how an error is diagnosed from logs and traces.

Do not invent performance improvements, describe an undeployed service as production-ready, or claim AWS experience not yet acquired.

## Revisions to the original plan

Changes made after review, with the reasoning. Each significant one gets an ADR.

1. **Tooling (done, ADR-0001).** uv with a lockfile from the first commit, instead of a `pip freeze` bootstrap.
2. **Layout (done, ADR-0001).** The API and worker live inside the `enterprise_knowledge` package instead of top-level `apps/` and `workers/`, giving one import root. Packages are created when their first feature lands.
3. **Access control moves to Week 2.** `tenant_id` and ACL fields are part of the chunk schema from the start, because SEC-01 requires filtering inside the vector query. With an HNSW index, selective filters can return fewer than k rows; evaluate pgvector iterative index scans or per-tenant partitioning. Needs an ADR.
4. **Embedding model and dimension decided before Week 3.** `vector(n)` is fixed in the column type, so every environment uses the same model and dimension, and the CI fake embedder matches it. Store `embedding_model` and `embedding_dim` per chunk. Needs an ADR.
5. **Demo corpus chosen in Week 1.** The Week 3 benchmark depends on a fixed, versioned, licensed corpus with cross-document overlap and some restricted documents for ACL tests. Needs an ADR.
6. **Early AWS spike in Week 3–4.** Deploy the health endpoint to Fargate (about 3 hours) to surface IAM, ECR and networking problems before Week 7. Also run the FPT model spike (ADR-0004) at the start of Week 3.
7. **OpenSearch Serverless out of core scope.** Its minimum capacity charge likely dominates the budget; an ADR justifies pgvector at this scale instead.
8. **Hybrid retrieval stays in Postgres.** `tsvector` full-text search plus pgvector, merged with reciprocal rank fusion.
9. **Evaluation records the judge.** EVAL-02 runs record the judge model and prompt version alongside the answer model and dataset version.
10. **Agent workflow as an explicit state machine.** Typed states and transitions, which makes invalid transitions straightforward to test.
11. **Architecture enforced by tooling (done, ADR-0002).** import-linter layer and forbidden-import contracts plus ruff banned imports, run in the edit hook, pytest, `/check` and CI.
12. **Model provider is FPT AI Marketplace (ADR-0004).** AWS is the deployment platform only; Bedrock is not implemented. Embeddings default to `Vietnamese_Embedding` (1024 dimensions), checked against a multilingual candidate in Week 4. The LLM is chosen by a Week 3 structured-output spike.
13. **Access control model decided (ADR-0003).** Tenant plus allowed groups on every chunk, filtered inside the vector query; the search port requires a `Principal`.
14. **Bilingual corpus decided (ADR-0005).** A fictional company corpus, about 60% Vietnamese and 40% English, with versions, access groups and cross-lingual benchmark questions. Text is NFC-normalized.
15. **Serving rule for document versions (ADR-0007).** Search serves a document's highest indexed version, so a pending or failed re-upload never hides the previous version. The contract tests enforce this for the fake and Postgres.
16. **Filtered HNSW verified, not assumed (ADR-0003, ADR-0007).** An integration test forces an HNSW plan and shows that plain HNSW drops a visible chunk behind 300 restricted neighbours, while the adapter (iterative scan on pgvector 0.8+, exact scan otherwise) returns it.
