"""Calibrate the AGENT-02 answer verifier on hand-labelled grounding cases (paid calls).

    uv run python scripts/verifier_calibration.py

Runs ``AnswerVerifier`` on the grounding cases of the EVAL-02 calibration set
(datasets/judge_calibration/) and reports how often its verdict (every claim supported, or
not) matches the hand label for faithfulness (ADR-0019). One call per case, no repair, as
in the workflow. Writes a JSON report with verdicts only to docs/evaluation/.
"""

import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from enterprise_knowledge.agents.errors import VerifierOutputError
from enterprise_knowledge.agents.verify import VERIFIER_PROMPT_VERSION, AnswerVerifier
from enterprise_knowledge.config import get_settings
from enterprise_knowledge.evaluation.judge_calibration import dataset_sha256, load_calibration
from enterprise_knowledge.infrastructure.fpt.chat import FptChatModel
from enterprise_knowledge.infrastructure.fpt.client import FptClient, RetryPolicy

ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "datasets" / "judge_calibration" / "cases-v2.jsonl"


async def main() -> int:
    settings = get_settings()
    if settings.llm_api_key is None or settings.llm_model is None:
        print("set EKA_LLM_API_KEY and EKA_LLM_MODEL in .env")
        return 2
    cases = [c for c in load_calibration(CASES) if c.kind == "grounding"]
    client = FptClient.create(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        timeout_seconds=settings.llm_request_timeout_seconds,
        retry=RetryPolicy(max_attempts=settings.model_max_attempts),
    )
    verifier = AnswerVerifier(
        chat=FptChatModel(client, model=settings.llm_model, json_mode=settings.llm_json_mode)
    )
    outcomes: list[dict[str, object]] = []
    try:
        for case in cases:
            try:
                check = await verifier.verify(
                    question=case.question, answer=case.answer, evidence=case.retrieved()
                )
            except VerifierOutputError as exc:
                outcomes.append({"case_id": case.id, "error_category": exc.category})
                continue
            outcomes.append(
                {
                    "case_id": case.id,
                    "expected_supported": case.expect_faithful,
                    "verified_supported": check.supported,
                    "agrees": check.supported is case.expect_faithful,
                    "claims": check.claims,
                    "unsupported_claims": check.unsupported_claims,
                    "input_tokens": check.input_tokens,
                    "output_tokens": check.output_tokens,
                }
            )
    finally:
        await client.aclose()

    judged = [o for o in outcomes if "agrees" in o]
    agreement = sum(1 for o in judged if o["agrees"]) / len(judged) if judged else None
    report = {
        "started_at": datetime.now(UTC).isoformat(),
        "verifier_model": settings.llm_model,
        "verifier_prompt_version": VERIFIER_PROMPT_VERSION,
        "dataset_sha256": dataset_sha256(CASES),
        "cases": len(outcomes),
        "errors": len(outcomes) - len(judged),
        "agreement": agreement,
        "outcomes": outcomes,
    }
    print(
        f"verifier {VERIFIER_PROMPT_VERSION}: agreement {agreement} on {len(judged)} cases, "
        f"{report['errors']} errors"
    )
    for o in judged:
        if not o["agrees"]:
            print(f"  DISAGREE {o['case_id']}: expected supported={o['expected_supported']}")
    out = (
        ROOT
        / "docs"
        / "evaluation"
        / f"verifier-calibration-{datetime.now(UTC):%Y%m%d-%H%M%S}.json"
    )
    out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"report written to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
