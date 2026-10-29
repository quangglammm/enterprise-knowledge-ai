"""Run the EVAL-01 retrieval benchmark on Postgres (ADR-0011).

    uv run python scripts/run_benchmark.py --database-url postgresql://eka:eka@localhost:5432/eka_test
    uv run python scripts/run_benchmark.py --database-url ... --embedding fpt   # paid calls

Migrates and WIPES the given database, indexes corpus v1 through the production ingestion
path with stable document IDs, runs every question as its principal, and writes a report
to docs/evaluation/. Refuses to touch the app database (EKA_DATABASE_URL). The hashing
embedder measures the pipeline only; real retrieval quality needs --embedding fpt.
"""

import argparse
import asyncio
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from enterprise_knowledge.config import get_settings
from enterprise_knowledge.domain.ports import Embedder
from enterprise_knowledge.evaluation.benchmark import (
    BenchmarkReport,
    QuestionType,
    dump_report,
    index_corpus,
    load_benchmark,
    load_corpus,
    run_retrieval_benchmark,
)
from enterprise_knowledge.infrastructure.blobs import LocalBlobStore
from enterprise_knowledge.infrastructure.embeddings.hashing import HashingEmbedder
from enterprise_knowledge.infrastructure.fpt.client import FptClient, RetryPolicy
from enterprise_knowledge.infrastructure.fpt.embeddings import FptEmbedder
from enterprise_knowledge.infrastructure.postgres.migrate import migrate, wipe_documents
from enterprise_knowledge.infrastructure.postgres.store import PostgresDocumentStore
from enterprise_knowledge.retrieval.search import SearchKnowledge

ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--database-url", required=True, help="a database this run may wipe")
    parser.add_argument(
        "--embedding", choices=["hashing", "fpt"], help="default: EKA_EMBEDDING_PROVIDER"
    )
    parser.add_argument("--k", default="1,3,5,10", help="comma-separated k values")
    parser.add_argument("--corpus", type=Path, default=ROOT / "datasets" / "corpus" / "v1")
    parser.add_argument("--benchmark", type=Path, default=ROOT / "datasets" / "benchmark" / "v1")
    parser.add_argument("--out", type=Path, help="report path (default: docs/evaluation/...)")
    return parser.parse_args()


def print_report(report: BenchmarkReport) -> None:
    def pct(value: float | None) -> str:
        return "  n/a" if value is None else f"{value:5.1%}"

    ks = report.k_values
    print(
        f"\nbenchmark {report.dataset_version} | embedding {report.embedding_model} | "
        f"{report.questions} questions ({report.answerable} answerable) | "
        f"access violations {report.access_violations}"
    )
    print(f"{'':20}" + "".join(f"  R@{k:<4}" for k in ks) + "   MRR")
    print(
        f"{'all':20}"
        + "".join(f" {pct(report.recall_at_k[k])} " for k in ks)
        + f" {pct(report.mrr)}"
    )
    for question_type in QuestionType:
        row = report.by_type[question_type]
        if not row.answerable:
            continue
        label = f"{question_type.value} ({row.answerable})"
        print(
            f"{label:20}" + "".join(f" {pct(row.recall_at_k[k])} " for k in ks) + f" {pct(row.mrr)}"
        )
    print(
        f"mean top score: answerable {report.top_score_answerable_mean}, "
        f"unanswerable {report.top_score_unanswerable_mean}"
    )


async def main() -> int:
    args = parse_args()
    settings = get_settings()
    if args.database_url.strip() == settings.database_url.get_secret_value().strip():
        print("refusing to wipe the app database (EKA_DATABASE_URL); pass a disposable database")
        return 2
    provider = args.embedding or settings.embedding_provider
    ks = [int(k) for k in args.k.split(",")]

    dataset = load_benchmark(args.benchmark, load_corpus(args.corpus))
    migrate(args.database_url)
    wipe_documents(args.database_url)

    client: FptClient | None = None
    embedder: Embedder
    if provider == "fpt":
        key = settings.embedding_api_key or settings.llm_api_key
        if key is None:
            print("--embedding fpt needs EKA_EMBEDDING_API_KEY")
            return 2
        client = FptClient.create(
            base_url=settings.embedding_base_url,
            api_key=key,
            timeout_seconds=settings.embedding_request_timeout_seconds,
            retry=RetryPolicy(max_attempts=settings.model_max_attempts),
        )
        embedder = FptEmbedder(
            client, model=settings.embedding_model, dimension=settings.embedding_dimension
        )
    else:
        embedder = HashingEmbedder(dimension=settings.embedding_dimension)

    store = await PostgresDocumentStore.connect(
        args.database_url, embedding_dimension=settings.embedding_dimension
    )
    try:
        with tempfile.TemporaryDirectory() as blob_dir:
            await index_corpus(
                dataset.corpus,
                documents=store,
                embedder=embedder,
                blobs=LocalBlobStore(Path(blob_dir)),
                chunking=dataset.chunking,
            )
        report = await run_retrieval_benchmark(
            dataset,
            SearchKnowledge(search=store, embedder=embedder),
            k_values=ks,
            embedding_model=embedder.model,
        )
    finally:
        await store.close()
        if client is not None:
            await client.aclose()

    print_report(report)
    out = args.out or ROOT / "docs" / "evaluation" / (
        f"benchmark-{report.dataset_version}-{provider}-{datetime.now(UTC):%Y%m%d-%H%M%S}.json"
    )
    dump_report(report, out)
    print(f"\nreport written to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
