"""The real benchmark on the production search path: Postgres, pgvector, filtered HNSW.

Uses the dev hashing embedder, so the numbers are deterministic and free; they measure the
pipeline, not retrieval quality (ADR-0011).
"""

from pathlib import Path

import pytest

from enterprise_knowledge.domain.ids import DocumentId, chunk_id_for
from enterprise_knowledge.evaluation.benchmark import (
    BenchmarkDataset,
    BenchmarkReport,
    QuestionType,
    chunk_count,
    index_corpus,
    load_benchmark,
    load_corpus,
    run_retrieval_benchmark,
)
from enterprise_knowledge.infrastructure.blobs import LocalBlobStore
from enterprise_knowledge.infrastructure.embeddings.hashing import HashingEmbedder
from enterprise_knowledge.infrastructure.postgres.store import PostgresDocumentStore
from enterprise_knowledge.retrieval.search import SearchKnowledge
from tests.contract.conftest import reset_database

pytestmark = pytest.mark.integration

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def dataset() -> BenchmarkDataset:
    corpus = load_corpus(REPO / "datasets" / "corpus" / "v1")
    return load_benchmark(REPO / "datasets" / "benchmark" / "v1", corpus)


async def run_on_postgres(
    url: str, dataset: BenchmarkDataset, blob_dir: Path
) -> tuple[BenchmarkReport, BenchmarkReport]:
    await reset_database(url)
    embedder = HashingEmbedder()
    store = await PostgresDocumentStore.connect(url, embedding_dimension=embedder.dimension)
    try:
        await index_corpus(
            dataset.corpus,
            documents=store,
            embedder=embedder,
            blobs=LocalBlobStore(blob_dir),
            chunking=dataset.chunking,
        )
        search = SearchKnowledge(search=store, embedder=embedder)
        first = await run_retrieval_benchmark(dataset, search, embedding_model=embedder.model)
        second = await run_retrieval_benchmark(dataset, search, embedding_model=embedder.model)
    finally:
        await store.close()
    return first, second


async def test_full_benchmark_runs_on_postgres_deterministically(
    postgres_url: str, dataset: BenchmarkDataset, tmp_path: Path
) -> None:
    first, second = await run_on_postgres(postgres_url, dataset, tmp_path)

    assert first.model_dump(exclude={"started_at"}) == second.model_dump(exclude={"started_at"})
    assert (first.questions, first.answerable, first.unanswerable) == (50, 44, 6)
    assert first.access_violations == 0
    assert first.embedding_model == "hashing-v1"
    for value in first.recall_at_k.values():
        assert value is not None
        assert 0.0 <= value <= 1.0
    assert first.by_type[QuestionType.TENANT_ISOLATION].questions == 2


async def test_restricted_and_other_tenant_chunks_never_rank(
    postgres_url: str, dataset: BenchmarkDataset, tmp_path: Path
) -> None:
    report, _ = await run_on_postgres(postgres_url, dataset, tmp_path)

    readable = {question.id: question.principal.principal() for question in dataset.questions}
    documents_by_chunk = {
        chunk_id: document
        for document in dataset.corpus.documents
        for chunk_id in _chunk_ids(dataset, document.id, document.version)
    }
    for result in report.results:
        for chunk_id in result.ranked:
            document = documents_by_chunk[chunk_id]
            assert readable[result.question_id].can_access(document.access), (
                result.question_id,
                document.id,
            )


def _chunk_ids(dataset: BenchmarkDataset, document_id: str, version: int) -> list[str]:
    document = next(
        d for d in dataset.corpus.documents if d.id == document_id and d.version == version
    )
    count = chunk_count(dataset.corpus, document, dataset.chunking)
    return [chunk_id_for(DocumentId(document_id), version, i) for i in range(count)]
