# ADR-0015: Answer-quality evaluation with a calibrated LLM judge

- Status: Accepted
- Date: 2026-10-30

## Context

EVAL-02 requires faithfulness, citation support and correctness to be measured separately, with model and dataset versions recorded for every run. Plan revision 9 adds the judge model and prompt version.

Benchmark v2 (ADR-0012) supplies the inputs: 100 reference answers, 15 unanswerable questions, and gold chunk labels. The constraints:
- **One usable model.** The FPT account serves one usable LLM, `Llama-3.3-70B-Instruct`, which is also the answer model; the Qwen and Llama 4 IDs were rejected (ADR-0004). A judge from the same model risks self-preference.
- **Safety rules apply.** Retrieved text is untrusted, and no answer text may be logged.

## Options considered

Judge:
1. **The same model, validated on a hand-labelled calibration set.** Its measured agreement bounds how far its verdicts can be trusted.
2. **A different marketplace model.** Removes self-preference, but no other ID works on this account yet.
3. **No LLM judge.** Hand-written key facts per question cover correctness, but faithfulness cannot be measured that way.

Structure: one call returning all three verdicts (cheaper, but one verdict can sway another) vs separate calls.

## Decision

- **Option 1, with two calls per answered question** (`evaluation/judge.py`, prompt `judge-v1`, temperature 0):
  - **Correctness:** the answer against the reference answer, with no evidence shown, so retrieval cannot sway the grade. The verdict is `correct`, `partially_correct` or `incorrect`.
  - **Grounding:** the judge splits the answer into claims and lists, for each claim, the evidence labels that state it. It is not told which blocks the answer cited. Code then derives the two metrics:
    - **faithful:** every claim is backed by retrieved evidence;
    - **citation-supported:** every claim is backed by evidence the answer cited.
  - **Prompt safety:** evidence uses the answer prompt's escaped, labelled blocks (`evidence_block`) under an "untrusted" heading. Answers and references are escaped too, so neither can close its block.
  - **Bad output:** invalid judge output gets one repair, then `JudgeOutputError`; timeouts raise `JudgeTimeoutError`.
- **Deterministic metrics, no judge involved:**
  - answer rate on answerable questions;
  - abstention accuracy on unanswerable questions;
  - whether citations hit a gold chunk;
  - whether retrieval surfaced a gold chunk at all, which separates retrieval failures from generation failures.
- **Scoring rules** (`evaluation/answer_quality.py`):
  - The production `AnswerQuestion` path answers.
  - An answer error counts as a failure in every rate it would enter.
  - A judge error leaves that one verdict unknown and out of its rate.
  - Correctness is measured over all answerable questions, so an abstention there is not correct.
  - Faithfulness and citation support are measured over answered questions, including wrongly answered unanswerable ones.
- **Recorded per run:**
  - dataset version and corpus manifest sha256;
  - chunking, retrieval settings, k and the evidence gate;
  - answer model and prompt version, judge model and prompt version;
  - code revision and token totals.

  No answer text is stored by default.
- **Calibration:** `datasets/judge_calibration/cases-v1.jsonl` holds 24 hand-labelled bilingual cases, 12 correctness and 12 grounding. Every verdict class is covered, including a cross-language answer, number-format paraphrases, an answer text that instructs the judge, and evidence that instructs the judge. `scripts/judge_calibration.py` reports agreement per metric. Judged numbers are quoted together with that agreement.

## Calibration (2026-10-30)

`Llama-3.3-70B-Instruct`, prompt `judge-v1`, 24 cases. Reports: `docs/evaluation/judge-calibration-*.json`.

- **First run** (`judge-calibration-20261030-035832.json`, code `3c88fae`): every judged case agreed, but `grnd-vi-06` failed as `judge_output_invalid` even after repair. Both of the model's replies were correct but dropped the final `}`.
- **Fix** (`32061ab`): the judge's parser now appends closers for objects and arrays left open at the end of a reply. It never adds content; a reply cut off inside a string still fails.
- **Rerun** (`judge-calibration-20261030-040008.json`): agreement was 12/12 on correctness, 12/12 on faithfulness and 12/12 on citation support, with 0 judge errors. The answer text that instructs the judge (`corr-en-06`) and the evidence that instructs it (`grnd-vi-05`) were both judged correctly. The run used 6,876 input and 817 output tokens.
- **Limits:** 24 clear-cut cases, written by the same author as the benchmark, show the judge follows the rubric. They do not show how it handles borderline real answers, and they do not measure self-preference on the model's own answers. The slice-2 write-up therefore reports judged metrics together with the deterministic ones, and spot-checks a sample of real verdicts by hand.

## Results (2026-10-30)

Benchmark v2, code `6544b58`, judge `judge-v2`. Write-up: `docs/evaluation/eval02-answer-quality.md`.

- **Deterministic:** 96% answer rate, 100% abstention accuracy, 99% of answers cite a gold chunk.
- **Judged:** 100% faithfulness and citation support. Correctness is 63% strict and 94% counting partial answers.
- **Review:** the review of every verdict other than `correct` puts correctness at 92%.
  - The judge's correctness agrees with the review on 70% of real answers, not the 93% calibration suggested. Every disagreement errs on the strict side: terse answers are marked partial whenever the reference states more than the question asked.
  - Strict judged correctness is therefore a lower bound and is not quoted as answer quality; "correct or partial" is the proxy.
  - A `judge-v3` must be calibrated on real terse answers from this run.

## Consequences

- **Confidence in judged numbers:** they are only as trustworthy as calibration agreement on 24 cases. A metric whose agreement is poor is reported as unreliable, not tuned around.
- **Self-preference stays an acknowledged bias:** calibration cases are not the model's own answers, so they do not measure it. Revisit when a second model ID works.
- **Cost:** a full benchmark-v2 run is about 115 answer calls plus up to 200 judge calls. That is paid and stays out of tests and CI, which use `ScriptedChatModel`.
- **Prompt changes** to `judge-v1` require rerunning calibration under a new version string.
