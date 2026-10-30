# ADR-0014: Hybrid retrieval: IDF-weighted full-text search fused with vectors by RRF

- Status: Accepted
- Date: 2026-10-30

## Context

Plan revision 8 keeps hybrid retrieval in Postgres: `tsvector` full-text search plus pgvector, merged with reciprocal rank fusion. On benchmark v2 the remaining vector misses are mostly lexical distinctions the embedding blurs: Da Nang vs Hanoi delivery, GOV.UK or the Labour Code vs company policy (Week 4 write-up). Constraints:

- the corpus is bilingual and Postgres ships no Vietnamese dictionary;
- tenant and ACL filters must sit inside every query (ADR-0003);
- the evidence gate (`EKA_ANSWER_MIN_SCORE`) is calibrated on cosine similarity;
- the AWS plan targets managed Postgres (RDS), so extensions beyond pgvector are a deployment risk.

## Options considered

Lexical ranking:

1. **`ts_rank_cd` over an OR query.** Built in. But Postgres ranking has no inverse document frequency, so in natural-language questions common words ("the", "là", "được") would outweigh rare ones.
2. **BM25-style IDF computed in SQL.** A chunk's relevance is the sum, over the query terms it contains, of `ln(1 + (N − df + 0.5) / (df + 0.5))`, with N and df counted over the chunks the principal may read. No extension needed. Term frequency and length normalization are left out.
3. **ParadeDB `pg_search`.** True BM25, but a different Postgres image, and not available on RDS.

Fusion:

1. **In `SearchKnowledge`, via a new port method:** pure, store-agnostic, tested with fakes. Costs two round trips.
2. **In one SQL statement:** one round trip, but the fake store must reimplement the fusion.

## Decision

- **Lexical option 2, fusion option 1.**
- **Indexing:** migration `0002` adds `chunks.lexemes`, computed as `to_tsvector('simple', concat_ws(' ', title, section, text))`, with a GIN index. Existing rows are backfilled.
  - The `simple` config lowercases and keeps diacritics: "Đà Nẵng" does not match "Da Nang", because diacritics distinguish Vietnamese words.
  - Dotted tokens (`gov.uk`, `tp.hcm`, `1.500.000`) stay whole.
- **Port:** `ChunkSearch.search_lexical(principal, query_text, query_vector, *, k, embedding_model)`.
  - It applies the same tenant, groups, serving-version and model filters in its SQL.
  - It returns only chunks that match at least one term, ranked by IDF relevance with ties by chunk ID.
  - `score` is still cosine similarity to the query vector, so every mode reports evidence on one scale.
- **Use case:** `SearchKnowledge` takes `RetrievalSettings`, with `mode` = `vector` (default) or `hybrid`, `rrf_k` = 60 and `candidates` = 50.
  - In hybrid mode it takes the top `max(k, candidates)` from each list and fuses them with `reciprocal_rank_fusion`: score `Σ 1/(rrf_k + rank)`, ties by chunk ID.
  - `ensure_accessible` still checks the fused result.
- **Settings:** `EKA_RETRIEVAL_MODE`, `EKA_RRF_K` and `EKA_HYBRID_CANDIDATES`. `ExperimentConfig` records the same three (ADR-0013).

## Results (2026-10-30)

On benchmark v2 with FPT embeddings, hybrid scores 73.0% Recall@1 against vector's 86.5%: 0 questions improved, 24 worsened, and Recall@10 fell from 100% to 80.5%.

- **Cause:** with `rrf_k` = 60 and 50 candidates, any chunk in both lists outranks every chunk found by only one.
- **Contributing:** the lexical list is full for 91 of 115 questions (common-word matches) and finds cross-lingual answers in only 11 of 30 questions.

Vector stays the default. Details are in `docs/evaluation/week4-retrieval-experiments.md`. Any re-tuning needs a development/test split of the questions first.

## Consequences

- **Production default:** vector search stays the default; on benchmark v2, hybrid as configured is worse (see Results).
- **Cost:** a hybrid search makes two queries. The lexical query scans the principal's visible chunks to count document frequencies, which is O(visible chunks × query terms). That is fine for the benchmark and a demo tenant. At scale, df would come from a maintained statistics table, or `pg_search` once the deployment target allows it.
- **Fusion only reorders evidence:** both inputs are already filtered, so hybrid never weakens access control. The contract tests check lexical filtering on the fake and on Postgres, and the Postgres benchmark tests run in both modes.
- **The fake approximates Postgres's tokenizer**, as `\w+(\.\w+)*` lowercased. A contract test that passes on one and fails on the other points to tokenizer drift.
- **Revisit** the fixed RRF constant and the equal list weights if hybrid helps one question type and hurts another.
