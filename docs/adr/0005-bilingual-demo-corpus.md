# ADR-0005: Bilingual demo corpus

- Status: Accepted
- Date: 2026-10-29

## Context

The Week 3 benchmark needs a fixed, versioned corpus whose answers are known. It must exercise multi-document answers, document versions, access control and abstention, and it must contain no confidential material. The target users are Vietnamese enterprises where policies are typically written in Vietnamese and technical documentation in English.

## Options considered

1. **Public corpus only** (for example open-source project docs). Pros: realistic writing. Cons: no access groups or versions, monolingual, and ground truth is laborious to establish.
2. **Synthetic fictional company, authored for the benchmark.** Pros: every property under test is designed in; ground truth is known. Cons: authoring effort; risk of unrealistically clean text.
3. **Mixed: synthetic core plus a few public documents.** Pros: designed coverage plus real-world formatting for the parsers.

## Decision

Option 3: a fictional company, **Bamboo Harbor Logistics** (fictional; any resemblance is unintended), with two tenants so cross-tenant isolation can be tested.

Corpus v1 targets about 50 documents:

- **Languages:** about 60% Vietnamese (HR policy, internal regulations, leave and expense rules, onboarding) and 40% English (engineering runbooks, security standard, IT how-tos), plus a few documents mixing both.
- **Formats:** PDF, DOCX, HTML and Markdown, including multi-page PDFs with headings and tables.
- **Versions:** at least five documents with v1 and v2 whose answers differ.
- **Access groups:** `all-staff`, `hr`, `security`, `managers`, `engineering`; at least ten restricted documents.
- **Planted properties:** facts spread across two or three documents; near-duplicate content; text containing instructions aimed at an assistant (prompt-injection fixtures).
- **Public documents:** a handful of public-domain or openly licensed documents to test real-world formatting, with the license recorded per document.

Benchmark question types: monolingual Vietnamese, monolingual English, cross-lingual (Vietnamese question answered by an English document and the reverse), multi-document, version-sensitive, access-sensitive (same question, different principals) and unanswerable.

Layout: `datasets/corpus/v1/` with the documents and a `manifest.jsonl` (document ID, tenant, title, language, format, version, allowed groups, source and license, checksum). Benchmark questions live in `datasets/benchmark/v1/`. Both are versioned; a change creates v2 rather than editing v1.

Documents may be drafted with LLM assistance, then reviewed by hand. Facts used as benchmark ground truth are checked by a person.

## Consequences

- Parser tests use small fixtures from this corpus; the full corpus is used by integration and evaluation runs.
- The corpus and benchmark must be in place before RAG-02 is evaluated (Week 3).
- Vietnamese text requires Unicode NFC normalization at ingestion and in queries, or identical words embed differently.
