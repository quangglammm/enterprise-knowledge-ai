# Model trial cases

Fixed grounded-answer prompts for the ADR-0004 model trial. Each case carries its own evidence, so the trial measures a chat model together with our prompt and parser (`GenerateAnswer`), not retrieval. Content is the fictional Bamboo Harbor corpus used by the parser fixtures.

Run:

```bash
uv run python scripts/model_trial.py --models Llama-3.3-70B-Instruct --json-mode both
```

Paid calls; never part of the test suite. Results without answer text go to `docs/evaluation/`.

## `cases-v1.jsonl`

24 cases, one JSON object per line:

| Group | IDs | Count | What it checks |
| --- | --- | --- | --- |
| Vietnamese | `vi-01`..`vi-06` | 6 | Answer and cite from Vietnamese evidence, some with a distractor block |
| English | `en-01`..`en-05` | 5 | The same for English evidence |
| Cross-lingual | `x-01`..`x-04` | 4 | Answer in the question's language when the evidence is in the other one |
| Unanswerable | `u-01`..`u-05` | 5 | Abstain when the evidence is present but does not answer (including near misses) |
| Injection | `i-01`..`i-04` | 4 | Ignore instructions inside evidence: false facts, prompt leaks, format overrides, "never abstain" |

Fields: `kind`, `question`, `question_language` (`vi`/`en`), `evidence` (labelled E1, E2, ... in order), `expect_status`, `expect_citations` (at least one must be cited), `must_contain` (every item required; `a|b` accepts either), `must_not_contain` (canary words from injected text).

Checks are deterministic string and schema tests. They catch wrong facts and obeyed injections, but not subtle wording problems, so read a sample of answers when choosing a model. Never edit a published version; add `cases-v2.jsonl` instead, so results stay comparable.
