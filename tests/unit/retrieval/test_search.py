"""SearchKnowledge: query text in, access-checked evidence out."""

import unicodedata

import pytest

from enterprise_knowledge.domain.access import Principal
from enterprise_knowledge.domain.documents import (
    DocumentChunk,
    DocumentStatus,
    Embedding,
    SourceLocation,
)
from enterprise_knowledge.domain.errors import AccessViolationError
from enterprise_knowledge.domain.ids import DocumentId
from enterprise_knowledge.domain.ports import Vector
from enterprise_knowledge.domain.retrieval import RetrievedEvidence
from enterprise_knowledge.retrieval.errors import InvalidQueryError
from enterprise_knowledge.retrieval.search import SearchKnowledge
from tests.factories import NOW, TENANT, make_document, make_evidence, make_policy, make_principal
from tests.fakes.document_store import InMemoryDocumentStore
from tests.fakes.embedder import HashEmbedder


async def indexed_store(embedder: HashEmbedder) -> InMemoryDocumentStore:
    store = InMemoryDocumentStore()
    for doc_id, checksum, groups, text in [
        ("handbook", "a" * 64, ("all-staff",), "Giờ làm việc từ 8 giờ 30 đến 17 giờ 30"),
        ("salaries", "b" * 64, ("hr",), "Bảng lương và giờ làm thêm"),
    ]:
        document = make_document(
            id=DocumentId(doc_id), checksum=checksum, access=make_policy(TENANT, *groups)
        )
        await store.add_document(document)
        chunk = DocumentChunk.for_document(document, index=0, text=text, source=SourceLocation())
        [vector] = await embedder.embed_documents([text])
        embedding = Embedding(
            chunk_id=chunk.id, model=embedder.model, dimension=embedder.dimension, vector=vector
        )
        await store.replace_chunks(document, [chunk], [embedding])
        await store.update_document(document.with_status(DocumentStatus.INDEXED, now=NOW))
    return store


async def test_returns_only_accessible_evidence() -> None:
    embedder = HashEmbedder()
    search = SearchKnowledge(search=await indexed_store(embedder), embedder=embedder)

    staff = await search(make_principal(TENANT, "all-staff"), "giờ làm việc", k=5)
    hr = await search(make_principal(TENANT, "hr"), "giờ làm thêm", k=5)

    assert [h.document_id for h in staff] == ["handbook"]
    assert [h.document_id for h in hr] == ["salaries"]


async def test_query_is_nfc_normalized_before_embedding() -> None:
    embedder = HashEmbedder()
    search = SearchKnowledge(search=await indexed_store(embedder), embedder=embedder)

    nfd = unicodedata.normalize("NFD", "giờ làm việc")
    hits = await search(make_principal(), nfd, k=1)

    assert [h.document_id for h in hits] == ["handbook"]


@pytest.mark.parametrize(
    ("query", "k"),
    [("", 5), ("   ", 5), ("...", 5), ("x" * 2001, 5), ("giờ làm", 0), ("giờ làm", 21)],
)
async def test_invalid_queries_are_rejected(query: str, k: int) -> None:
    embedder = HashEmbedder()
    search = SearchKnowledge(search=InMemoryDocumentStore(), embedder=embedder)

    with pytest.raises(InvalidQueryError):
        await search(make_principal(), query, k=k)
    assert embedder.calls == 0


class LeakySearch:
    """An adapter bug: ignores the principal and returns an HR-only chunk."""

    async def search(
        self, principal: Principal, query_vector: Vector, *, k: int, embedding_model: str
    ) -> list[RetrievedEvidence]:
        return [make_evidence("leak", access=make_policy(TENANT, "hr"))]


async def test_adapter_leak_is_detected_not_returned() -> None:
    search = SearchKnowledge(search=LeakySearch(), embedder=HashEmbedder())

    with pytest.raises(AccessViolationError):
        await search(make_principal(TENANT, "all-staff"), "lương", k=3)
