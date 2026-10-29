"""Postgres-specific behavior beyond the shared contract (ADR-0007)."""

from collections.abc import AsyncIterator

import psycopg
import pytest
from psycopg.conninfo import make_conninfo

from enterprise_knowledge.domain.documents import (
    Document,
    DocumentChunk,
    DocumentStatus,
    Embedding,
    SourceLocation,
)
from enterprise_knowledge.domain.ids import DocumentId
from enterprise_knowledge.infrastructure.postgres.migrate import migrate, migration_files
from enterprise_knowledge.infrastructure.postgres.store import (
    PostgresDocumentStore,
    SchemaMismatchError,
)
from tests.contract.conftest import MODEL, reset_database
from tests.factories import NOW, TENANT, make_document, make_policy, make_principal
from tests.fakes.embedder import PRODUCTION_DIMENSION, HashEmbedder

pytestmark = pytest.mark.integration


@pytest.fixture
async def store(postgres_url: str) -> AsyncIterator[PostgresDocumentStore]:
    await reset_database(postgres_url)
    store = await PostgresDocumentStore.connect(
        postgres_url, embedding_dimension=PRODUCTION_DIMENSION
    )
    try:
        yield store
    finally:
        await store.close()


def test_migrations_are_recorded_and_idempotent(postgres_url: str) -> None:
    assert migrate(postgres_url) == []

    with psycopg.connect(postgres_url) as conn:
        recorded = [r[0] for r in conn.execute("SELECT version FROM schema_migrations")]
    assert recorded == [version for version, _ in migration_files()]


async def test_connect_refuses_mismatched_embedding_dimension(postgres_url: str) -> None:
    with pytest.raises(SchemaMismatchError, match="vector\\(1024\\)"):
        await PostgresDocumentStore.connect(postgres_url, embedding_dimension=768)


async def test_ping_succeeds(store: PostgresDocumentStore) -> None:
    await store.ping()


async def test_search_rejects_query_of_wrong_dimension(store: PostgresDocumentStore) -> None:
    with pytest.raises(ValueError, match="dimension"):
        await store.search(make_principal(), (1.0, 0.0), k=3, embedding_model=MODEL)


# With few rows and fresh statistics the planner prefers a B-tree scan plus sort, which is
# exact and would hide the HNSW problem. Disabling sorts makes the HNSW index (the only path
# that returns rows already ordered) the cheapest plan, as it is at production scale.
FORCE_HNSW = "-c enable_sort=off"


@pytest.fixture
async def selective_acl_data(postgres_url: str) -> str:
    """300 restricted chunks closer to the query than the single visible one."""
    await reset_database(postgres_url)
    setup = await PostgresDocumentStore.connect(
        postgres_url, embedding_dimension=PRODUCTION_DIMENSION
    )
    try:
        embedder = HashEmbedder(model=MODEL)
        restricted = make_document(id=DocumentId("hr-files"), access=make_policy(TENANT, "hr"))
        visible = make_document(id=DocumentId("handbook"), checksum="1" * 64)
        await _index(setup, embedder, restricted, [f"salary review band {i}" for i in range(300)])
        await _index(setup, embedder, visible, ["the salary review calendar is published in May"])
    finally:
        await setup.close()
    return make_conninfo(postgres_url, options=FORCE_HNSW)


async def test_plain_hnsw_misses_the_visible_chunk(selective_acl_data: str) -> None:
    """Pins the hazard from ADR-0003 that the adapter must avoid. If this starts passing with
    results, the fixture no longer forces an HNSW plan and the next test proves nothing."""
    query = await HashEmbedder(model=MODEL).embed_query("salary review band")
    literal = "[" + ",".join(repr(v) for v in query) + "]"
    async with await psycopg.AsyncConnection.connect(selective_acl_data) as conn:
        plan = await conn.execute(f"EXPLAIN {PLAIN_HNSW_SQL}", (literal,))
        cur = await conn.execute(PLAIN_HNSW_SQL, (literal,))
        assert any("hnsw" in row[0] for row in await plan.fetchall())
        assert await cur.fetchall() == []


async def test_selective_acl_finds_visible_chunk_behind_many_restricted_neighbours(
    selective_acl_data: str,
) -> None:
    """ADR-0003: iterative index scans (pgvector 0.8+) or the exact-scan fallback must still
    return the visible chunk that plain HNSW misses."""
    store = await PostgresDocumentStore.connect(
        selective_acl_data, embedding_dimension=PRODUCTION_DIMENSION
    )
    try:
        hits = await store.search(
            make_principal(TENANT, "all-staff"),
            await HashEmbedder(model=MODEL).embed_query("salary review band"),
            k=3,
            embedding_model=MODEL,
        )
    finally:
        await store.close()

    assert [h.document_id for h in hits] == ["handbook"]


PLAIN_HNSW_SQL = (
    "SELECT document_id FROM chunks"
    " WHERE tenant_id = 'bamboo-harbor' AND searchable AND allowed_groups && '{all-staff}'"
    " ORDER BY embedding <=> %s::vector LIMIT 3"
)


async def _index(
    store: PostgresDocumentStore,
    embedder: HashEmbedder,
    document: Document,
    texts: list[str],
) -> None:
    await store.add_document(document)
    chunks = [
        DocumentChunk.for_document(document, index=i, text=t, source=SourceLocation())
        for i, t in enumerate(texts)
    ]
    vectors = await embedder.embed_documents(texts)
    embeddings = [
        Embedding(chunk_id=c.id, model=MODEL, dimension=PRODUCTION_DIMENSION, vector=v)
        for c, v in zip(chunks, vectors, strict=True)
    ]
    await store.replace_chunks(document, chunks, embeddings)
    await store.update_document(document.with_status(DocumentStatus.INDEXED, now=NOW))
