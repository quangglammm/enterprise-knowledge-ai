"""Run the EVAL-02 answer-quality evaluation on Postgres (paid calls; ADR-0015).

    uv run python scripts/run_answer_eval.py --database-url postgresql://eka:eka@localhost:5432/eka_test
    uv run python scripts/run_answer_eval.py --database-url ... --limit 5    # a cheap smoke run
    uv run python scripts/run_answer_eval.py --database-url ... --mode workflow  # ADR-0017

Migrates and WIPES the given database, indexes the corpus through the production ingestion
path, then answers every benchmark question through the production ``AnswerQuestion`` path
(retrieval settings, k and the evidence gate from EKA_* settings) and judges each answer
with ``AnswerJudge``. Writes a report with verdicts and no answer text to docs/evaluation/;
``--answers-out`` also writes answer texts to a separate file for manual review (do not
commit it). Refuses to touch the app database (EKA_DATABASE_URL).
"""

import argparse
import asyncio
import json
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from run_benchmark import REPORTS_DIR, code_revision

from enterprise_knowledge.agents.modes import AnswerModes, ModeAnswer
from enterprise_knowledge.agents.workflow import AnswerWorkflow, WorkflowLimits
from enterprise_knowledge.config import get_settings
from enterprise_knowledge.domain.access import Principal
from enterprise_knowledge.evaluation.answer_quality import (
    AnswerQualityReport,
    AnswerRunSettings,
    evaluate_answers,
)
from enterprise_knowledge.evaluation.benchmark import (
    QuestionType,
    index_corpus,
    load_benchmark,
    load_corpus,
)
from enterprise_knowledge.evaluation.judge import AnswerJudge
from enterprise_knowledge.generation.answer import AnswerQuestion
from enterprise_knowledge.infrastructure.blobs import LocalBlobStore
from enterprise_knowledge.infrastructure.fpt.chat import FptChatModel
from enterprise_knowledge.infrastructure.fpt.client import FptClient, RetryPolicy
from enterprise_knowledge.infrastructure.fpt.embeddings import FptEmbedder
from enterprise_knowledge.infrastructure.postgres.migrate import migrate, wipe_documents
from enterprise_knowledge.infrastructure.postgres.store import PostgresDocumentStore
from enterprise_knowledge.retrieval.search import RetrievalSettings, SearchKnowledge

ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--database-url", required=True, help="a database this run may wipe")
    parser.add_argument("--corpus", default="v2", help="datasets/corpus/<name>")
    parser.add_argument("--benchmark", default="v2", help="datasets/benchmark/<name>")
    parser.add_argument("--judge-model", help="default: EKA_LLM_MODEL")
    parser.add_argument("--mode", choices=["direct", "workflow"], default="direct")
    parser.add_argument("--limit", type=int, help="only the first N questions (smoke run)")
    parser.add_argument("--out", type=Path, help="report path (default: docs/evaluation/...)")
    parser.add_argument("--answers-out", type=Path, help="also write answer texts here")
    return parser.parse_args()


def print_report(report: AnswerQualityReport) -> None:
    def pct(value: float | None) -> str:
        return "  n/a" if value is None else f"{value:5.1%}"

    print(
        f"\nanswers {report.answer_model} ({report.answer_prompt_version}) | judge "
        f"{report.judge_model} ({report.judge_prompt_version}) | benchmark "
        f"{report.dataset_version} | {report.questions} questions "
        f"({report.answerable} answerable)"
    )
    print(
        f"answer rate {pct(report.answer_rate)} | abstention accuracy "
        f"{pct(report.abstention_accuracy)} | correct {pct(report.correct_rate)} "
        f"(with partial {pct(report.correct_or_partial_rate)}) | faithful "
        f"{pct(report.faithfulness_rate)} | citation-supported "
        f"{pct(report.citation_support_rate)} | cites gold {pct(report.gold_citation_rate)} | "
        f"gold retrieved {pct(report.retrieval_gold_rate)}"
    )
    print(f"{'':22}correct  faithful")
    for question_type in QuestionType:
        row = report.by_type[question_type]
        if row.questions:
            print(
                f"{question_type.value + f' ({row.questions})':22}{pct(row.correct_rate)}   "
                f"{pct(row.faithfulness_rate)}"
            )
    print(
        f"mode {report.settings.mode} | model calls {report.model_calls} | planner tokens "
        f"{report.planner_input_tokens}/{report.planner_output_tokens} | revised "
        f"{report.revised_answers} | withheld by verification {report.verification_abstentions} "
        f"| verifier tokens {report.verifier_input_tokens}/{report.verifier_output_tokens}"
    )
    print(
        f"errors: answer {report.answer_errors}, judge {report.judge_errors} | tokens: answer "
        f"{report.answer_input_tokens}/{report.answer_output_tokens}, judge "
        f"{report.judge_input_tokens}/{report.judge_output_tokens} (in/out)"
    )


async def main() -> int:
    args = parse_args()
    settings = get_settings()
    if args.database_url.strip() == settings.database_url.get_secret_value().strip():
        print("refusing to wipe the app database (EKA_DATABASE_URL); pass a disposable database")
        return 2
    embedding_key = settings.embedding_api_key or settings.llm_api_key
    if settings.llm_api_key is None or settings.llm_model is None or embedding_key is None:
        print("set EKA_LLM_API_KEY, EKA_LLM_MODEL and an embedding key in .env")
        return 2

    dataset = load_benchmark(
        ROOT / "datasets" / "benchmark" / args.benchmark,
        load_corpus(ROOT / "datasets" / "corpus" / args.corpus),
    )
    if args.limit:
        dataset = dataset.model_copy(update={"questions": dataset.questions[: args.limit]})
    retrieval = RetrievalSettings(
        mode=settings.retrieval_mode,
        rrf_k=settings.rrf_k,
        candidates=settings.hybrid_candidates,
    )
    migrate(args.database_url)
    wipe_documents(args.database_url)

    embed_client = FptClient.create(
        base_url=settings.embedding_base_url,
        api_key=embedding_key,
        timeout_seconds=settings.embedding_request_timeout_seconds,
        retry=RetryPolicy(max_attempts=settings.model_max_attempts),
    )
    chat_client = FptClient.create(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        timeout_seconds=settings.llm_request_timeout_seconds,
        retry=RetryPolicy(max_attempts=settings.model_max_attempts),
    )
    embedder = FptEmbedder(
        embed_client, model=settings.embedding_model, dimension=settings.embedding_dimension
    )
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
        search = SearchKnowledge(search=store, embedder=embedder, retrieval=retrieval)
        chat = FptChatModel(chat_client, model=settings.llm_model, json_mode=settings.llm_json_mode)
        limits = WorkflowLimits(
            max_sub_questions=settings.workflow_max_sub_questions,
            k_per_question=settings.answer_top_k,
            max_evidence=settings.workflow_max_evidence,
            timeout_seconds=settings.workflow_timeout_seconds,
        )
        modes = AnswerModes(
            direct=AnswerQuestion(
                search=search,
                chat=chat,
                k=settings.answer_top_k,
                min_score=settings.answer_min_score,
                timeout_seconds=settings.answer_timeout_seconds,
            ),
            workflow=AnswerWorkflow(
                search=search, chat=chat, limits=limits, min_score=settings.answer_min_score
            ),
        )

        async def answer(principal: Principal, question: str) -> ModeAnswer:
            return await modes(principal, question, mode=args.mode)

        judge = AnswerJudge(
            chat=FptChatModel(
                chat_client,
                model=args.judge_model or settings.llm_model,
                json_mode=settings.llm_json_mode,
            ),
            timeout_seconds=settings.answer_timeout_seconds,
        )
        print(f"answering and judging {len(dataset.questions)} questions ...")
        report = await evaluate_answers(
            dataset,
            answer,
            judge,
            AnswerRunSettings(
                retrieval=retrieval,
                k=settings.answer_top_k,
                min_score=settings.answer_min_score,
                embedding_model=embedder.model,
                mode=args.mode,
                workflow=limits if args.mode == "workflow" else None,
            ),
            code_revision=code_revision(),
            keep_text=args.answers_out is not None,
        )
    finally:
        await store.close()
        await embed_client.aclose()
        await chat_client.aclose()

    print_report(report)
    suffix = f"-limit{args.limit}" if args.limit else ""
    out = args.out or ROOT / REPORTS_DIR / (
        f"answer-quality-{report.dataset_version}-{args.mode}{suffix}-"
        f"{datetime.now(UTC):%Y%m%d-%H%M%S}.json"
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report.model_dump_json(indent=2, exclude={"outcomes": {"__all__": {"answer"}}}))
    print(f"\nreport written to {out}")
    if args.answers_out:
        answers = [o.model_dump(include={"question_id", "answer"}) for o in report.outcomes]
        args.answers_out.write_text(json.dumps(answers, ensure_ascii=False, indent=2), "utf-8")
        print(f"answer texts written to {args.answers_out} (do not commit)")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
