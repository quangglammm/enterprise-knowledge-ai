# ADR-0012: Benchmark v2: superset corpus with hard distractors and public documents

- Status: Accepted
- Date: 2026-10-30

## Context

Benchmark v1 (ADR-0011) saturates. With FPT embeddings it reaches 100% Recall@3 and MRR 0.989, so Week 4 cannot use it to compare chunk sizes, top-k or hybrid retrieval. Its 24 versions make only 72 section-sized chunks, and every topic lives in exactly one document. ADR-0005's remaining targets were still open: about 50 documents, at least 5 version pairs, at least 10 restricted documents, near-duplicates, and a few openly licensed public documents. The labelling rules (chunk IDs, evidence groups, metrics) stay as in ADR-0011.

## Options considered

1. **Superset of v1:** copy every v1 version byte-for-byte, keep all 50 v1 questions, add documents and questions. Pros: the v1 questions measured on v2 show what the new distractors cost. Cons: a new document must never change a v1 answer, which constrains authoring.
2. **Fresh corpus:** new documents and questions only. Pros: free design. Cons: no comparison with v1, and twice the authoring and review work.

Public documents: (a) Vietnamese law plus GOV.UK guidance; (b) synthetic only, deferring ADR-0005's public-document target.

## Decision

- **Option 1, with public documents (a).** Authoring data: `scripts/benchmark_data/v2.py`; PDF and DOCX files: `scripts/make_corpus_v2.py`; built by `scripts/build_benchmark.py --version v2`.
- **Corpus v2:** 49 documents (55 versions, 243 chunks) across 2 tenants. 28 Vietnamese, 18 English, 3 bilingual. Formats: PDF (including a table), DOCX, HTML and Markdown. 6 version pairs; 15 restricted documents.
- **Distractors are designed, not random:**
  - sibling documents with the same layout and different facts: the Da Nang hub's service levels, the Binh Duong cold store's rules, four runbooks with identical sections;
  - statutory rules next to company rules;
  - a news digest restating the superseded overtime rules;
  - Lotus Retail copies of Bamboo Harbor policies with other values;
  - a second prompt-injection document (`it-service-desk-faq`).
- **Public documents:**
  - `pub-vn-labour-code-working-time`: Bộ luật Lao động 2019, Điều 105–114, from the Wikisource transcription of the Công báo. Public domain under Luật SHTT Điều 15. Điều 115 (marriage leave) is left out so that v1's q013 stays unanswerable.
  - `pub-uk-holiday-entitlement`: three parts of the GOV.UK guide with their original markup, under OGL v3.0.
  - Source and licence are recorded per document in the manifest.
- **v1 questions stay true on v2:**
  - No new document answers a v1 unanswerable question.
  - Where a new document restates a v1 answer (q014, q015, q030, q032), it is added to that question's evidence group as an alternative.
  - Where a new document only competes with the answer, the question gains the new `near-duplicate` type (q001, q021, q025, q031).
- **Benchmark v2:** 115 questions (v1's 50 plus 65 new), 100 answerable and 15 unanswerable.

## Results (2026-10-30)

Postgres and pgvector, chunking 1200/150. Reports are in `docs/evaluation/benchmark-v2-*.json`.

| Embedding | R@1 | R@3 | R@10 | MRR | Cross-lingual R@1 | Near-duplicate R@1 | v1 questions R@1 / MRR | Violations |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `hashing-v1` | 68.0% | 72.0% | 73.0% | 0.708 | 13.3% | 53.3% | 77.3% / 0.811 | 0 |
| `Vietnamese_Embedding` | 86.5% | 95.5% | 100% | 0.930 | 60.0% | 70.0% | 88.6% / 0.946 | 0 |

On the same 44 answerable v1 questions, FPT drops from 93.2% R@1, 100% R@3 and MRR 0.989 on corpus v1 to 88.6%, 95.5% and 0.946 on corpus v2. In 9 of the 10 FPT questions whose first hit is not relevant, a planted distractor ranks first: GOV.UK or Labour Code chunks on English leave and overtime questions, the Da Nang hub on Hanoi–HCMC delivery, and same-topic sections of sibling runbooks and SOPs. In the tenth (q089), a neighbouring article of the right document ranks first.

## Consequences

- **Week 4 compares on R@1 and MRR, overall and per type**, especially cross-lingual (60% R@1) and near-duplicate (70%). R@3 at 95.5% and R@10 at 100% leave little headroom; a variant that only moves R@3 cannot be told apart on v2.
- **v2 is frozen like v1.** A chunking change means new dataset versions, and the label check fails loudly otherwise.
- **Human review done (2026-10-30):** per ADR-0005, a person checked the 65 new questions and the facts behind them in `scripts/benchmark_data/v2.py`; all were accepted unchanged.
- **Revisit** if the Week 4 variants saturate R@1 too. The next step would be corpus v3 with real-world noise (scanned PDFs, longer documents, more sections per document), not more of the same distractors.
