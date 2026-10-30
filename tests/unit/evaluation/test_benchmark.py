"""Benchmark loading, validation and the retrieval run (EVAL-01), on a tiny corpus."""

import hashlib
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from enterprise_knowledge.domain.access import Principal
from enterprise_knowledge.domain.ids import DocumentId, GroupId, chunk_id_for
from enterprise_knowledge.domain.ports import Vector
from enterprise_knowledge.domain.retrieval import RetrievedEvidence
from enterprise_knowledge.evaluation.benchmark import (
    BenchmarkDataset,
    QuestionType,
    index_corpus,
    load_benchmark,
    load_corpus,
    run_retrieval_benchmark,
)
from enterprise_knowledge.evaluation.experiment import ExperimentConfig
from enterprise_knowledge.retrieval.search import SearchKnowledge
from tests.fakes.blob_store import InMemoryBlobStore
from tests.fakes.document_store import InMemoryDocumentStore
from tests.fakes.embedder import HashEmbedder

REPO = Path(__file__).resolve().parents[3]

DOCS = {
    "leave-v1.md": "# Leave policy\n\nEmployees get 12 days of annual leave.\n",
    "leave-v2.md": "# Leave policy\n\nEmployees get 14 days of annual leave.\n",
    "vpn.md": "# VPN guide\n\nRestart the network adapter when the VPN client shows error 809.\n",
    "salary.md": "# Salary review\n\nSalary reviews happen every April.\n",
    "other.md": "# Other tenant leave\n\nStaff at the other company get 15 days of annual leave.\n",
}
MANIFEST = [
    ("leave", 1, "bamboo", ["all-staff"], "leave-v1.md"),
    ("leave", 2, "bamboo", ["all-staff"], "leave-v2.md"),
    ("vpn", 1, "bamboo", ["all-staff"], "vpn.md"),
    ("salary", 1, "bamboo", ["hr"], "salary.md"),
    ("other-leave", 1, "lotus", ["all-staff"], "other.md"),
]


def ref(document: str, version: int, index: int = 0) -> dict[str, Any]:
    return {
        "document_id": document,
        "version": version,
        "chunk_index": index,
        "chunk_id": chunk_id_for(DocumentId(document), version, index),
    }


STAFF = {"tenant": "bamboo", "groups": ["all-staff"]}
QUESTIONS: list[dict[str, Any]] = [
    {
        "id": "q001",
        "question": "How many days of annual leave do employees get?",
        "language": "en",
        "types": ["english", "version-sensitive"],
        "principal": STAFF,
        "evidence": [[ref("leave", 2)]],
        "reference_answer": "14 days.",
    },
    {
        "id": "q002",
        "question": "What should I do about VPN error 809 and how much leave do I get?",
        "language": "en",
        "types": ["english", "multi-document"],
        "principal": STAFF,
        "evidence": [[ref("vpn", 1)], [ref("leave", 2)]],
        "reference_answer": "Restart the network adapter; 14 days of leave.",
    },
    {
        "id": "q003",
        "question": "When do salary reviews happen?",
        "language": "en",
        "types": ["english", "access-sensitive", "unanswerable"],
        "principal": STAFF,
        "evidence": [],
        "reference_answer": None,
    },
    {
        "id": "q004",
        "question": "When do salary reviews happen?",
        "language": "en",
        "types": ["english", "access-sensitive"],
        "principal": {"tenant": "bamboo", "groups": ["hr"]},
        "evidence": [[ref("salary", 1)]],
        "reference_answer": "Every April.",
    },
]


def write_corpus(
    root: Path, manifest: Sequence[tuple[str, int, str, list[str], str]] = MANIFEST
) -> Path:
    docs = root / "corpus" / "docs"
    docs.mkdir(parents=True)
    lines = []
    for name, text in DOCS.items():
        (docs / name).write_text(text, encoding="utf-8")
    for doc_id, version, tenant, groups, name in manifest:
        data = (docs / name).read_bytes()
        lines.append(
            json.dumps(
                {
                    "id": doc_id,
                    "version": version,
                    "tenant": tenant,
                    "title": doc_id,
                    "language": "en",
                    "format": "md",
                    "file": f"docs/{name}",
                    "allowed_groups": groups,
                    "source": "synthetic",
                    "license": "CC0-1.0",
                    "sha256": hashlib.sha256(data).hexdigest(),
                }
            )
        )
    (root / "corpus" / "manifest.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return root / "corpus"


def write_benchmark(
    root: Path, corpus_dir: Path, questions: Sequence[dict[str, Any]] = QUESTIONS
) -> Path:
    bench = root / "benchmark"
    bench.mkdir()
    manifest_sha = hashlib.sha256((corpus_dir / "manifest.jsonl").read_bytes()).hexdigest()
    metadata = {
        "version": "v1",
        "corpus_manifest_sha256": manifest_sha,
        "chunking": {"max_chars": 1200, "overlap_chars": 150},
    }
    (bench / "benchmark.json").write_text(json.dumps(metadata), encoding="utf-8")
    (bench / "questions.jsonl").write_text(
        "".join(json.dumps(q) + "\n" for q in questions), encoding="utf-8"
    )
    return bench


@pytest.fixture
def dataset(tmp_path: Path) -> BenchmarkDataset:
    corpus_dir = write_corpus(tmp_path)
    return load_benchmark(write_benchmark(tmp_path, corpus_dir), load_corpus(corpus_dir))


# --- loading and validation -----------------------------------------------------------


def test_valid_benchmark_loads(dataset: BenchmarkDataset) -> None:
    assert [q.id for q in dataset.questions] == ["q001", "q002", "q003", "q004"]
    assert dataset.questions[2].answerable is False
    assert len(dataset.corpus.documents) == 5


def test_corpus_file_that_changed_is_rejected(tmp_path: Path) -> None:
    corpus_dir = write_corpus(tmp_path)
    (corpus_dir / "docs" / "vpn.md").write_text("tampered", encoding="utf-8")

    with pytest.raises(ValueError, match="sha256"):
        load_corpus(corpus_dir)


def test_versions_must_be_listed_in_order(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="version"):
        load_corpus(write_corpus(tmp_path, [MANIFEST[1], MANIFEST[0]]))


def test_benchmark_for_another_corpus_is_rejected(tmp_path: Path) -> None:
    corpus_dir = write_corpus(tmp_path)
    bench = write_benchmark(tmp_path, corpus_dir)
    metadata = json.loads((bench / "benchmark.json").read_text())
    (bench / "benchmark.json").write_text(
        json.dumps(metadata | {"corpus_manifest_sha256": "0" * 64})
    )

    with pytest.raises(ValueError, match="manifest"):
        load_benchmark(bench, load_corpus(corpus_dir))


@pytest.mark.parametrize(
    ("evidence", "message"),
    [
        ([[ref("missing", 1)]], "unknown document"),
        ([[ref("leave", 1)]], "served version"),
        ([[ref("salary", 1)]], "cannot read"),
        ([[ref("other-leave", 1)]], "cannot read"),
        ([[ref("vpn", 1, index=7)]], "chunk index 7"),
        ([[ref("vpn", 1) | {"chunk_id": "0" * 32}]], "chunk_id"),
    ],
    ids=[
        "unknown-doc",
        "superseded-version",
        "other-group",
        "other-tenant",
        "no-such-chunk",
        "bad-id",
    ],
)
def test_impossible_evidence_is_rejected(
    tmp_path: Path, evidence: list[list[dict[str, Any]]], message: str
) -> None:
    corpus_dir = write_corpus(tmp_path)
    question = QUESTIONS[0] | {"evidence": evidence}

    with pytest.raises(ValueError, match=message):
        load_benchmark(write_benchmark(tmp_path, corpus_dir, [question]), load_corpus(corpus_dir))


def test_unanswerable_type_must_match_empty_evidence(tmp_path: Path) -> None:
    corpus_dir = write_corpus(tmp_path)
    question = QUESTIONS[0] | {"types": ["english", "unanswerable"]}

    with pytest.raises(ValueError, match="unanswerable"):
        load_benchmark(write_benchmark(tmp_path, corpus_dir, [question]), load_corpus(corpus_dir))


def test_question_ids_must_be_unique(tmp_path: Path) -> None:
    corpus_dir = write_corpus(tmp_path)

    with pytest.raises(ValueError, match="duplicate"):
        load_benchmark(
            write_benchmark(tmp_path, corpus_dir, [QUESTIONS[0], QUESTIONS[0]]),
            load_corpus(corpus_dir),
        )


# --- the run --------------------------------------------------------------------------


async def indexed(dataset: BenchmarkDataset) -> tuple[InMemoryDocumentStore, HashEmbedder]:
    store, embedder = InMemoryDocumentStore(), HashEmbedder()
    await index_corpus(
        dataset.corpus,
        documents=store,
        embedder=embedder,
        blobs=InMemoryBlobStore(),
        chunking=dataset.chunking,
    )
    return store, embedder


async def test_corpus_is_indexed_with_stable_ids_and_versions(dataset: BenchmarkDataset) -> None:
    store, _ = await indexed(dataset)

    leave = await store.get_document(
        dataset.corpus.documents[0].access.tenant_id, DocumentId("leave")
    )

    assert leave is not None
    assert leave.version == 2
    assert [c.id for c in await store.list_chunks(leave.tenant_id, leave.id, 2)] == [
        chunk_id_for(DocumentId("leave"), 2, 0)
    ]


async def test_run_scores_answerable_questions_and_separates_unanswerable(
    dataset: BenchmarkDataset,
) -> None:
    store, embedder = await indexed(dataset)

    report = await run_retrieval_benchmark(
        dataset, SearchKnowledge(search=store, embedder=embedder), k_values=(1, 5)
    )

    assert report.questions == 4
    assert report.answerable == 3
    assert report.unanswerable == 1
    assert report.access_violations == 0
    assert set(report.recall_at_k) == {1, 5}
    assert report.recall_at_k[5] == 1.0  # the tiny corpus has 4 visible chunks at most
    assert report.mrr is not None
    assert 0.0 < report.mrr <= 1.0
    by_type = report.by_type[QuestionType.MULTI_DOCUMENT]
    assert by_type.questions == 1
    unanswerable = next(r for r in report.results if r.question_id == "q003")
    assert unanswerable.recall_at_k is None
    assert unanswerable.reciprocal_rank is None
    assert chunk_id_for(DocumentId("salary"), 1, 0) not in unanswerable.ranked


async def test_report_records_the_experiment_and_code_revision(
    dataset: BenchmarkDataset,
) -> None:
    store, embedder = await indexed(dataset)
    experiment = ExperimentConfig(name="baseline", corpus="v1", benchmark="v1", embedding="hashing")

    report = await run_retrieval_benchmark(
        dataset,
        SearchKnowledge(search=store, embedder=embedder),
        experiment=experiment,
        code_revision="abc1234",
    )

    assert report.experiment == experiment
    assert report.code_revision == "abc1234"


async def test_corpus_can_be_indexed_without_the_embedding_header(
    dataset: BenchmarkDataset,
) -> None:
    store, embedder = InMemoryDocumentStore(), HashEmbedder()

    await index_corpus(
        dataset.corpus,
        documents=store,
        embedder=embedder,
        blobs=InMemoryBlobStore(),
        chunking=dataset.chunking,
        embedding_header=False,
    )

    assert embedder.document_inputs[0] == "Leave policy\n\nEmployees get 12 days of annual leave."


async def test_run_is_deterministic(dataset: BenchmarkDataset) -> None:
    store, embedder = await indexed(dataset)
    search = SearchKnowledge(search=store, embedder=embedder)

    first = await run_retrieval_benchmark(dataset, search, k_values=(1, 3))
    second = await run_retrieval_benchmark(dataset, search, k_values=(1, 3))

    assert first.model_dump(exclude={"started_at"}) == second.model_dump(exclude={"started_at"})


class _IgnoresAccess(InMemoryDocumentStore):
    """A broken adapter that searches as an all-powerful principal."""

    async def search(
        self, principal: Principal, query_vector: Vector, *, k: int, embedding_model: str
    ) -> list[RetrievedEvidence]:
        everyone = Principal(
            tenant_id=principal.tenant_id,
            user_id=principal.user_id,
            groups=frozenset({GroupId("all-staff"), GroupId("hr")}),
        )
        return await super().search(everyone, query_vector, k=k, embedding_model=embedding_model)


async def test_a_leaking_search_is_counted_not_hidden(dataset: BenchmarkDataset) -> None:
    store, embedder = _IgnoresAccess(), HashEmbedder()
    await index_corpus(
        dataset.corpus,
        documents=store,
        embedder=embedder,
        blobs=InMemoryBlobStore(),
        chunking=dataset.chunking,
    )

    report = await run_retrieval_benchmark(
        dataset, SearchKnowledge(search=store, embedder=embedder), k_values=(5,)
    )

    assert report.access_violations >= 1
    leaked = next(r for r in report.results if r.question_id == "q003")
    assert leaked.access_violation


def test_bundled_benchmark_and_corpus_are_consistent() -> None:
    corpus = load_corpus(REPO / "datasets" / "corpus" / "v1")
    dataset = load_benchmark(REPO / "datasets" / "benchmark" / "v1", corpus)

    types = [t for q in dataset.questions for t in q.types]
    assert len(dataset.questions) == 50
    for required in set(QuestionType) - {QuestionType.NEAR_DUPLICATE}:  # added in v2
        assert required in types, required
    assert sum(1 for q in dataset.questions if not q.answerable) >= 6
    assert {d.tenant for d in corpus.documents} == {"bamboo-harbor", "lotus-retail"}
    assert sum(1 for d in corpus.documents if d.version > 1) >= 3


def test_bundled_benchmark_v2_meets_corpus_v2_targets() -> None:
    corpus = load_corpus(REPO / "datasets" / "corpus" / "v2")
    dataset = load_benchmark(REPO / "datasets" / "benchmark" / "v2", corpus)

    served = [d for d in corpus.documents if corpus.served(d.id) == d]
    types = [t for q in dataset.questions for t in q.types]
    assert len(served) >= 45
    assert len({d.id for d in corpus.documents if d.version > 1}) >= 5
    assert sum(1 for d in served if "all-staff" not in d.allowed_groups) >= 10
    assert sum(1 for d in served if d.source.startswith("public:")) >= 2
    assert sum(1 for d in served if d.language == "vi") / len(served) >= 0.5
    assert len(dataset.questions) >= 100
    assert sum(1 for q in dataset.questions if not q.answerable) >= 10
    for required in QuestionType:
        assert required in types, required


def test_benchmark_v2_keeps_every_v1_question_and_document() -> None:
    v1 = load_benchmark(
        REPO / "datasets" / "benchmark" / "v1", load_corpus(REPO / "datasets" / "corpus" / "v1")
    )
    v2 = load_benchmark(
        REPO / "datasets" / "benchmark" / "v2", load_corpus(REPO / "datasets" / "corpus" / "v2")
    )

    v2_questions = {(q.id, q.question, q.principal.model_dump_json()) for q in v2.questions}
    assert {(q.id, q.question, q.principal.model_dump_json()) for q in v1.questions} <= v2_questions
    v2_files = {(d.id, d.version, d.sha256) for d in v2.corpus.documents}
    assert {(d.id, d.version, d.sha256) for d in v1.corpus.documents} <= v2_files


@pytest.mark.parametrize("label_set", ["v2-packed1200", "v2-packed800"])
def test_derived_label_sets_cover_benchmark_v2_questions_under_their_chunking(
    label_set: str,
) -> None:
    corpus = load_corpus(REPO / "datasets" / "corpus" / "v2")
    base = load_benchmark(REPO / "datasets" / "benchmark" / "v2", corpus)

    derived = load_benchmark(REPO / "datasets" / "benchmark" / label_set, corpus)

    assert derived.version == label_set
    assert derived.chunking.pack_sections
    assert [(q.id, q.question, q.answerable) for q in derived.questions] == [
        (q.id, q.question, q.answerable) for q in base.questions
    ]
