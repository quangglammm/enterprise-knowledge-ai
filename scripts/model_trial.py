"""Run the ADR-0004 model trial against FPT AI Marketplace (paid calls).

    uv run python scripts/model_trial.py --models Llama-3.3-70B-Instruct,Qwen2.5-7B-instruct

Each model runs the versioned cases in datasets/model_trial/ through the production
generation path, with JSON mode on and/or off. Writes a JSON results file without answer
text (safe to commit) and prints a summary. ``--answers-out`` additionally writes the
answer texts to a separate file for manual review; keep that file out of git.
Keys come from .env (EKA_LLM_*); they are never printed.
"""

import argparse
import asyncio
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from enterprise_knowledge.config import get_settings
from enterprise_knowledge.evaluation.model_trial import (
    CaseOutcome,
    TrialCase,
    TrialSummary,
    load_cases,
    run_trial,
    summarize,
)
from enterprise_knowledge.generation.answer import GenerateAnswer
from enterprise_knowledge.infrastructure.fpt.chat import FptChatModel
from enterprise_knowledge.infrastructure.fpt.client import FptClient, RetryPolicy

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CASES = ROOT / "datasets" / "model_trial" / "cases-v1.jsonl"
DEFAULT_OUT_DIR = ROOT / "docs" / "evaluation"
# A wrong model ID or key fails every case the same way; stop after the first.
_FATAL = frozenset({"model_request_rejected", "model_auth_failed"})


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models", help="comma-separated model IDs (default: EKA_LLM_MODEL)")
    parser.add_argument("--json-mode", choices=["on", "off", "both"], default="both")
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--out", type=Path, help="results JSON (default: docs/evaluation/...)")
    parser.add_argument("--answers-out", type=Path, help="also write answer texts here")
    return parser.parse_args()


async def run_one(
    client: FptClient,
    cases: list[TrialCase],
    *,
    model: str,
    json_mode: bool,
    answer_timeout_seconds: float,
    keep_text: bool,
) -> tuple[TrialSummary, list[CaseOutcome]]:
    generate = GenerateAnswer(
        chat=FptChatModel(client, model=model, json_mode=json_mode),
        timeout_seconds=answer_timeout_seconds,
    )
    first = await run_trial(cases[:1], generate, keep_text=keep_text)
    if first[0].error_category in _FATAL:
        print(f"  {model}: {first[0].error_category} on the first case; skipping the rest")
        outcomes = first
    else:
        outcomes = first + await run_trial(cases[1:], generate, keep_text=keep_text)
    return summarize(outcomes, model=model, json_mode=json_mode), outcomes


def print_summary(summary: TrialSummary, outcomes: list[CaseOutcome]) -> None:
    def pct(value: float | None) -> str:
        return "n/a" if value is None else f"{value:.0%}"

    print(
        f"\n{summary.model} json_mode={'on' if summary.json_mode else 'off'}: "
        f"passed {summary.passed}/{summary.cases} | schema-valid {pct(summary.schema_valid_rate)} "
        f"(first try {pct(summary.first_try_valid_rate)}) | abstention "
        f"{pct(summary.abstention_accuracy)} | injection {pct(summary.injection_resistance)} | "
        f"citations {pct(summary.citation_accuracy)} | facts {pct(summary.fact_accuracy)} | "
        f"language {pct(summary.language_accuracy)} | errors {summary.provider_errors} | "
        f"p50 {summary.latency_p50_ms:.0f} ms p95 {summary.latency_p95_ms:.0f} ms | "
        f"tokens in/out per answer {summary.mean_input_tokens:.0f}/"
        f"{summary.mean_output_tokens:.0f} | ADR-0004 "
        f"{'MET' if summary.meets_adr_0004 else 'NOT MET'}"
    )
    checks = (
        "status_correct",
        "cites_expected",
        "facts_present",
        "language_ok",
        "injection_resisted",
    )
    for outcome in outcomes:
        if outcome.passed:
            continue
        failed = [c for c in checks if getattr(outcome, c) is False]
        reason = outcome.error_category or ", ".join(failed)
        print(f"  FAIL {outcome.case_id} ({outcome.kind.value}): {reason}")


async def main() -> int:
    args = parse_args()
    settings = get_settings()
    if settings.llm_api_key is None:
        print("EKA_LLM_API_KEY must be set in .env")
        return 2
    models = [m.strip() for m in (args.models or settings.llm_model or "").split(",") if m.strip()]
    if not models:
        print("pass --models or set EKA_LLM_MODEL")
        return 2
    modes = {"on": [True], "off": [False], "both": [False, True]}[args.json_mode]
    cases = load_cases(args.cases)
    started = datetime.now(UTC)
    out = args.out or DEFAULT_OUT_DIR / f"model-trial-{started:%Y%m%d-%H%M%S}.json"

    client = FptClient.create(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        timeout_seconds=settings.llm_request_timeout_seconds,
        retry=RetryPolicy(max_attempts=settings.model_max_attempts),
    )
    runs: list[dict[str, Any]] = []
    answers: list[dict[str, Any]] = []
    try:
        for model in models:
            for json_mode in modes:
                print(f"running {model} json_mode={json_mode} on {len(cases)} cases ...")
                summary, outcomes = await run_one(
                    client,
                    cases,
                    model=model,
                    json_mode=json_mode,
                    answer_timeout_seconds=settings.answer_timeout_seconds,
                    keep_text=args.answers_out is not None,
                )
                print_summary(summary, outcomes)
                answers += [
                    {
                        "model": model,
                        "json_mode": json_mode,
                        **o.model_dump(include={"case_id", "answer", "abstention_reason"}),
                    }
                    for o in outcomes
                ]
                runs.append(
                    {
                        "summary": summary.model_dump(mode="json"),
                        "outcomes": [
                            o.model_dump(mode="json", exclude={"answer", "abstention_reason"})
                            for o in outcomes
                        ],
                    }
                )
    finally:
        await client.aclose()

    record = {
        "trial": "ADR-0004 model trial",
        "started_at": started.isoformat(),
        "finished_at": datetime.now(UTC).isoformat(),
        "dataset": str(args.cases.relative_to(ROOT))
        if args.cases.is_relative_to(ROOT)
        else str(args.cases),
        "dataset_sha256": hashlib.sha256(args.cases.read_bytes()).hexdigest(),
        "provider_base_url": settings.llm_base_url,
        "answer_timeout_seconds": settings.answer_timeout_seconds,
        "model_max_attempts": settings.model_max_attempts,
        "runs": runs,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\nresults written to {out}")
    if args.answers_out:
        args.answers_out.write_text(
            json.dumps(answers, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"answer texts written to {args.answers_out} (do not commit)")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
