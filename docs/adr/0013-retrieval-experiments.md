# ADR-0013: Retrieval experiments: versioned configurations and derived label sets

- Status: Accepted
- Date: 2026-10-30

## Context

Week 4 must compare retrieval variants with "reproducible experiment configurations" (plan, Week 4). Benchmark v2 (ADR-0012) is the yardstick. Two problems had to be solved first.

1. A report recorded the dataset, chunking and embedding model, but not the rest of the setup (for example whether the ADR-0006 embedding header was on) or the code revision.
2. Labels are chunk IDs, valid only under the chunking settings the label set pins (ADR-0011). A chunking experiment therefore needs labels for each setting it tests.

The chunking lever also had to change. With a heading always starting a chunk, `max_chars` from 400 to 3000 alters only 1 to 4 of v2's 49 documents, so the experiment compares section packing instead (ADR-0006 amendment).

## Options considered

Labels for other chunking settings:

1. **Derived label sets:** rebuild labels from the same authoring quotes under each setting, into `datasets/benchmark/<version>-packed<max>/` or `-c<max>/`. Pros: no format change; the loader's checks apply unchanged. Cons: one directory per setting; a quote split by a chunk boundary must be shortened.
2. **Character-span labels:** relevance is overlap with a quote's span. Pros: works for any chunking. Cons: changes ADR-0011's label format and needs offsets recorded at ingestion.

Configuration format: TOML files read with the standard library's `tomllib` (no dependency, comments allowed) vs CLI flags only (nothing to commit, so nothing reproducible).

## Decision

- **Derived label sets (option 1).** `scripts/build_benchmark.py --version v2 [--chunking MAX,OVERLAP] [--pack-sections]` writes a set with the same questions and question IDs, pinned to its chunking settings. It never rewrites the corpus manifest. The first sets are `v2-packed1200` and `v2-packed800`. All 115 questions' quotes resolve under both.
- **`ExperimentConfig`** (`evaluation/experiment.py`, frozen, unknown keys rejected) names:
  - the corpus and the label set (which pins chunking);
  - the embedder (`hashing` or `fpt`);
  - `embedding_header` (default on, as in production);
  - the k values.

  Configurations live in `experiments/<week>/*.toml`.
- **Every report records** its `ExperimentConfig` and `code_revision` (short git SHA, suffixed `-dirty` for uncommitted changes). Reports from before Week 4 load with both fields empty.
- **Runner:** `scripts/run_benchmark.py --experiment <file>`. `--embedding hashing` overrides the embedder for a free dry run of a paid experiment. Without `--experiment`, the flags form an `ad-hoc` configuration.
- **Comparison:** `compare_reports` (`evaluation/comparison.py`) requires the same question IDs. It returns metric deltas plus the questions whose reciprocal rank improved or worsened, because a mean can hide offsetting changes. `scripts/compare_reports.py` prints that, with cross-lingual, near-duplicate and multi-document Recall@1.
- **Headline metrics:** Recall@1 and MRR. Benchmark v2 leaves little headroom at Recall@3 (ADR-0012).

## Results (2026-10-30)

First four experiments on FPT embeddings, written up in `docs/evaluation/week4-retrieval-experiments.md`:
- **Baseline:** 86.5% Recall@1, MRR 0.930, reproduced exactly on a rerun.
- **No header:** 81.5%, with 11 questions worse and 2 better (sign test p = 0.022).
- **Packed-1200:** 83.5% (p = 0.118).
- **Packed-800:** 82.5% (p = 0.077).

The production defaults stand.

## Consequences

- An experiment is a committed file plus a report that points back to it and to a commit. A result without a clean `code_revision` is not quoted as a finding.
- `IngestDocument` gained `embedding_header`, which only experiments switch off.
- Hybrid retrieval adds a retrieval-mode field to `ExperimentConfig` when it lands. The field is not added before the feature exists.
- **Comparisons across label sets need care:** chunk counts differ, so per-question changes are the primary evidence and means are secondary.
- **Revisit** if the number of derived sets grows beyond a handful; character-span labels would then pay for their format change.
