# ADR-0003: Access control model

- Status: Accepted
- Date: 2026-10-29

## Context

SEC-01 requires that a user never receives restricted documents, and the stronger guarantee is that restricted text never reaches the model context. That can only be enforced inside the retrieval query: filtering after retrieval leaks through scores, through bugs in the post-filter, and returns fewer than k results. The schema must carry access data from the first migration, because adding it later means re-indexing.

The demo models a multi-tenant SaaS: several fictional tenants, each with departments whose documents are restricted to groups (for example HR or security).

## Options considered

1. **Tenant plus allowed groups on every chunk.** Filter `tenant_id = $1 AND allowed_groups && $2` (array overlap) in the same query as the vector search. Pros: one table, no join, GIN-indexable, simple to reason about. Cons: changing a document's ACL rewrites its chunks.
2. **Per-document ACL table joined at query time.** Pros: ACL changes touch one row. Cons: every vector search pays a join, and the planner interacts badly with the HNSW index.
3. **Tenant only.** Pros: simplest. Cons: cannot express restricted documents, so SEC-01 is untestable.

## Decision

Option 1.

- `Document` and `DocumentChunk` carry an `AccessPolicy`: `tenant_id` plus a non-empty set of `allowed_groups`. "Everyone in the tenant" is an ordinary group (for example `all-staff`); there is no implicit public access.
- A request runs as a `Principal`: `tenant_id`, `user_id`, `groups`. Access is granted when tenants match and the group sets intersect.
- Chunks copy the document's policy (denormalized). Changing a document's policy updates all its chunks in the same transaction.
- The search port takes a `Principal` as a required argument, so a call site cannot forget it. Adapters must apply the filter inside the query.
- Defense in depth: the retrieval use case re-checks every returned item with `Principal.can_access`. A failure raises `AccessViolationError` (a bug, logged and surfaced as a 500), never a silent drop that would hide an adapter defect.
- Postgres indexes: B-tree on `tenant_id`, GIN on `allowed_groups`, HNSW on the embedding.
- HNSW with a selective filter can return fewer than k rows. The adapter enables pgvector iterative index scans (`hnsw.iterative_scan`, pgvector 0.8+) with a bounded `hnsw.max_scan_tuples`, and the result reports when fewer than k rows were found. A test with a highly selective ACL covers this.

## Consequences

- Every ingestion path must know the document's policy up front. Uploads without one are rejected.
- Tests include: a user without the group never receives the chunk even when it is the best match; cross-tenant access is impossible; an ACL change takes effect on the next query.
- Revisit if ACL changes become frequent or per-user (not per-group) grants are needed; option 2 or a per-tenant partitioned index would then be reconsidered.
