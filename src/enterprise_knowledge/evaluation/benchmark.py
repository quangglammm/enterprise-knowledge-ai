"""Retrieval benchmark (EVAL-01, ADR-0011): versioned corpus, chunk-labelled questions.

The corpus manifest pins every file by sha256; the benchmark pins the manifest and the
chunking settings its labels were made with. Loading refuses anything inconsistent: a
changed file, a label for a chunk that does not exist under those settings, evidence the
asking principal cannot read, or evidence on a superseded version. A chunking change
therefore fails loudly instead of silently scoring zero.
"""

import hashlib
import json
from collections.abc import Callable, Iterable, Sequence
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from enterprise_knowledge.domain.access import AccessPolicy, Principal
from enterprise_knowledge.domain.errors import AccessViolationError
from enterprise_knowledge.domain.ids import (
    ChunkId,
    DocumentId,
    GroupId,
    TenantId,
    UserId,
    chunk_id_for,
)
from enterprise_knowledge.domain.ports import BlobStore, DocumentRepository, Embedder
from enterprise_knowledge.evaluation.retrieval_metrics import mean, recall_at_k, reciprocal_rank
from enterprise_knowledge.ingestion.chunking import ChunkingSettings
from enterprise_knowledge.ingestion.ingest import IngestDocument
from enterprise_knowledge.ingestion.prepare import prepare_document
from enterprise_knowledge.retrieval.search import SearchKnowledge

_SLUG = r"^[a-z0-9][a-z0-9-]{0,63}$"
BENCHMARK_USER = UserId("benchmark")


class CorpusDocument(BaseModel):
    """One document version in ``manifest.jsonl``."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(pattern=_SLUG)
    version: int = Field(ge=1)
    tenant: str = Field(pattern=_SLUG)
    title: str = Field(min_length=1)
    language: Literal["vi", "en", "mixed"]
    format: Literal["pdf", "docx", "html", "md"]
    file: str = Field(min_length=1)
    allowed_groups: list[str] = Field(min_length=1)
    source: str = Field(min_length=1)
    license: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @property
    def access(self) -> AccessPolicy:
        return AccessPolicy(
            tenant_id=TenantId(self.tenant),
            allowed_groups=frozenset(GroupId(g) for g in self.allowed_groups),
        )


class Corpus(BaseModel):
    model_config = ConfigDict(frozen=True)

    root: Path
    manifest_sha256: str
    documents: tuple[CorpusDocument, ...]

    def served(self, document_id: str) -> CorpusDocument | None:
        """The version search serves after indexing: the highest one (ADR-0007)."""
        versions = [d for d in self.documents if d.id == document_id]
        return max(versions, key=lambda d: d.version, default=None)

    def read(self, document: CorpusDocument) -> bytes:
        return (self.root / document.file).read_bytes()


class QuestionType(StrEnum):
    VIETNAMESE = "vietnamese"
    ENGLISH = "english"
    CROSS_LINGUAL = "cross-lingual"
    MULTI_DOCUMENT = "multi-document"
    VERSION_SENSITIVE = "version-sensitive"
    ACCESS_SENSITIVE = "access-sensitive"
    TENANT_ISOLATION = "tenant-isolation"
    UNANSWERABLE = "unanswerable"


class ChunkRef(BaseModel):
    """A relevance label: a chunk, written readably and checked against its derived ID."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    document_id: str
    version: int = Field(ge=1)
    chunk_index: int = Field(ge=0)
    chunk_id: str

    @model_validator(mode="after")
    def _id_matches(self) -> Self:
        expected = chunk_id_for(DocumentId(self.document_id), self.version, self.chunk_index)
        if self.chunk_id != expected:
            raise ValueError(f"chunk_id of {self.document_id} v{self.version}#{self.chunk_index}")
        return self


class BenchmarkPrincipal(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    tenant: str = Field(pattern=_SLUG)
    groups: list[str] = Field(min_length=1)

    def principal(self) -> Principal:
        return Principal(
            tenant_id=TenantId(self.tenant),
            user_id=BENCHMARK_USER,
            groups=frozenset(GroupId(g) for g in self.groups),
        )


class BenchmarkQuestion(BaseModel):
    """``evidence`` is a list of groups; each group is satisfied by any one of its chunks."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(pattern=r"^q\d{3}$")
    question: str = Field(min_length=1)
    language: Literal["vi", "en"]
    types: list[QuestionType] = Field(min_length=1)
    principal: BenchmarkPrincipal
    evidence: list[list[ChunkRef]]
    reference_answer: str | None

    @model_validator(mode="after")
    def _unanswerable_has_no_evidence(self) -> Self:
        unanswerable = QuestionType.UNANSWERABLE in self.types
        if unanswerable != (not self.evidence):
            raise ValueError(f"{self.id}: unanswerable must be set exactly when evidence is empty")
        if any(not group for group in self.evidence):
            raise ValueError(f"{self.id}: empty evidence group")
        if (self.reference_answer is None) != unanswerable:
            raise ValueError(f"{self.id}: only unanswerable questions omit reference_answer")
        return self

    @property
    def answerable(self) -> bool:
        return bool(self.evidence)

    def groups(self) -> list[set[ChunkId]]:
        return [{ChunkId(ref.chunk_id) for ref in group} for group in self.evidence]


class BenchmarkMetadata(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    version: str
    corpus_manifest_sha256: str
    chunking: ChunkingSettings


class BenchmarkDataset(BaseModel):
    model_config = ConfigDict(frozen=True)

    version: str
    corpus: Corpus
    chunking: ChunkingSettings
    questions: tuple[BenchmarkQuestion, ...]


class QuestionResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    question_id: str
    types: list[QuestionType]
    answerable: bool
    ranked: list[str]
    recall_at_k: dict[int, float] | None = None
    reciprocal_rank: float | None = None
    top_score: float | None = None
    access_violation: bool = False


class TypeBreakdown(BaseModel):
    model_config = ConfigDict(frozen=True)

    questions: int
    answerable: int
    recall_at_k: dict[int, float | None]
    mrr: float | None


class BenchmarkReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    started_at: datetime
    dataset_version: str
    corpus_manifest_sha256: str
    chunking: ChunkingSettings
    embedding_model: str | None
    k_values: list[int]
    questions: int
    answerable: int
    unanswerable: int
    access_violations: int
    recall_at_k: dict[int, float | None]
    mrr: float | None
    by_type: dict[QuestionType, TypeBreakdown]
    # Calibration data for the evidence score gate (EKA_ANSWER_MIN_SCORE, Week 4).
    top_score_answerable_mean: float | None
    top_score_unanswerable_mean: float | None
    results: list[QuestionResult]


def load_corpus(root: Path) -> Corpus:
    manifest = root / "manifest.jsonl"
    raw = manifest.read_bytes()
    documents = tuple(
        CorpusDocument.model_validate_json(line)
        for line in raw.decode("utf-8").splitlines()
        if line.strip()
    )
    seen: dict[str, CorpusDocument] = {}
    for document in documents:
        actual = hashlib.sha256((root / document.file).read_bytes()).hexdigest()
        if actual != document.sha256:
            raise ValueError(f"{document.file}: sha256 does not match the manifest")
        previous = seen.get(document.id)
        expected_version = previous.version + 1 if previous else 1
        if document.version != expected_version:
            raise ValueError(
                f"{document.id}: version {document.version}, expected {expected_version}"
            )
        if previous and previous.tenant != document.tenant:
            raise ValueError(f"{document.id}: versions must share a tenant")
        seen[document.id] = document
    return Corpus(root=root, manifest_sha256=hashlib.sha256(raw).hexdigest(), documents=documents)


def load_benchmark(root: Path, corpus: Corpus) -> BenchmarkDataset:
    metadata = BenchmarkMetadata.model_validate_json((root / "benchmark.json").read_text("utf-8"))
    if metadata.corpus_manifest_sha256 != corpus.manifest_sha256:
        raise ValueError("benchmark was labelled against a different corpus manifest")
    questions = tuple(
        BenchmarkQuestion.model_validate_json(line)
        for line in (root / "questions.jsonl").read_text("utf-8").splitlines()
        if line.strip()
    )
    ids = [q.id for q in questions]
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    if duplicates:
        raise ValueError(f"duplicate question ids: {duplicates}")
    _check_labels(questions, corpus, metadata.chunking)
    return BenchmarkDataset(
        version=metadata.version, corpus=corpus, chunking=metadata.chunking, questions=questions
    )


def chunk_count(corpus: Corpus, document: CorpusDocument, chunking: ChunkingSettings) -> int:
    """Chunks a document version yields under ``chunking``: same code path as ingestion."""
    prepared = prepare_document(
        corpus.read(document), filename=Path(document.file).name, chunking=chunking
    )
    return len(prepared.chunks)


async def index_corpus(
    corpus: Corpus,
    *,
    documents: DocumentRepository,
    embedder: Embedder,
    blobs: BlobStore,
    chunking: ChunkingSettings,
) -> None:
    """Ingest every version in manifest order with its manifest ID, so labels resolve."""
    for document in corpus.documents:
        ingest = IngestDocument(
            documents=documents,
            embedder=embedder,
            blobs=blobs,
            chunking=chunking,
            new_document_id=_fixed_id(document.id),
        )
        await ingest(
            data=corpus.read(document),
            filename=Path(document.file).name,
            access=document.access,
            document_id=DocumentId(document.id) if document.version > 1 else None,
            title=document.title,
        )


async def run_retrieval_benchmark(
    dataset: BenchmarkDataset,
    search: SearchKnowledge,
    *,
    k_values: Sequence[int] = (1, 3, 5, 10),
    embedding_model: str | None = None,
) -> BenchmarkReport:
    started_at = datetime.now(UTC)
    ks = sorted(set(k_values))
    results = [await _run_question(question, search, ks) for question in dataset.questions]
    answerable = [r for r in results if r.answerable]
    return BenchmarkReport(
        started_at=started_at,
        dataset_version=dataset.version,
        corpus_manifest_sha256=dataset.corpus.manifest_sha256,
        chunking=dataset.chunking,
        embedding_model=embedding_model,
        k_values=ks,
        questions=len(results),
        answerable=len(answerable),
        unanswerable=len(results) - len(answerable),
        access_violations=sum(r.access_violation for r in results),
        recall_at_k=_recall_means(answerable, ks),
        mrr=mean(r.reciprocal_rank for r in answerable if r.reciprocal_rank is not None),
        by_type={
            question_type: _breakdown([r for r in results if question_type in r.types], ks)
            for question_type in QuestionType
        },
        top_score_answerable_mean=_round(
            mean(r.top_score for r in answerable if r.top_score is not None)
        ),
        top_score_unanswerable_mean=_round(
            mean(r.top_score for r in results if not r.answerable and r.top_score is not None)
        ),
        results=results,
    )


async def _run_question(
    question: BenchmarkQuestion, search: SearchKnowledge, ks: Sequence[int]
) -> QuestionResult:
    try:
        hits = await search(question.principal.principal(), question.question, k=max(ks))
    except AccessViolationError:
        # The search returned content this principal may not read. Never hide it.
        return QuestionResult(
            question_id=question.id,
            types=question.types,
            answerable=question.answerable,
            ranked=[],
            access_violation=True,
        )
    ranked = [ChunkId(h.chunk_id) for h in hits]
    top_score = round(hits[0].score, 6) if hits else None
    if not question.answerable:
        return QuestionResult(
            question_id=question.id,
            types=question.types,
            answerable=False,
            ranked=list(ranked),
            top_score=top_score,
        )
    groups = question.groups()
    return QuestionResult(
        question_id=question.id,
        types=question.types,
        answerable=True,
        ranked=list(ranked),
        recall_at_k={k: recall_at_k(ranked, groups, k=k) for k in ks},
        reciprocal_rank=reciprocal_rank(ranked, groups),
        top_score=top_score,
    )


def _fixed_id(document_id: str) -> Callable[[], DocumentId]:
    """New documents get their manifest ID instead of a random one, so labels resolve."""
    return lambda: DocumentId(document_id)


def _check_labels(
    questions: Iterable[BenchmarkQuestion], corpus: Corpus, chunking: ChunkingSettings
) -> None:
    counts: dict[tuple[str, int], int] = {}
    for question in questions:
        principal = question.principal.principal()
        for ref in (ref for group in question.evidence for ref in group):
            served = corpus.served(ref.document_id)
            if served is None:
                raise ValueError(f"{question.id}: unknown document {ref.document_id}")
            if ref.version != served.version:
                raise ValueError(
                    f"{question.id}: {ref.document_id} v{ref.version} is not the served version "
                    f"v{served.version}"
                )
            if not principal.can_access(served.access):
                raise ValueError(f"{question.id}: its principal cannot read {ref.document_id}")
            key = (served.id, served.version)
            if key not in counts:
                counts[key] = chunk_count(corpus, served, chunking)
            if ref.chunk_index >= counts[key]:
                raise ValueError(
                    f"{question.id}: {ref.document_id} v{ref.version} has no chunk index "
                    f"{ref.chunk_index} under {chunking.model_dump()} (it has {counts[key]})"
                )


def _recall_means(results: Sequence[QuestionResult], ks: Sequence[int]) -> dict[int, float | None]:
    return {
        k: _round(mean(r.recall_at_k[k] for r in results if r.recall_at_k is not None)) for k in ks
    }


def _breakdown(results: Sequence[QuestionResult], ks: Sequence[int]) -> TypeBreakdown:
    answerable = [r for r in results if r.answerable]
    return TypeBreakdown(
        questions=len(results),
        answerable=len(answerable),
        recall_at_k=_recall_means(answerable, ks),
        mrr=_round(mean(r.reciprocal_rank for r in answerable if r.reciprocal_rank is not None)),
    )


def _round(value: float | None) -> float | None:
    return None if value is None else round(value, 4)


def dump_report(report: BenchmarkReport, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n", "utf-8"
    )
