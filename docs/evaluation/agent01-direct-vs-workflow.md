# Direct RAG vs the planned workflow on benchmark v2

Week 6 comparison (AGENT-01, ADR-0017). Both runs use benchmark v2 (115 questions, 100 answerable), vector retrieval with k = 5 and no evidence gate, `Llama-3.3-70B-Instruct` with prompt `answer-v1`, and judge `judge-v2` (ADR-0015).

- **Workflow:** report `answer-quality-v2-workflow-20261030-084006.json`, code `daccdc4`, planner `planner-v1`, at most 3 sub-questions and 8 evidence chunks.
- **Direct:** the EVAL-02 run, `answer-quality-v2-20261030-041627.json`, code `6544b58`. It was reused rather than rerun: the direct answer path, the prompts, the settings and the judge are unchanged since then. Only modules it does not call were added.

## Results

| Metric | Direct | Workflow |
| --- | --- | --- |
| Answer rate (answerable) | 96.0% | 95.0% |
| Abstention accuracy (unanswerable) | 100% | 100% |
| Correct, judge strict | 63.0% | 62.0% |
| Correct or partially correct, judge | 94.0% | 93.0% |
| Faithfulness / citation support | 100% / 100% | 100% / 100% |
| Gold chunk retrieved | 96.0% | 96.0% |
| Multi-document correct, strict (8 questions) | 87.5% | 75.0% |
| Answer-side model calls | 115 (1 per question) | 230 (2 per question) |
| Planner tokens (in / out) | 0 | 20,592 / 2,829 |
| Answer tokens (in) | 89,359 | 93,368 |

**Per question, the outcome (status, judged correctness, gold retrieved, gold cited) differs on 1 of 115 questions, and the workflow is worse there.** q038 asks two things: remote-work days and the internet allowance. Direct answered both correctly. The workflow split it into two searches, retrieved the gold chunks, and the model abstained over the merged evidence. That single question accounts for the drop in multi-document correctness.

## Why the workflow does not help here

- **It changes nothing for most questions.** The planner kept 97 of 115 questions as a single part. With one part, the workflow runs the same search and asks the same answer prompt as direct mode, so at temperature 0 it returns the same answer, at the cost of the planning call.
- **Where it splits, direct already succeeds.** The planner split 18 questions, including 7 of the 8 multi-document ones (it kept q109 whole), and its splits read correctly. But direct RAG already answers 7 of the 8 multi-document questions correctly, so on this benchmark the workflow's target case has almost no headroom.
- **It does not touch the actual failures.** The direct misses are cross-lingual retrieval failures (q025, q026, q052, q055: English questions whose Vietnamese policy chunks lose to the GOV.UK and Labour Code excerpts) and one over-abstention (q051). The planner keeps the question's language, so its sub-questions miss the same chunks. q026 and q055 were split, and each part still found nothing.

## Decision

`EKA_ANSWER_MODE` stays `direct`. On benchmark v2, `planner-v1` doubles the model calls for 0 improved and 1 worsened question, so by the safety rule's own test ("the agent path must justify itself in the evaluation") it is not justified as a default. The mode stays available in the API and the UI for comparison.

## Next

- **A `planner-v2` aimed at the measured failure:** for each sub-question, also emit a query in the other language (Vietnamese ↔ English). Four of the eight direct misses are cross-lingual retrieval failures, and this is the one change in the workflow's power that targets them. It is a hypothesis to test, ideally on a development/test split of the questions, so the prompt is not tuned to the same 100 questions it is scored on.
- **A harder multi-part set:** benchmark v2 has only 8 multi-document questions, and direct answers 7. A fair test of decomposition needs more questions whose evidence lives in different documents.
- **Not measured:** latency. The evaluation report does not record time per question. A single comparison in the UI took 6.4 s for the workflow against 1.8 s for direct, which is consistent with the extra planning call and searches.
