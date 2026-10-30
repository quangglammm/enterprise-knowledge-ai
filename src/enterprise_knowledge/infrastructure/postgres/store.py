"""PostgreSQL implementation of DocumentRepository and ChunkSearch (ADR-0003, ADR-0007).

Every write that can change what search should see (status, access policy, chunks) ends
with ``_apply_serving_rule`` in the same transaction: it prunes chunks of superseded
versions (ADR-0008) and recomputes ``searchable``.
"""

import logging
import re
from collections.abc import Sequence
from typing import Any, Self

from psycopg import AsyncConnection, sql
from psycopg.errors import UniqueViolation
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from enterprise_knowledge.domain.access import AccessPolicy, Principal
from enterprise_knowledge.domain.documents import (
    ContentType,
    Document,
    DocumentChunk,
    DocumentStatus,
    Embedding,
    Language,
    SourceLocation,
    validate_chunk_set,
)
from enterprise_knowledge.domain.errors import DocumentAlreadyExistsError, DocumentNotFoundError
from enterprise_knowledge.domain.ids import ChunkId, DocumentId, GroupId, TenantId
from enterprise_knowledge.domain.ports import Vector
from enterprise_knowledge.domain.retrieval import RetrievedEvidence

logger = logging.getLogger(__name__)

_ITERATIVE_SCAN_MIN_VERSION = (0, 8, 0)
_MAX_SCAN_TUPLES = 20_000
_VECTOR_TYPE = re.compile(r"^vector\((\d+)\)$")

_DOCUMENT_FIELDS = (
    "tenant_id",
    "id",
    "version",
    "title",
    "filename",
    "content_type",
    "checksum",
    "status",
    "allowed_groups",
    "language",
    "error_category",
    "created_at",
    "updated_at",
)
_CHUNK_FIELDS = (
    "id",
    "document_id",
    "document_version",
    "chunk_index",
    "text",
    "page",
    "section",
    "char_start",
    "char_end",
    "allowed_groups",
    "language",
    "tenant_id",
)
_DOCUMENT_COLUMNS = sql.SQL(", ").join(map(sql.Identifier, _DOCUMENT_FIELDS))
_DOCUMENT_VALUES = sql.SQL(", ").join(map(sql.Placeholder, _DOCUMENT_FIELDS))
_CHUNK_COLUMNS = sql.SQL(", ").join(map(sql.Identifier, _CHUNK_FIELDS))

_SEARCH_SQL = sql.SQL("""
WITH hits AS MATERIALIZED (
    SELECT {columns}, embedding <=> %(query)s::vector AS distance
    FROM chunks
    WHERE tenant_id = %(tenant)s
      AND searchable
      AND allowed_groups && %(groups)s::text[]
      AND embedding_model = %(model)s
    ORDER BY embedding <=> %(query)s::vector
    LIMIT %(k)s
)
SELECT hits.*, d.title
FROM hits
JOIN documents d
  ON d.tenant_id = hits.tenant_id AND d.id = hits.document_id AND d.version = hits.document_version
ORDER BY hits.distance, hits.id
""").format(columns=_CHUNK_COLUMNS)

# Full-text relevance (ADR-0014): the sum of BM25-style IDF over the query terms a chunk
# contains, with N and document frequencies counted over the chunks this principal may
# read. The same filters as vector search apply inside the query (ADR-0003).
_LEXICAL_SQL = sql.SQL("""
WITH terms AS MATERIALIZED (
    SELECT DISTINCT lexeme
    FROM unnest(tsvector_to_array(to_tsvector('simple', %(text)s))) AS lexeme
),
visible AS MATERIALIZED (
    SELECT id, lexemes
    FROM chunks
    WHERE tenant_id = %(tenant)s
      AND searchable
      AND allowed_groups && %(groups)s::text[]
      AND embedding_model = %(model)s
),
idf AS (
    SELECT t.lexeme,
           ln(1 + ((SELECT count(*) FROM visible) - count(*) + 0.5) / (count(*) + 0.5)) AS idf
    FROM terms t
    JOIN visible v ON v.lexemes @@ to_tsquery('simple', quote_literal(t.lexeme))
    GROUP BY t.lexeme
),
scored AS (
    SELECT v.id, sum(i.idf)::float8 AS relevance
    FROM visible v
    JOIN idf i ON v.lexemes @@ to_tsquery('simple', quote_literal(i.lexeme))
    GROUP BY v.id
    ORDER BY relevance DESC, v.id
    LIMIT %(k)s
)
SELECT {columns}, c.embedding <=> %(query)s::vector AS distance, d.title
FROM scored
JOIN chunks c ON c.id = scored.id
JOIN documents d
  ON d.tenant_id = c.tenant_id AND d.id = c.document_id AND d.version = c.document_version
ORDER BY scored.relevance DESC, c.id
""").format(columns=sql.SQL(", ").join(sql.Identifier("c", f) for f in _CHUNK_FIELDS))

# Chunks of versions older than the serving one are stale (ADR-0008). Without an indexed
# version the comparison is NULL and nothing is pruned.
_PRUNE_SUPERSEDED_SQL = """
DELETE FROM chunks c
USING (
    SELECT max(version) FILTER (WHERE status = 'indexed') AS version
    FROM documents WHERE tenant_id = %(tenant)s AND id = %(document)s
) s
WHERE c.tenant_id = %(tenant)s
  AND c.document_id = %(document)s
  AND c.document_version < s.version
"""

_RECOMPUTE_SEARCHABLE_SQL = """
UPDATE chunks c
SET searchable = (c.document_version IS NOT DISTINCT FROM s.version)
FROM (
    SELECT max(version) FILTER (WHERE status = 'indexed') AS version
    FROM documents WHERE tenant_id = %(tenant)s AND id = %(document)s
) s
WHERE c.tenant_id = %(tenant)s
  AND c.document_id = %(document)s
  AND c.searchable IS DISTINCT FROM (c.document_version IS NOT DISTINCT FROM s.version)
"""


class SchemaMismatchError(RuntimeError):
    """The database schema does not match this build (missing migrations, wrong dimension)."""


class PostgresDocumentStore:
    def __init__(
        self, pool: AsyncConnectionPool, *, embedding_dimension: int, iterative_scan: bool
    ) -> None:
        self._pool = pool
        self._dimension = embedding_dimension
        self.iterative_scan = iterative_scan

    @classmethod
    async def connect(
        cls,
        conninfo: str,
        *,
        embedding_dimension: int,
        min_size: int = 1,
        max_size: int = 10,
        connect_timeout: float = 10.0,
    ) -> Self:
        """Open a pool and verify the schema. Fails fast on misconfiguration."""
        pool = AsyncConnectionPool(
            conninfo, min_size=min_size, max_size=max_size, timeout=connect_timeout, open=False
        )
        await pool.open(wait=True, timeout=connect_timeout)
        try:
            async with pool.connection() as conn:
                await _check_dimension(conn, embedding_dimension)
                version = await _pgvector_version(conn)
        except BaseException:
            await pool.close()
            raise
        iterative = version >= _ITERATIVE_SCAN_MIN_VERSION
        if not iterative:
            logger.warning(
                "pgvector without iterative index scans; filtered search uses exact scans",
                extra={"pgvector_version": ".".join(map(str, version))},
            )
        return cls(pool, embedding_dimension=embedding_dimension, iterative_scan=iterative)

    async def close(self) -> None:
        await self._pool.close()

    async def ping(self) -> None:
        """Readiness check: raises if the database is unreachable."""
        async with self._pool.connection() as conn:
            await conn.execute("SELECT 1")

    # --- DocumentRepository -------------------------------------------------------------

    async def add_document(self, document: Document) -> None:
        try:
            async with self._pool.connection() as conn:
                await conn.execute(
                    sql.SQL("INSERT INTO documents ({columns}) VALUES ({values})").format(
                        columns=_DOCUMENT_COLUMNS, values=_DOCUMENT_VALUES
                    ),
                    _document_params(document),
                )
        except UniqueViolation as exc:
            raise DocumentAlreadyExistsError(f"{document.id} v{document.version} exists") from exc

    async def get_document(self, tenant_id: TenantId, document_id: DocumentId) -> Document | None:
        async with self._pool.connection() as conn:
            cur = await conn.cursor(row_factory=dict_row).execute(
                sql.SQL(
                    "SELECT {columns} FROM documents"
                    " WHERE tenant_id = %s AND id = %s ORDER BY version DESC LIMIT 1"
                ).format(columns=_DOCUMENT_COLUMNS),
                (tenant_id, document_id),
            )
            row = await cur.fetchone()
        return _document(row) if row else None

    async def find_by_checksum(self, tenant_id: TenantId, checksum: str) -> Document | None:
        async with self._pool.connection() as conn:
            cur = await conn.cursor(row_factory=dict_row).execute(
                sql.SQL(
                    "SELECT {columns} FROM documents"
                    " WHERE tenant_id = %s AND checksum = %s AND status <> 'deleted'"
                    " ORDER BY id DESC, version DESC LIMIT 1"
                ).format(columns=_DOCUMENT_COLUMNS),
                (tenant_id, checksum),
            )
            row = await cur.fetchone()
        return _document(row) if row else None

    async def update_document(self, document: Document) -> None:
        params = _document_params(document)
        async with self._pool.connection() as conn, conn.transaction():
            cur = await conn.execute(
                "UPDATE documents SET title = %(title)s, filename = %(filename)s,"
                " content_type = %(content_type)s, checksum = %(checksum)s, status = %(status)s,"
                " allowed_groups = %(allowed_groups)s, language = %(language)s,"
                " error_category = %(error_category)s, updated_at = %(updated_at)s"
                " WHERE tenant_id = %(tenant_id)s AND id = %(id)s AND version = %(version)s",
                params,
            )
            if cur.rowcount == 0:
                raise DocumentNotFoundError(f"{document.id} v{document.version} not found")
            # ADR-0003: a policy change reaches the version's chunks in the same transaction.
            await conn.execute(
                "UPDATE chunks SET allowed_groups = %(allowed_groups)s"
                " WHERE tenant_id = %(tenant_id)s AND document_id = %(id)s"
                " AND document_version = %(version)s",
                params,
            )
            await _apply_serving_rule(conn, document.tenant_id, document.id)

    async def replace_chunks(
        self,
        document: Document,
        chunks: Sequence[DocumentChunk],
        embeddings: Sequence[Embedding],
    ) -> None:
        validate_chunk_set(document, chunks, embeddings)
        for embedding in embeddings:
            if embedding.dimension != self._dimension:
                raise ValueError(
                    f"embedding dimension {embedding.dimension} != column dimension "
                    f"{self._dimension}"
                )
        vectors = {e.chunk_id: e for e in embeddings}
        key = {"tenant": document.tenant_id, "document": document.id, "version": document.version}

        async with self._pool.connection() as conn, conn.transaction():
            cur = await conn.execute(
                "SELECT 1 FROM documents WHERE tenant_id = %(tenant)s AND id = %(document)s"
                " AND version = %(version)s FOR UPDATE",
                key,
            )
            if await cur.fetchone() is None:
                raise DocumentNotFoundError(f"{document.id} v{document.version} not found")
            await conn.execute(
                "DELETE FROM chunks WHERE tenant_id = %(tenant)s AND document_id = %(document)s"
                " AND document_version = %(version)s",
                key,
            )
            async with conn.cursor() as insert:
                await insert.executemany(
                    "INSERT INTO chunks (id, tenant_id, document_id, document_version,"
                    " chunk_index, text, page, section, char_start, char_end, allowed_groups,"
                    " language, embedding_model, embedding, lexemes) VALUES (%s, %s, %s, %s,"
                    " %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::vector,"
                    " to_tsvector('simple', concat_ws(' ', %s::text, %s::text, %s::text)))",
                    [
                        (
                            *_chunk_params(c, vectors[c.id]),
                            document.title,
                            c.source.section,
                            c.text,
                        )
                        for c in chunks
                    ],
                )
            await _apply_serving_rule(conn, document.tenant_id, document.id)

    async def list_chunks(
        self, tenant_id: TenantId, document_id: DocumentId, version: int
    ) -> list[DocumentChunk]:
        async with self._pool.connection() as conn:
            cur = await conn.cursor(row_factory=dict_row).execute(
                sql.SQL(
                    "SELECT {columns} FROM chunks WHERE tenant_id = %s"
                    " AND document_id = %s AND document_version = %s ORDER BY chunk_index"
                ).format(columns=_CHUNK_COLUMNS),
                (tenant_id, document_id, version),
            )
            rows = await cur.fetchall()
        return [_chunk(row) for row in rows]

    async def delete_document(self, tenant_id: TenantId, document_id: DocumentId) -> None:
        async with self._pool.connection() as conn, conn.transaction():
            await conn.execute(
                "UPDATE documents SET status = 'deleted' WHERE tenant_id = %s AND id = %s",
                (tenant_id, document_id),
            )
            await conn.execute(
                "DELETE FROM chunks WHERE tenant_id = %s AND document_id = %s",
                (tenant_id, document_id),
            )

    # --- ChunkSearch --------------------------------------------------------------------

    async def search(
        self,
        principal: Principal,
        query_vector: Vector,
        *,
        k: int,
        embedding_model: str,
    ) -> list[RetrievedEvidence]:
        if k < 1:
            raise ValueError("k must be at least 1")
        if len(query_vector) != self._dimension:
            raise ValueError(f"query dimension {len(query_vector)} != {self._dimension}")
        params = {
            "query": _vector_literal(query_vector),
            "tenant": principal.tenant_id,
            "groups": sorted(principal.groups),
            "model": embedding_model,
            "k": k,
        }
        async with self._pool.connection() as conn, conn.transaction():
            if self.iterative_scan:
                await conn.execute("SET LOCAL hnsw.iterative_scan = relaxed_order")
                await conn.execute(
                    sql.SQL("SET LOCAL hnsw.max_scan_tuples = {}").format(
                        sql.Literal(_MAX_SCAN_TUPLES)
                    )
                )
                rows = await _run_search(conn, params)
                if len(rows) >= k:
                    return [_evidence(row) for row in rows]
                # The index scan can stop early (scan budget, graph shape) under a selective
                # filter. Fewer than k rows must mean fewer accessible chunks exist, so
                # confirm with an exact scan (ADR-0007).
                logger.debug("hnsw returned fewer than k; exact rescan", extra={"k": k})
            # Exact scan: correct under any filter, slower at scale (ADR-0007).
            await conn.execute("SET LOCAL enable_indexscan = off")
            rows = await _run_search(conn, params)
        return [_evidence(row) for row in rows]

    async def search_lexical(
        self,
        principal: Principal,
        query_text: str,
        query_vector: Vector,
        *,
        k: int,
        embedding_model: str,
    ) -> list[RetrievedEvidence]:
        if k < 1:
            raise ValueError("k must be at least 1")
        if len(query_vector) != self._dimension:
            raise ValueError(f"query dimension {len(query_vector)} != {self._dimension}")
        params = {
            "text": query_text,
            "query": _vector_literal(query_vector),
            "tenant": principal.tenant_id,
            "groups": sorted(principal.groups),
            "model": embedding_model,
            "k": k,
        }
        async with self._pool.connection() as conn:
            cur = await conn.cursor(row_factory=dict_row).execute(_LEXICAL_SQL, params)
            rows = await cur.fetchall()
        return [_evidence(row) for row in rows]


async def _run_search(conn: AsyncConnection[Any], params: dict[str, Any]) -> list[dict[str, Any]]:
    cur = await conn.cursor(row_factory=dict_row).execute(_SEARCH_SQL, params)
    return await cur.fetchall()


async def _apply_serving_rule(
    conn: AsyncConnection[Any], tenant_id: TenantId, document_id: DocumentId
) -> None:
    params = {"tenant": tenant_id, "document": document_id}
    await conn.execute(_PRUNE_SUPERSEDED_SQL, params)
    await conn.execute(_RECOMPUTE_SEARCHABLE_SQL, params)


async def _check_dimension(conn: AsyncConnection[Any], expected: int) -> None:
    cur = await conn.execute(
        "SELECT format_type(atttypid, atttypmod) FROM pg_attribute"
        " WHERE attrelid = to_regclass('chunks') AND attname = 'embedding'"
    )
    row = await cur.fetchone()
    if row is None:
        raise SchemaMismatchError("table chunks not found; run `eka-migrate` first")
    match = _VECTOR_TYPE.match(str(row[0]))
    if match is None or int(match.group(1)) != expected:
        raise SchemaMismatchError(
            f"chunks.embedding is {row[0]}, but the configured embedding dimension is {expected}"
        )


async def _pgvector_version(conn: AsyncConnection[Any]) -> tuple[int, ...]:
    cur = await conn.execute("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
    row = await cur.fetchone()
    if row is None:
        raise SchemaMismatchError("pgvector extension is not installed")
    return tuple(int(part) for part in str(row[0]).split(".")[:3])


def _vector_literal(vector: Vector) -> str:
    return "[" + ",".join(repr(float(v)) for v in vector) + "]"


def _document_params(document: Document) -> dict[str, Any]:
    return {
        "tenant_id": document.tenant_id,
        "id": document.id,
        "version": document.version,
        "title": document.title,
        "filename": document.filename,
        "content_type": document.content_type.value,
        "checksum": document.checksum,
        "status": document.status.value,
        "allowed_groups": sorted(document.access.allowed_groups),
        "language": document.language.value,
        "error_category": document.error_category,
        "created_at": document.created_at,
        "updated_at": document.updated_at,
    }


def _chunk_params(chunk: DocumentChunk, embedding: Embedding) -> tuple[Any, ...]:
    return (
        chunk.id,
        chunk.access.tenant_id,
        chunk.document_id,
        chunk.document_version,
        chunk.chunk_index,
        chunk.text,
        chunk.source.page,
        chunk.source.section,
        chunk.source.char_start,
        chunk.source.char_end,
        sorted(chunk.access.allowed_groups),
        chunk.language.value,
        embedding.model,
        _vector_literal(embedding.vector),
    )


def _policy(row: dict[str, Any]) -> AccessPolicy:
    return AccessPolicy(
        tenant_id=TenantId(row["tenant_id"]),
        allowed_groups=frozenset(GroupId(g) for g in row["allowed_groups"]),
    )


def _document(row: dict[str, Any]) -> Document:
    return Document(
        id=DocumentId(row["id"]),
        title=row["title"],
        filename=row["filename"],
        content_type=ContentType(row["content_type"]),
        checksum=row["checksum"],
        version=row["version"],
        status=DocumentStatus(row["status"]),
        access=_policy(row),
        language=Language(row["language"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        error_category=row["error_category"],
    )


def _source(row: dict[str, Any]) -> SourceLocation:
    return SourceLocation(
        page=row["page"],
        section=row["section"],
        char_start=row["char_start"],
        char_end=row["char_end"],
    )


def _chunk(row: dict[str, Any]) -> DocumentChunk:
    return DocumentChunk(
        id=ChunkId(row["id"]),
        document_id=DocumentId(row["document_id"]),
        document_version=row["document_version"],
        chunk_index=row["chunk_index"],
        text=row["text"],
        source=_source(row),
        access=_policy(row),
        language=Language(row["language"]),
    )


def _evidence(row: dict[str, Any]) -> RetrievedEvidence:
    return RetrievedEvidence(
        chunk_id=ChunkId(row["id"]),
        document_id=DocumentId(row["document_id"]),
        document_version=row["document_version"],
        title=row["title"],
        text=row["text"],
        score=1.0 - float(row["distance"]),
        source=_source(row),
        access=_policy(row),
        language=Language(row["language"]),
    )
