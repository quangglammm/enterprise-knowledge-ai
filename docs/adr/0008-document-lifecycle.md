# ADR-0008: Document lifecycle: superseded versions and deletion

- Status: Accepted
- Date: 2026-10-29

## Context

ING-03 requires that reprocessing is idempotent, that changed content creates a new version, and that deletion removes stale indexed data. ADR-0007 decided which version search serves (the highest indexed one), but every older version kept its chunks and embeddings forever, hidden only by `searchable = false`. Each re-upload therefore grew the `chunks` table and the HNSW graph, which ADR-0007 already flagged as bloat. Separately, nothing called `delete_document`: there was no use case, no endpoint, and original uploads were never removed. A deleted document could also still be read through `GET /v1/documents/{id}` and given a new version.

## Options considered

Superseded versions:

1. **Keep every version's chunks** (status quo). Allows rollback and inspecting old text. Storage and index size grow with every re-upload, and the rows are never served.
2. **Prune chunks older than the serving version.** Chunks and embeddings of versions below the highest indexed one are deleted in the same transaction as the write that changed the serving version. Bounded index size. Old text is gone, but document rows and original files remain.
3. **Keep the last N versions.** A middle ground that adds a setting and more cases to test, for a rollback feature nobody has asked for.

Who may delete:

1. **Any principal who can read the document**, the same rule as uploading a new version.
2. **Members of every allowed group.** Stricter, but an unusual rule to explain.
3. **Roles (editor/admin) on `Principal`.** Realistic, but it changes the access model (ADR-0003) and widens this item.

## Decision

- **Prune superseded chunks (option 2).** Every repository write ends with one function that first deletes chunks of versions older than the serving version, then recomputes `searchable` (`_apply_serving_rule` in Postgres, `_prune_superseded` in the fake). A pending or failed newer version never prunes anything, so ADR-0007's "a re-upload is never a search outage" still holds. Citations are validated against evidence retrieved in the same request (RAG-02), so old chunks are never needed to resolve one.
- **Document rows of all versions are kept** as history. Original files of superseded versions are kept until the document is deleted.
- **Deletion is soft for metadata and hard for content.** `DeleteDocument` marks every version `deleted`, deletes all chunks (one transaction), then deletes the original file of each version `1..N`. The database step runs first, so search forgets the document even if a file deletion fails. Deleting again returns success and retries the file deletions, which makes a retry the recovery path.
- **A deleted document stays deleted.** `GET`, chunk listing and new-version uploads return 404. Uploading the same bytes again creates a new document, because checksum dedup ignores deleted versions.
- **Delete authorization: anyone who can read (option 1).** A principal without read access gets 404, the same as for an absent document, so callers cannot probe for documents. SEC-01 (week 9) may add roles.
- **Concurrent new-version uploads** that collide on `(id, version)` return 409 `document_exists`; the client may retry.

## Consequences

- `GET /v1/documents/{id}/chunks?version=N` returns an empty list for a superseded version.
- The `chunks` table holds at most one indexed version per document, plus any newer version being indexed. The week 5 bloat measurement (ADR-0007) now covers only the `searchable` flip, not accumulated versions.
- Deleted documents keep their metadata rows. A hard purge (for example, for data-subject requests) is not implemented; it would delete the document rows as well.
- Revisit if a feature needs old text: answer audit trails, version diffing or rollback. Option 3, or archiving chunks outside the vector index, would then be needed.
