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
from enterprise_knowledge.retrieval.search import RetrievalSettings, SearchKnowledge
from tests.factories import NOW, TENANT, make_document, make_evidence, make_policy, make_principal
from tests.fakes.chunk_search import ScriptedChunkSearch
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

    async def search_lexical(
        self,
        principal: Principal,
        query_text: str,
        query_vector: Vector,
        *,
        k: int,
        embedding_model: str,
    ) -> list[RetrievedEvidence]:
        return [make_evidence("leak", access=make_policy(TENANT, "hr"))]


async def test_adapter_leak_is_detected_not_returned() -> None:
    search = SearchKnowledge(search=LeakySearch(), embedder=HashEmbedder())

    with pytest.raises(AccessViolationError):
        await search(make_principal(TENANT, "all-staff"), "lương", k=3)


@pytest.mark.parametrize("mode", ["vector", "hybrid"])
async def test_lexical_leak_is_detected_in_either_mode(mode: str) -> None:
    search = SearchKnowledge(
        search=LeakySearch(), embedder=HashEmbedder(), retrieval=RetrievalSettings(mode=mode)
    )

    with pytest.raises(AccessViolationError):
        await search(make_principal(TENANT, "all-staff"), "lương", k=3)


# --- hybrid retrieval (ADR-0014) --------------------------------------------------------

HYBRID = RetrievalSettings(mode="hybrid", rrf_k=60, candidates=10)


async def test_vector_mode_never_runs_lexical_search() -> None:
    scripted = ScriptedChunkSearch(vector=[make_evidence("a")], lexical=[make_evidence("b")])
    search = SearchKnowledge(search=scripted, embedder=HashEmbedder())

    hits = await search(make_principal(), "nghỉ phép", k=3)

    assert [h.chunk_id for h in hits] == ["a"]
    assert scripted.lexical_calls == []


async def test_hybrid_mode_fuses_both_rankings() -> None:
    scripted = ScriptedChunkSearch(
        vector=[make_evidence("a", score=0.8), make_evidence("b", score=0.7)],
        lexical=[make_evidence("b", score=0.7), make_evidence("c", score=0.2)],
    )
    search = SearchKnowledge(search=scripted, embedder=HashEmbedder(), retrieval=HYBRID)

    hits = await search(make_principal(), "nghỉ phép Đà Nẵng", k=3)

    assert [h.chunk_id for h in hits] == ["b", "a", "c"]
    assert scripted.vector_calls == [10]
    assert scripted.lexical_calls == [("nghỉ phép Đà Nẵng", 10)]


async def test_hybrid_results_keep_their_cosine_score() -> None:
    scripted = ScriptedChunkSearch(
        vector=[make_evidence("a", score=0.8)], lexical=[make_evidence("c", score=0.2)]
    )
    search = SearchKnowledge(search=scripted, embedder=HashEmbedder(), retrieval=HYBRID)

    hits = await search(make_principal(), "nghỉ phép", k=2)

    assert {h.chunk_id: h.score for h in hits} == {"a": 0.8, "c": 0.2}


async def test_hybrid_returns_at_most_k() -> None:
    scripted = ScriptedChunkSearch(
        vector=[make_evidence(f"v{i}") for i in range(5)],
        lexical=[make_evidence(f"l{i}") for i in range(5)],
    )
    search = SearchKnowledge(search=scripted, embedder=HashEmbedder(), retrieval=HYBRID)

    assert len(await search(make_principal(), "nghỉ phép", k=3)) == 3


async def test_hybrid_candidates_cover_at_least_k() -> None:
    scripted = ScriptedChunkSearch()
    settings = RetrievalSettings(mode="hybrid", candidates=5)
    search = SearchKnowledge(search=scripted, embedder=HashEmbedder(), retrieval=settings)

    await search(make_principal(), "nghỉ phép", k=8)

    assert scripted.vector_calls == [8]
    assert scripted.lexical_calls == [("nghỉ phép", 8)]


@pytest.mark.parametrize(("field", "value"), [("rrf_k", 0), ("candidates", 0), ("mode", "keyword")])
def test_invalid_retrieval_settings_are_rejected(field: str, value: object) -> None:
    with pytest.raises(ValueError, match=field):
        RetrievalSettings.model_validate({field: value})
