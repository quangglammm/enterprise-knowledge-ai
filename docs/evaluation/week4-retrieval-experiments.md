# Week 4 retrieval experiments

Benchmark v2 (ADR-0012), 115 questions (100 answerable), Postgres and pgvector, `Vietnamese_Embedding` (FPT), all runs at code revision `15e122b`. Configurations are in `experiments/week4/`; the method is in ADR-0013. Reports are the `benchmark-v2*-{baseline,no-header,packed-1200,packed-800}-fpt-20261030-*.json` files in this directory.

## Results

| Experiment | Chunks | R@1 | R@3 | R@10 | MRR | Cross-lingual R@1 | Near-duplicate R@1 | Improved / worsened | Sign test p |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| baseline (section per chunk, header on) | 219 | 86.5% | 95.5% | 100% | 0.930 | 60.0% | 70.0% | — | — |
| no-header | 219 | 81.5% | 93.5% | 99% | 0.897 | 53.3% | 70.0% | 2 / 11 | 0.022 |
| packed-1200 | 71 | 83.5% | 92.5% | 97% | 0.904 | 60.0% | 76.7% | 4 / 11 | 0.118 |
| packed-800 | 96 | 82.5% | 94.5% | 97% | 0.903 | 63.3% | 63.3% | 4 / 12 | 0.077 |

- **Improved / worsened** counts the answerable questions whose reciprocal rank rose or fell against the baseline (`scripts/compare_reports.py`).
- **Sign test p** is the exact two-sided sign test on those counts. Questions whose rank did not change are excluded.
- **Chunks** are the served chunks.
- 0 access violations in every run.
- **The FPT run is deterministic.** Re-running the baseline reproduced the earlier, pre-harness v2 report exactly: every ranking and every top score.

## Findings

1. **The embedding header helps, and the effect is unlikely to be noise.** Without the "title › section" header, R@1 falls 5.0 points and MRR 0.033. 11 questions get worse and 2 get better (p = 0.022). Cross-lingual questions lose most (R@1 60.0% → 53.3%). This is the Week 4 measurement ADR-0006 promised. The header stays.
2. **Section packing does not help on this corpus.** Both budgets lower R@1 (3.0 and 4.0 points) and MRR (about 0.027). Neither change is statistically clear (p = 0.118 and 0.077).
   - **Where packing helps:** both budgets fix the same 4 questions (q031, q075, q089, q113). In three of them (q031, q089, q113), a neighbouring section of the same document used to outrank the answer; once the sections share a chunk, the distinction no longer matters. In q075, the earlier top hit came from another document.
   - **Where packing hurts:** short, specific answers diluted in larger chunks (for example q001, meal allowance; q026, hourly leave).
   - **Score gap:** packing narrows the top-score gap between answerable and unanswerable questions from 0.152 to 0.094 (packed-1200). That would make the evidence gate (`EKA_ANSWER_MIN_SCORE`) harder to calibrate.
   - **Decision:** `pack_sections` stays off by default.
3. **Recall@3 is near its ceiling** in every variant (92.5–95.5%). As ADR-0012 expected, Recall@1 and MRR are where variants differ.

## Hybrid retrieval (ADR-0014)

Run at `d86d866`, same corpus, labels and embedder as the baseline. RRF uses k=60 and 50 candidates per list. Reports: `benchmark-v2-hybrid-{fpt,hashing}-20261030-*.json`.

| Experiment | R@1 | R@3 | R@10 | MRR | Cross-lingual R@1 | Near-duplicate R@1 | Improved / worsened |
| --- | --- | --- | --- | --- | --- | --- | --- |
| baseline (vector) | 86.5% | 95.5% | 100% | 0.930 | 60.0% | 70.0% | — |
| hybrid | 73.0% | 76.5% | 80.5% | 0.771 | 18.3% | 56.7% | 0 / 24 |

With the hashing embedder, which is itself word overlap, hybrid improves 5 questions and worsens 1. With real embeddings it is clearly worse: no question improves, and even Recall@10 loses 19.5 points. Monolingual Vietnamese questions are unchanged (96.2% R@1); the damage is in cross-lingual (60.0% → 18.3%) and multi-document questions.

**Why: these settings make RRF rank the overlap of the two lists first.** With `rrf_k` = 60 and 50 candidates per list, the best score a chunk can get from one list (1/61 ≈ 0.0164) is below the worst score of a chunk found by both (2/110 ≈ 0.0182). So every chunk in both top-50 lists outranks every chunk found by only one, however well it ranked there. Two measurements make that decisive here:

- **The lexical list is mostly noise.** It is full (50 hits) for 91 of 115 questions, because an OR query over a natural-language question matches common words almost everywhere.
- **Cross-lingual answers rarely match lexically.** A relevant chunk is in the lexical top 50 for 81 of 100 answerable questions, but for only 11 of 30 cross-lingual ones. Example: q031 asks in Vietnamese about Hanoi–HCMC express delivery; the English answer chunk is vector rank 3, has no lexical match, and falls out of the fused top 10.

**Decision: vector search stays the production default** (`EKA_RETRIEVAL_MODE=vector`). The hybrid code stays, behind the setting.

**Not done, on purpose: tuning on this benchmark.** Smaller candidate depth, weighted fusion, a minimum-IDF gate on lexical hits, or skipping lexical search for cross-lingual queries could each fix the mechanism above. Choosing among them with these same 100 questions would overfit the benchmark; that needs a development/test split of the questions first.

## Limits

- **Sample size:** 100 answerable questions; 1 percentage point of Recall@1 is one question. Differences of a few points need the per-question counts above, not the means alone.
- **Scope:** one embedding model and one corpus. A multilingual embedding candidate (plan revision 12) has not been run, because the model IDs offered by the FPT marketplace are still to be confirmed.
- **Answer quality:** retrieval metrics do not show how the answer changes. Top-k and packing at the answer level need EVAL-02.

## Next

- **EVAL-02:** answer quality.
- **Before any hybrid tuning:** a fixed development/test split of the benchmark questions.
