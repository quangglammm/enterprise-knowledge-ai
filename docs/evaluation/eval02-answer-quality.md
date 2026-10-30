# EVAL-02 answer quality on benchmark v2

Run of 2026-10-30, code `6544b58`, report `answer-quality-v2-20261030-041627.json`.

- **Answers:** the production `AnswerQuestion` path. Vector retrieval, k = 5, no evidence gate, `Llama-3.3-70B-Instruct`, prompt `answer-v1`.
- **Judge:** the same model, prompt `judge-v2` (ADR-0015).
- **Questions:** 115 (100 answerable, 15 unanswerable).
- **Tokens:** 89,359 / 4,351 for answers and 95,930 / 5,603 for the judge (in / out).
- **Errors:** 0 answer errors; 1 judge error (q030's grounding call).

## Results

| Metric | Value | Source |
| --- | --- | --- |
| Answer rate (answerable questions answered) | 96.0% | deterministic |
| Abstention accuracy (unanswerable questions abstained) | 100% (15/15) | deterministic |
| Answers citing a gold chunk | 99.0% | deterministic |
| Gold chunk retrieved (top 5) | 96.0% | deterministic |
| Faithfulness (every claim in the retrieved evidence) | 100% | judge |
| Citation support (every claim in the cited evidence) | 100% | judge |
| Correct, judge, strict | 63.0% | judge |
| Correct or partially correct, judge | 94.0% | judge |
| **Correct, after review** | **92.0%** | review of every non-`correct` verdict |
| Correct or partial, after review | 95.0% | review |

## Review of the judge's correctness verdicts

Every answered question the judge did not mark `correct` (33) was compared with its question and reference answer, and the 63 `correct` verdicts were skimmed for false positives. The reviewer was the assistant that wrote the benchmark, not a second person; a person should confirm the classifications below.

| Judge verdict | Questions | Review |
| --- | --- | --- |
| `correct` | 63 | all correct; no false positives found |
| `partially_correct` | 31 | 28 fully answer the question asked; 3 really omit part of the answer (q005 omits the eligibility condition, q053 the 300-hour exception, q110 the return conditions) |
| `incorrect` | 2 | q025 is really wrong (see below); q093 ("30 seconds" for "below 30 seconds") is correct |

The 28 over-strict verdicts follow one pattern. The model answers tersely ("300.000 đồng", "6 buổi", "5"), and the reference also states things the question did not ask (the rollback deadline, who reviews access, the emergency hotline). The judge treats each missing reference detail as a missing fact.

`judge-v2` added a rule against this and fixed the calibration cases built for it, but not these answers. It is also inconsistent: "2 ngày" for q004 was `correct`, while "6 buổi" for q060 was `partially_correct`.

**Agreement with the review on real answers is 67 of 96 (70%), against 93% on the calibration set.** Every disagreement errs on the strict side. So the judge's strict "correct" is a lower bound, and "correct or partial" is the better proxy (94.0% judged vs 95.0% reviewed). Strict judged correctness should not be quoted as answer quality.

## Where answers fail

Of the 8 answerable questions not answered correctly after review:

- **Retrieval (4: q025, q026, q052, q055).** The gold chunk was not in the top 5. All four are English questions about Vietnamese company policies, and in all four the GOV.UK and Labour Code excerpts take most of the top 5 (`benchmark-v2-baseline-fpt` report).
  - q025 is the most important finding of the run. Asked about annual leave in English, the model answered "at least 28 days" from the GOV.UK excerpt (ADR-0012's planted distractor). The answer is faithful and properly cited, and wrong for the company (14 days). Faithfulness checks cannot catch this; only retrieval can.
  - q026, q052 and q055 abstained correctly given what was retrieved.
- **Generation (1: q051).** The overtime policy chunk was retrieved, but the model abstained. The same top 5 also held the Labour Code (40 hours) and the news digest restating the superseded 30-hour cap, so the evidence conflicted.
- **Incomplete answers (3: q005, q053, q110).** Terse answers that drop a condition or exception.

Faithfulness and citation support are 100% (95 of 95 judged answers). Calibration supports those two metrics (12/12), and no answer was judged unsupported. A judge that was too lenient on grounding would also produce 100%, so these numbers say "no unsupported claim found", not "proven grounded".

## Limits

- One run at temperature 0, and one model as both answerer and judge.
- The review is by the benchmark's author, not a person (see above).
- The reference answers are fuller than the questions require. That is the root of the judge's strictness, and a reason to keep strict correctness out of headlines.

## Next

- Use "correct or partial" plus the review as the answer-quality figure until a better judge or trimmed references exist. A `judge-v3` should be calibrated on real terse answers from this run, not on new synthetic cases.
- Cross-lingual retrieval is the main source of wrong or missing answers, and q025 shows a distractor can produce a confident, cited, wrong answer. That points at retrieval work (a multilingual embedding check, ADR-0004) more than at generation.
