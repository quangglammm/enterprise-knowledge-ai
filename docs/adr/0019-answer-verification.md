# ADR-0019: Claim-level verification in the answer workflow

- Status: Accepted
- Date: 2026-10-30

## Context

AGENT-02 requires that unsupported claims trigger a retry or an abstention, that agent outputs use typed schemas, and that invalid transitions are tested. The safety rules say hitting a limit ends in abstention or a controlled failure, never a partial unverified answer.

What verification can and cannot do:
- It catches statements the evidence does not make.
- It cannot catch a grounded answer drawn from the wrong evidence. EVAL-02's q025 quoted GOV.UK's 28 days, a faithful and cited answer that is wrong for the company.
- On benchmark v2 the EVAL-02 judge found no unsupported claims, so verification is mainly a safety net, and its main risk is withholding correct answers.

## Options considered

- **Scope:** the workflow only (the agent path), both modes behind a setting, or a separate third mode.
- **On failure:** retry once then abstain, or abstain at once.
- **Check:** an LLM claim check, or an LLM check plus a deterministic number guard. The guard was rejected for now: normalising numbers across Vietnamese and English formats risks rejecting correct paraphrases.

## Decision

The workflow only; retry once, then abstain; an LLM claim check.

- **Verifier** (`agents/verify.py`, prompt `verifier-v1`, temperature 0):
  - One call lists the answer's claims and the evidence labels that state each; a claim no block states is unsupported. The check is support by any of the evidence the answer was given, i.e. faithfulness. That citations resolve to that evidence is already enforced by the answer parser.
  - Evidence is escaped and labelled untrusted.
  - The output is typed: unknown labels and empty claim lists are rejected.
  - There is no repair attempt; unreadable output is `VerifierOutputError`.
- **State machine:** `ANSWERING → VERIFYING → DONE`, `VERIFYING → ANSWERING` (at most `max_revisions` = 1 time) and `VERIFYING → ABSTAINED`.
  - `DONE` is reachable only from `VERIFYING`, so an unverified answer cannot finish.
  - A model abstention goes `ANSWERING → ABSTAINED` with nothing to verify.
  - A second revision raises `WorkflowLimitError`.
- **Revision:** `GenerateAnswer(revise=True)` appends `REVISION_INSTRUCTION`, a fixed text from `generation/prompts.py`. It does not echo the unsupported statements back, so no model or document text becomes an instruction. The new answer is verified again.
- **Abstention reasons:**
  - `unsupported_claims`: still unsupported after the revision.
  - `verification_unavailable`: the verifier output was unreadable. The workflow fails closed.
- **Budgets** (derived from the workflow shape unless set; set values must still allow a complete run):
  - **Model calls:** `1 + 3 × (1 + max_revisions)`, so 7 by default.
  - **Steps:** `1 + max_sub_questions + 2 × (1 + max_revisions)`, so 8 by default.
- **API and UI:** answers carry `verification: {verified, revisions}`, where `verified` is null when nothing was verified (direct mode, or the model abstained). The UI's route line shows Answer → (Check → Revise) → Verified or Withheld. Evaluation reports record verification outcomes and verifier tokens.
- **Shared parsing:** `generation/output.py:clean_json_reply` strips fences, drops text after the first complete JSON value, and closes objects left open at the end. It never adds content. The answer parser, planner, verifier and EVAL-02 judge all use it.

## Calibration (2026-10-30)

On the 12 hand-labelled grounding cases of `datasets/judge_calibration/cases-v2.jsonl`, the verifier's verdict was compared with the label for faithfulness.

- **First run** (`verifier-calibration-20261030-090617.json`): 11/11 agreement, but 1 case (`grnd-en-05`) failed to parse. The model put a note after its JSON, and in the workflow that would have withheld a correct answer.
- **Fix:** `clean_json_reply` now drops trailing text.
- **Rerun** (`verifier-calibration-20261030-090729.json`): 12/12 agreement and 0 errors, including the case where the evidence instructs the checker.

## Consequences

- **Cost:** a verified workflow answer costs one more model call (two more, plus the regeneration, when it is revised). Direct mode is unchanged.
- **Measured trust:** the verifier's trust is measured on 12 clear-cut cases written by the benchmark author. Its false-withholding rate on real answers is measured by running `scripts/run_answer_eval.py --mode workflow`; reports count `verification_abstentions` and `revised_answers`.
- **Self-preference:** verifier, answerer and judge are the same model. A disagreement between them is visible in the reports, but shared blind spots are not.
- **Revisit:** if verification withholds correct answers measurably often. Options then are a more lenient prompt, verification of only cited claims, or a different verifier model.
