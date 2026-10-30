"""Calibrate the EVAL-02 answer-quality judge against hand-labelled verdicts (paid calls).

    uv run python scripts/judge_calibration.py [--judge-model Llama-3.3-70B-Instruct]

Runs every case in datasets/judge_calibration/ through ``AnswerJudge`` (one call per case,
plus at most one repair) and reports agreement for correctness, faithfulness and citation
support (ADR-0015). Writes a JSON report with verdicts only, no case text, to
docs/evaluation/. Keys come from .env (EKA_LLM_*); they are never printed.
"""

import argparse
import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path

from enterprise_knowledge.config import get_settings
from enterprise_knowledge.evaluation.judge import AnswerJudge
from enterprise_knowledge.evaluation.judge_calibration import (
    CalibrationReport,
    dataset_sha256,
    load_calibration,
    run_calibration,
)
from enterprise_knowledge.infrastructure.fpt.chat import FptChatModel
from enterprise_knowledge.infrastructure.fpt.client import FptClient, RetryPolicy

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CASES = ROOT / "datasets" / "judge_calibration" / "cases-v2.jsonl"
DEFAULT_OUT_DIR = ROOT / "docs" / "evaluation"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--judge-model", help="default: EKA_LLM_MODEL")
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--out", type=Path, help="report JSON (default: docs/evaluation/...)")
    return parser.parse_args()


def print_report(report: CalibrationReport) -> None:
    def pct(value: float | None) -> str:
        return "n/a" if value is None else f"{value:.0%}"

    print(
        f"\njudge {report.judge_model} ({report.judge_prompt_version}) on {report.cases} cases: "
        f"correctness {pct(report.correctness_agreement)} | "
        f"faithfulness {pct(report.faithfulness_agreement)} | "
        f"citation support {pct(report.citation_support_agreement)} | "
        f"judge errors {report.judge_errors} | "
        f"tokens {report.total_input_tokens} in / {report.total_output_tokens} out"
    )
    for outcome in report.outcomes:
        if outcome.agrees is False or outcome.error_category:
            judged = outcome.error_category or outcome.judged
            print(f"  DISAGREE {outcome.case_id}: expected {outcome.expected}, judged {judged}")


async def main() -> int:
    args = parse_args()
    settings = get_settings()
    model = args.judge_model or settings.llm_model
    if settings.llm_api_key is None or model is None:
        print("set EKA_LLM_API_KEY and EKA_LLM_MODEL in .env, or pass --judge-model")
        return 2
    cases = load_calibration(args.cases)
    client = FptClient.create(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        timeout_seconds=settings.llm_request_timeout_seconds,
        retry=RetryPolicy(max_attempts=settings.model_max_attempts),
    )
    judge = AnswerJudge(
        chat=FptChatModel(client, model=model, json_mode=settings.llm_json_mode),
        timeout_seconds=settings.answer_timeout_seconds,
    )
    try:
        print(f"judging {len(cases)} calibration cases with {model} ...")
        report = await run_calibration(cases, judge, dataset_sha256=dataset_sha256(args.cases))
    finally:
        await client.aclose()

    print_report(report)
    out = args.out or DEFAULT_OUT_DIR / f"judge-calibration-{datetime.now(UTC):%Y%m%d-%H%M%S}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
    print(f"\nreport written to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
