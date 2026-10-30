"""Build a corpus manifest and its benchmark's labelled questions (EVAL-01, ADR-0011).

    uv run python scripts/build_benchmark.py --version v1

The authoring source is ``scripts/benchmark_data/<version>.py``. Each question's evidence is
written as (document, short quote from that document); the builder chunks the served version
of each document with the recorded chunking settings and writes, as the relevance label,
every chunk whose text contains the quote. The published dataset is scored on those chunk IDs
only. If chunking settings change, rebuild into a new dataset version instead of editing one.
"""

import argparse
import hashlib
import importlib
import json
import re
import sys
import unicodedata
from pathlib import Path
from types import ModuleType
from typing import Any

from enterprise_knowledge.domain.ids import DocumentId, chunk_id_for
from enterprise_knowledge.evaluation.benchmark import load_benchmark, load_corpus
from enterprise_knowledge.ingestion.chunking import ChunkingSettings
from enterprise_knowledge.ingestion.prepare import prepare_document

ROOT = Path(__file__).resolve().parents[1]
CHUNKING = ChunkingSettings()  # the ingestion defaults: 1200 characters, 150 overlap
VERSIONS = ("v1", "v2")


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", text)).strip()


def write_manifest(data: ModuleType, corpus: Path) -> None:
    lines = []
    for doc_id, version, tenant, title, language, fmt, name, groups in data.MANIFEST:
        source, license_ = data.PROVENANCE.get(doc_id, (data.SOURCE, data.LICENSE))
        lines.append(
            {
                "id": doc_id,
                "version": version,
                "tenant": tenant,
                "title": title,
                "language": language,
                "format": fmt,
                "file": f"docs/{name}",
                "allowed_groups": groups,
                "source": source,
                "license": license_,
                "sha256": hashlib.sha256((corpus / "docs" / name).read_bytes()).hexdigest(),
            }
        )
    (corpus / "manifest.jsonl").write_text(
        "".join(json.dumps(line, ensure_ascii=False) + "\n" for line in lines), encoding="utf-8"
    )


def resolve(
    data: ModuleType,
    corpus: Path,
    doc_id: str,
    quote: str,
    chunks_cache: dict[str, tuple[int, list[str]]],
) -> list[dict[str, Any]]:
    """Every chunk of the served version whose text contains ``quote``."""
    if doc_id not in chunks_cache:
        served = [m for m in data.MANIFEST if m[0] == doc_id][-1]
        prepared = prepare_document(
            (corpus / "docs" / served[6]).read_bytes(), filename=served[6], chunking=CHUNKING
        )
        chunks_cache[doc_id] = (served[1], [normalize(c.text) for c in prepared.chunks])
    version, texts = chunks_cache[doc_id]
    hits = [i for i, text in enumerate(texts) if normalize(quote) in text]
    if not hits:
        raise SystemExit(f"quote not found in {doc_id} v{version}: {quote!r}")
    return [
        {
            "document_id": doc_id,
            "version": version,
            "chunk_index": i,
            "chunk_id": chunk_id_for(DocumentId(doc_id), version, i),
        }
        for i in hits
    ]


def write_questions(data: ModuleType, version: str, corpus: Path, benchmark: Path) -> None:
    cache: dict[str, tuple[int, list[str]]] = {}
    rows = []
    for number, (language, types, principal, question, groups, answer) in enumerate(
        data.QUESTIONS, start=1
    ):
        evidence = []
        for group in groups:
            refs = [
                ref
                for doc_id, quote in group
                for ref in resolve(data, corpus, doc_id, quote, cache)
            ]
            evidence.append(list({r["chunk_id"]: r for r in refs}.values()))
        rows.append(
            {
                "id": f"q{number:03d}",
                "question": question,
                "language": language,
                "types": types,
                "principal": principal,
                "evidence": evidence,
                "reference_answer": answer,
            }
        )
    benchmark.mkdir(parents=True, exist_ok=True)
    (benchmark / "questions.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8"
    )
    metadata = {
        "version": version,
        "corpus_manifest_sha256": hashlib.sha256(
            (corpus / "manifest.jsonl").read_bytes()
        ).hexdigest(),
        "chunking": CHUNKING.model_dump(),
    }
    (benchmark / "benchmark.json").write_text(
        json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--version", choices=VERSIONS, required=True)
    version = parser.parse_args().version
    data = importlib.import_module(f"benchmark_data.{version}")
    corpus = ROOT / "datasets" / "corpus" / version
    benchmark = ROOT / "datasets" / "benchmark" / version
    write_manifest(data, corpus)
    write_questions(data, version, corpus, benchmark)
    dataset = load_benchmark(benchmark, load_corpus(corpus))  # full validation
    print(f"{len(dataset.corpus.documents)} document versions, {len(dataset.questions)} questions")
    return 0


if __name__ == "__main__":
    sys.exit(main())
