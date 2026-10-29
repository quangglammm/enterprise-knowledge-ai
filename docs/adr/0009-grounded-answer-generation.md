# ADR-0009: Grounded answer generation and citation validation

- Status: Accepted
- Date: 2026-10-29

## Context

RAG-02 requires answers that match a Pydantic schema, cite only evidence that was retrieved, and abstain when evidence is insufficient. The model provider is FPT AI Marketplace (ADR-0004), but its adapter and the model trial are not built yet, and open-weight models are less reliable at structured output than frontier APIs. Retrieved text is untrusted: the corpus deliberately contains prompt-injection fixtures (ADR-0005). Chunk IDs are 32-character hex UUIDs (ING-02).

## Options considered

Scope:

1. **Generation logic and endpoint now, FPT adapter as a separate item.** Testable with the scripted fake model; the adapter needs real calls and an API key.
2. **Both together.** Roughly double the size for one item.

How the model cites evidence:

1. **Short labels (E1..En) mapped back to chunk IDs in code.** Models copy short labels reliably.
2. **Raw chunk IDs.** No mapping step, but models truncate or mistype long hex strings.

When output is still invalid after the repair attempt:

1. **Typed error (502/504).** Model failures stay distinct from real abstentions.
2. **Abstain** with reason `unverifiable_answer`. Softer for users, but it inflates abstention metrics and hides model failures in the benchmark.

## Decision

- **Scope:** option 1. `POST /v1/answers` returns 503 until a `ChatModel` adapter is wired; the FPT adapter, its settings (`EKA_LLM_*`, answer top-k, minimum score, timeout) and the ADR-0004 trial are the next item.
- **Flow** (`generation/answer.py`):
  1. NFC-normalize the question.
  2. Retrieve with `SearchKnowledge`, which filters by tenant and groups inside the query.
  3. Drop evidence below an optional minimum score (off by default; Week 4 calibrates it).
  4. With no usable evidence, abstain with `no_relevant_evidence` and never call the model.
- **Prompt** `answer-v1` (`generation/prompts.py`): a constant system prompt with no document content. It covers grounding, the untrusted-evidence rule, citations by label, abstention, answering in the question's language, and a single-JSON-object reply. Evidence goes in the user message as `<evidence label="E1" title=… section=… page=…>` blocks, and the question in a `<question>` block. `& < > "` are escaped in all document- and user-derived text, so a document cannot close its block or forge a question.
- **Call:** JSON mode, temperature 0, up to 1024 output tokens, and a 30-second deadline enforced by the caller (`asyncio.timeout`).
- **Parsing** (`generation/output.py`):
  - A Markdown code fence around the JSON is tolerated.
  - The reply must match `{status, answer, citations, abstention_reason}`.
  - Citations are labels; `[E#]` markers in the answer text count as citations too.
  - Any label that was not provided is an `unknown_citation`.
  - Repeated labels collapse.
  - An abstention reason is truncated to 200 characters, with a default when missing.
  - After label mapping, `AnswerResponse.verify_citations` runs again against the evidence as a final check.
- **Repair:** at most one. The retry appends the model's reply and a fixed repair message that names the problem and the valid label range.
- **Failures:** still-invalid output is `invalid_model_output` (502); an unresolved citation is `unknown_citation` (502); a timeout is `model_timeout` (504). An abstention is always a 200 with `status=insufficient_evidence`.
- **Response:** each citation carries its label, chunk ID, document ID and version, title, page, section and character offsets, so a client can show and highlight the source. The model ID and prompt version are included.
- **Logging:** status, evidence and citation counts, whether a repair happened, model ID, input and output tokens, latency and prompt version. Never the question, evidence or answer text.

## Consequences

- Any wording change to the prompt bumps `PROMPT_VERSION`; evaluation runs record it (EVAL-02).
- The fake-model tests prove structure: injected text stays inside an evidence block, and restricted chunks never reach the prompt. Whether a real model *obeys* the untrusted-evidence rule is measured by the benchmark's injection questions and SEC-01, not by unit tests.
- The ADR-0004 model trial measures schema-valid output after this one repair. If the chosen model needs more than one repair to reach 95%, revisit the parser's tolerance or the model choice, not the repair limit.
- Answers are synchronous within the request. The agent workflow (AGENT-01/02) reuses `parse_answer` and the prompt contract rather than adding a second one.
