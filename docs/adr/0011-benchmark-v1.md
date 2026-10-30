# ADR-0011: Benchmark v1: corpus, chunk-ID labels and retrieval metrics

- Status: Accepted
- Date: 2026-10-29

## Context

EVAL-01 needs a dataset with answerable, unanswerable and multi-document questions, and deterministic Recall@k and MRR. ADR-0005 designed a bilingual corpus of about 50 documents. Authoring that, and having a person check every ground-truth fact, is more than one item. Week 4 will compare chunk sizes, top-k and hybrid retrieval on this benchmark, and hybrid retrieval will live in Postgres (plan revision 8).

## Options considered

Scope:

1. **Corpus v1 of about 20 documents now**, growing to about 50 in a frozen corpus v2.
2. **All 50 documents now.**

Relevance labels:

1. **Evidence quotes:** a chunk is relevant if it contains a quoted fact. Survives chunking changes.
2. **Document IDs:** coarse, and rewards the wrong section of the right document.
3. **Chunk IDs:** exact, but invalidated by any chunking change.

## Decision

- **Scope:** corpus v1, built from 21 documents (24 versions) across 2 tenants. ADR-0005's remaining targets go to corpus v2.
- **Labels: chunk IDs.** Each label is written readably, as document, version and chunk index, together with the derived chunk ID, which is checked against them.
  - `benchmark.json` pins the corpus manifest's sha256 and the chunking settings used for labelling.
  - The loader refuses to score if a labelled chunk does not exist under those settings, if evidence sits on a superseded version, or if the asking principal cannot read it. A chunking change therefore fails loudly instead of scoring 0.
  - Labels were produced by `scripts/build_benchmark.py` from (document, quote) pairs. The quotes are authoring input only, not the scoring rule.
  - Changing chunking means rebuilding into a new dataset version; v1 is never edited. `scripts/show_chunks.py` shows chunk boundaries for relabelling.
- **Evidence groups:**
  - A question lists one group per required fact, and any chunk in a group satisfies it (near-duplicates count).
  - **Recall@k** = the share of groups with a chunk in the top k.
  - **MRR** = 1 / rank of the first relevant chunk.
  - Unanswerable questions are excluded from both and reported separately, with their top retrieval score for calibrating the evidence gate (`EKA_ANSWER_MIN_SCORE`).
  - Score ties are broken by chunk ID (ADR-0007), so a run is deterministic.
- **Runner:** `scripts/run_benchmark.py` wipes a disposable database (it refuses the app database), indexes the corpus through the production `IngestDocument` with manifest IDs, and searches as each question's principal through `SearchKnowledge` on Postgres and pgvector. An access violation is counted, never hidden.
- **Corpus v1:**
  - 13 Vietnamese, 6 English and 2 bilingual documents.
  - Formats: PDF, DOCX, HTML and Markdown.
  - 3 version pairs whose answers differ: leave policy, expense policy, deployment guide.
  - 6 restricted documents across `hr`, `managers`, `security` and `engineering`.
  - A bilingual FAQ that repeats facts from another policy, a planted prompt-injection note, and a second tenant (`lotus-retail`) with a near-identical leave policy.
- **Benchmark v1:** 50 questions, 26 Vietnamese and 24 English:

  | Type | Questions |
  | --- | --- |
  | Cross-lingual | 13 |
  | Version-sensitive | 7 |
  | Access-sensitive (3 reader/non-reader pairs) | 6 |
  | Unanswerable | 6 |
  | Multi-document | 5 |
  | Tenant isolation | 2 |

## Results (2026-10-29)

Postgres and pgvector, chunking 1200/150, all 50 questions. Reports are in `docs/evaluation/benchmark-v1-*.json`.

| Embedding | R@1 | R@3 | R@5 | MRR | Cross-lingual R@1 | Access violations | Mean top score (answerable / unanswerable) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `hashing-v1` (dev, word overlap) | 72.7% | 77.3% | 78.4% | 0.773 | 16.7% | 0 | 0.443 / 0.281 |
| `Vietnamese_Embedding` (FPT) | 93.2% | 100% | 100% | 0.989 | 75.0% | 0 | 0.538 / 0.347 |

## Consequences

- **v1 saturates.** With 72 chunks, fewer visible per principal, a real embedder reaches 100% Recall@3, so v1 cannot separate the Week 4 retrieval variants. It validates the pipeline, the labels and access filtering. Corpus v2 is a prerequisite for Week 4 comparisons; it needs about 50 documents, at least 5 version pairs, at least 10 restricted documents, harder distractors and near-duplicates, and openly licensed public documents.
- **The hashing baseline is free and deterministic**, which makes it a candidate for a CI regression check (CI-01). It measures the pipeline, never quality.
- **Score gap for the evidence gate:** answerable questions' top scores (0.54) sit well above unanswerable ones (0.35) with FPT embeddings. This is a starting point for calibrating `EKA_ANSWER_MIN_SCORE` in Week 4, not a chosen threshold.
- **Human review done (2026-10-30):** per ADR-0005, a person checked the 50 ground-truth facts behind the reference answers and labels (now in `scripts/benchmark_data/v1.py`); all were accepted unchanged.
- **Answer quality is not measured here:** the reference answers are stored for EVAL-02.
