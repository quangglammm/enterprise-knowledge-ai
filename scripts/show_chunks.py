"""Show how a corpus document is chunked, to write or check benchmark labels (ADR-0011).

    uv run python scripts/show_chunks.py hr-expense-policy            # served version
    uv run python scripts/show_chunks.py hr-expense-policy --version 1 --max-chars 800

Prints each chunk's index, chunk ID, page and section, and its text. Uses the same
preparation code as ingestion, with the benchmark's recorded chunking settings unless
overridden. The corpus is synthetic, so printing its text is fine.
"""

import argparse
import sys
from pathlib import Path

from enterprise_knowledge.domain.ids import DocumentId, chunk_id_for
from enterprise_knowledge.evaluation.benchmark import BenchmarkMetadata, load_corpus
from enterprise_knowledge.ingestion.chunking import ChunkingSettings
from enterprise_knowledge.ingestion.prepare import prepare_document

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("document_id")
    parser.add_argument("--version", type=int)
    parser.add_argument("--corpus", type=Path, default=ROOT / "datasets" / "corpus" / "v2")
    parser.add_argument("--benchmark", type=Path, default=ROOT / "datasets" / "benchmark" / "v2")
    parser.add_argument("--max-chars", type=int)
    parser.add_argument("--overlap-chars", type=int)
    args = parser.parse_args()

    corpus = load_corpus(args.corpus)
    versions = [d for d in corpus.documents if d.id == args.document_id]
    if not versions:
        print(f"unknown document {args.document_id}")
        return 2
    document = next((d for d in versions if d.version == args.version), versions[-1])
    metadata_file = args.benchmark / "benchmark.json"
    chunking = (
        BenchmarkMetadata.model_validate_json(metadata_file.read_text("utf-8")).chunking
        if metadata_file.exists()
        else ChunkingSettings()
    )
    chunking = ChunkingSettings(
        max_chars=args.max_chars or chunking.max_chars,
        overlap_chars=args.overlap_chars
        if args.overlap_chars is not None
        else chunking.overlap_chars,
    )
    prepared = prepare_document(
        corpus.read(document), filename=Path(document.file).name, chunking=chunking
    )
    print(f"{document.id} v{document.version} ({document.file}) {chunking.model_dump()}")
    for draft in prepared.chunks:
        chunk_id = chunk_id_for(DocumentId(document.id), document.version, draft.index)
        print(f"\n#{draft.index} {chunk_id} page={draft.page} section={draft.section!r}")
        print(draft.text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
