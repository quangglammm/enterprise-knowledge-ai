# ADR-0007: Postgres persistence and vector search

- Status: Accepted
- Date: 2026-10-29

## Context

Day 4 implements `DocumentRepository` and `ChunkSearch` (ADR-0003, ADR-0006) on PostgreSQL with pgvector. The adapter must pass the same contract tests as the in-memory fake, enforce access control inside the query, and stay readable enough to tune by hand (HNSW settings, query plans).

Writing the adapter exposed a gap in the contract: if a new version is added and still pending, should search return the previous indexed version or nothing? Returning nothing makes every re-upload a temporary outage for that document.

## Options considered

- **Data access:** SQLAlchemy ORM vs SQLAlchemy Core vs psycopg 3 with explicit SQL. The queries are few and performance-sensitive (vector operators, array overlap, `SET LOCAL` tuning), and an ORM would mostly be bypassed.
- **Migrations:** Alembic (needs SQLAlchemy metadata) vs a small runner over ordered SQL files.
- **Current-version filter:** a join or subquery on `documents` at query time vs a denormalized `searchable` flag on `chunks`. Join filters make the HNSW planner less predictable; a flag keeps the search a single-table scan.
- **Filtered HNSW on old pgvector:** silently accept fewer than k results vs fall back to exact search.

## Decision

- **psycopg 3 (async) with `psycopg_pool`**, explicit SQL in `infrastructure/postgres/`. Vectors are sent in pgvector's text form with a `::vector` cast; vectors are never read back, so no client-side vector adapter is needed.
- **Migrations:** ordered SQL files packaged with the code, applied by a runner (`eka-migrate`) that records versions in `schema_migrations`, takes an advisory lock, and applies each file in its own transaction. Applied files are never edited; changes go in a new file.
- **Schema:** `documents` keyed by `(tenant_id, id, version)`; `chunks` keyed by chunk ID with a foreign key to its document version (cascade delete). Chunks carry `tenant_id`, `allowed_groups text[]`, `embedding_model`, `embedding vector(1024)` and `searchable`. Indexes: B-tree `(tenant_id, searchable)`, GIN on `allowed_groups`, HNSW `vector_cosine_ops` on `embedding`, and `(tenant_id, checksum)` on non-deleted documents.
- **Serving rule (contract change):** the searchable version of a document is its highest version with status `indexed`. A newer pending or failed version does not hide the previous indexed one. Deleting a document removes all versions from search. The repository recomputes `searchable` for the whole document in the same transaction as every status change, policy change and chunk replacement. The in-memory fake and the contract tests are updated to match.
- **Search:** one query on `chunks` filtered by tenant, group overlap, `searchable` and `embedding_model`, ordered by cosine distance, limited to k, then re-sorted by `(distance, chunk_id)` for determinism. Score is cosine similarity (`1 - distance`).
- **pgvector version:** detected once per pool. On 0.8+, each search runs with `SET LOCAL hnsw.iterative_scan = relaxed_order` and a bounded `hnsw.max_scan_tuples` (ADR-0003). On older versions the adapter disables index scans for the search transaction, giving an exact scan: slower, but never wrong under selective filters. It logs a warning at startup. Docker Compose and CI use the `pgvector/pgvector:pg17` image (0.8.x); the fallback exists for environments like a distribution package.
- **Dimension check:** at startup the adapter reads the `embedding` column's declared dimension and refuses to start if it differs from the configured embedding dimension. Changing embedding models means a new migration and a re-index (ADR-0004).
- **Shared validation:** the rules for a valid chunk set (chunks belong to the document version, unique, exactly one embedding each) move into the domain, so the fake and the adapter enforce the same rules.

## Consequences

- Integration tests need Postgres. They are marked `integration`, excluded from the default run, and run in CI against a pgvector service container. The contract tests run against both the fake and Postgres.
- `searchable` is derived data; a bug that forgets to recompute it would serve stale versions. Every write path calls one recompute function, and the contract tests cover each transition.
- Inserting 1024-dimension vectors as text is slower than binary COPY. Acceptable at portfolio scale; revisit if bulk indexing time matters in Week 5.
