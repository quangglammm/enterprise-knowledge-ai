"""Behavior every DocumentRepository + ChunkSearch implementation must have.

Parametrized over implementations: the in-memory fake now, the Postgres adapter from
Week 1 Day 4 (added to STORES with the integration marker). A fake that drifts from
production semantics fails here.
"""

import contextlib
from collections.abc import Callable
from typing import Protocol

import pytest

from enterprise_knowledge.domain.documents import (
    Document,
    DocumentChunk,
    DocumentStatus,
    Embedding,
    SourceLocation,
)
from enterprise_knowledge.domain.errors import DocumentAlreadyExistsError, DocumentNotFoundError
from enterprise_knowledge.domain.ids import DocumentId, TenantId
from enterprise_knowledge.domain.ports import ChunkSearch, DocumentRepository
from tests.factories import NOW, TENANT, make_document, make_policy, make_principal
from tests.fakes.document_store import InMemoryDocumentStore
from tests.fakes.embedder import HashEmbedder

MODEL = "fake-hash"
OTHER_TENANT = TenantId("other-co")


class Store(DocumentRepository, ChunkSearch, Protocol):
    """Both ports; production uses one Postgres adapter for both."""


STORES: list[Callable[[], Store]] = [InMemoryDocumentStore]


@pytest.fixture(params=STORES, ids=lambda factory: factory.__name__)
def store(request: pytest.FixtureRequest) -> Store:
    factory: Callable[[], Store] = request.param
    return factory()


@pytest.fixture
def embedder() -> HashEmbedder:
    return HashEmbedder(model=MODEL)


async def index(store: Store, embedder: HashEmbedder, document: Document, *texts: str) -> Document:
    """Add the document version if new, then index it with the given chunk texts."""
    with contextlib.suppress(DocumentAlreadyExistsError):
        await store.add_document(document)
    chunks = [
        DocumentChunk.for_document(document, index=i, text=t, source=SourceLocation(page=1))
        for i, t in enumerate(texts)
    ]
    vectors = await embedder.embed_documents([c.text for c in chunks])
    embeddings = [
        Embedding(chunk_id=c.id, model=MODEL, dimension=embedder.dimension, vector=v)
        for c, v in zip(chunks, vectors, strict=True)
    ]
    await store.replace_chunks(document, chunks, embeddings)
    indexed = document.with_status(DocumentStatus.INDEXED, now=NOW)
    await store.update_document(indexed)
    return indexed


async def search_ids(
    store: Store,
    embedder: HashEmbedder,
    query: str,
    *groups: str,
    k: int = 5,
    tenant: TenantId = TENANT,
) -> list[str]:
    hits = await store.search(
        make_principal(tenant, *groups),
        await embedder.embed_query(query),
        k=k,
        embedding_model=MODEL,
    )
    return [h.document_id for h in hits]


# --- repository -----------------------------------------------------------------------


async def test_add_and_get_document(store: Store) -> None:
    document = make_document()

    await store.add_document(document)

    assert await store.get_document(TENANT, document.id) == document


async def test_adding_same_version_twice_is_rejected(store: Store) -> None:
    await store.add_document(make_document())

    with pytest.raises(DocumentAlreadyExistsError):
        await store.add_document(make_document())


async def test_get_document_is_tenant_scoped(store: Store) -> None:
    await store.add_document(make_document())

    assert await store.get_document(OTHER_TENANT, DocumentId("doc-1")) is None


async def test_get_document_returns_highest_version(store: Store) -> None:
    await store.add_document(make_document(version=1))
    await store.add_document(make_document(version=2, checksum="1" * 64))

    current = await store.get_document(TENANT, DocumentId("doc-1"))

    assert current is not None
    assert current.version == 2


async def test_find_by_checksum_is_tenant_scoped_and_ignores_deleted(store: Store) -> None:
    await store.add_document(make_document(checksum="c" * 64))

    assert await store.find_by_checksum(TENANT, "c" * 64) is not None
    assert await store.find_by_checksum(OTHER_TENANT, "c" * 64) is None

    await store.delete_document(TENANT, DocumentId("doc-1"))

    assert await store.find_by_checksum(TENANT, "c" * 64) is None


async def test_update_unknown_document_raises(store: Store) -> None:
    with pytest.raises(DocumentNotFoundError):
        await store.update_document(make_document())


async def test_replace_chunks_is_idempotent(store: Store, embedder: HashEmbedder) -> None:
    document = make_document()
    await index(store, embedder, document, "first chunk", "second chunk")

    await index(store, embedder, document, "first chunk", "second chunk")

    chunks = await store.list_chunks(TENANT, document.id, 1)
    assert [c.chunk_index for c in chunks] == [0, 1]


async def test_replace_chunks_requires_one_embedding_per_chunk(store: Store) -> None:
    document = make_document()
    await store.add_document(document)
    chunk = DocumentChunk.for_document(document, index=0, text="x", source=SourceLocation())

    with pytest.raises(ValueError, match="embedding"):
        await store.replace_chunks(document, [chunk], [])


async def test_replace_chunks_rejects_chunks_of_another_version(store: Store) -> None:
    v1 = make_document(version=1)
    v2 = make_document(version=2, checksum="1" * 64)
    await store.add_document(v1)
    chunk_v2 = DocumentChunk.for_document(v2, index=0, text="x", source=SourceLocation())
    embedding = Embedding(chunk_id=chunk_v2.id, model=MODEL, dimension=1, vector=(1.0,))

    with pytest.raises(ValueError, match="does not belong"):
        await store.replace_chunks(v1, [chunk_v2], [embedding])


# --- search: access control (ADR-0003) -----------------------------------------------


async def test_restricted_best_match_is_never_returned(
    store: Store, embedder: HashEmbedder
) -> None:
    hr_only = make_document(id=DocumentId("salary"), access=make_policy(TENANT, "hr"))
    public = make_document(id=DocumentId("handbook"), checksum="1" * 64)
    await index(store, embedder, hr_only, "salary bands for engineers")
    await index(store, embedder, public, "office opening hours")

    assert await search_ids(store, embedder, "salary bands for engineers", "all-staff") == [
        "handbook"
    ]
    assert (await search_ids(store, embedder, "salary bands for engineers", "hr"))[0] == "salary"


async def test_other_tenants_content_is_invisible(store: Store, embedder: HashEmbedder) -> None:
    foreign = make_document(id=DocumentId("foreign"), access=make_policy(OTHER_TENANT))
    await index(store, embedder, foreign, "quy định nghỉ phép")

    assert await search_ids(store, embedder, "quy định nghỉ phép", "all-staff") == []


async def test_selective_filter_returns_fewer_than_k(store: Store, embedder: HashEmbedder) -> None:
    for i in range(5):
        doc = make_document(
            id=DocumentId(f"sec-{i}"), checksum=f"{i}" * 64, access=make_policy(TENANT, "security")
        )
        await index(store, embedder, doc, f"incident runbook step {i}")
    visible = make_document(id=DocumentId("visible"), checksum="9" * 64)
    await index(store, embedder, visible, "incident runbook overview")

    assert await search_ids(store, embedder, "incident runbook", "all-staff", k=5) == ["visible"]


async def test_policy_change_takes_effect_on_next_search(
    store: Store, embedder: HashEmbedder
) -> None:
    document = await index(store, embedder, make_document(), "bonus policy 2026")

    restricted = document.model_validate(
        document.model_dump() | {"access": make_policy(TENANT, "managers")}
    )
    await store.update_document(restricted)

    assert await search_ids(store, embedder, "bonus policy 2026", "all-staff") == []
    assert await search_ids(store, embedder, "bonus policy 2026", "managers") == ["doc-1"]


# --- search: versions, status, models ------------------------------------------------


async def test_only_current_version_is_searchable(store: Store, embedder: HashEmbedder) -> None:
    await index(store, embedder, make_document(version=1), "annual leave is 12 days")
    await index(
        store, embedder, make_document(version=2, checksum="1" * 64), "annual leave is 14 days"
    )

    hits = await store.search(
        make_principal(),
        await embedder.embed_query("annual leave days"),
        k=5,
        embedding_model=MODEL,
    )

    assert [(h.document_id, h.document_version) for h in hits] == [("doc-1", 2)]
    assert "14 days" in hits[0].text


async def test_unindexed_and_deleted_documents_are_not_searchable(
    store: Store, embedder: HashEmbedder
) -> None:
    pending = make_document(id=DocumentId("pending"))
    await store.add_document(pending)
    deleted = await index(
        store, embedder, make_document(id=DocumentId("gone"), checksum="1" * 64), "expense claims"
    )
    await store.delete_document(TENANT, deleted.id)

    assert await search_ids(store, embedder, "expense claims", "all-staff") == []


async def test_embeddings_from_another_model_are_ignored(
    store: Store, embedder: HashEmbedder
) -> None:
    await index(store, embedder, make_document(), "vpn setup guide")

    hits = await store.search(
        make_principal(),
        await embedder.embed_query("vpn setup"),
        k=5,
        embedding_model="other-model",
    )

    assert hits == []


async def test_results_are_ranked_and_limited_to_k(store: Store, embedder: HashEmbedder) -> None:
    await index(
        store,
        embedder,
        make_document(),
        "vpn setup guide for laptops",
        "printer setup",
        "vpn troubleshooting and vpn setup",
    )

    hits = await store.search(
        make_principal(), await embedder.embed_query("vpn setup"), k=2, embedding_model=MODEL
    )

    assert len(hits) == 2
    assert hits[0].score >= hits[1].score
    assert all("vpn" in h.text for h in hits)


async def test_k_must_be_positive(store: Store, embedder: HashEmbedder) -> None:
    with pytest.raises(ValueError, match="k"):
        await store.search(
            make_principal(), await embedder.embed_query("x"), k=0, embedding_model=MODEL
        )
