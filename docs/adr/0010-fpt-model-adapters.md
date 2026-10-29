# ADR-0010: FPT model adapters: transport, retries and errors

- Status: Accepted
- Date: 2026-10-29

## Context

ADR-0004 chose FPT AI Marketplace for chat and embeddings, behind the `ChatModel` and `Embedder` ports, with an httpx adapter and `EKA_LLM_*` / `EKA_EMBEDDING_*` settings. RAG-02 (ADR-0009) left `/v1/answers` returning 503 until a chat adapter exists. The hashing embedder has no semantics, so a benchmark run on it would mean nothing.

FPT's public API docs ([fpt-corp/ai-marketplace](https://github.com/fpt-corp/ai-marketplace)) show an OpenAI-style gateway at `https://mkp-api.fptcloud.com`: `POST /chat/completions` and `POST /embeddings`, with `Authorization: Bearer <key>`. They do not document `response_format` (JSON mode), `max_tokens`, `usage`, error status codes or rate limits.

## Options considered

Scope:

1. **Chat and embeddings together.** They share the HTTP client, auth and retry code, and Week 3 needs real embeddings.
2. **Chat only.** Smaller, but retrieval stays on the hashing embedder.

Retries:

1. **A small hand-written loop** with injected sleep and randomness. Deterministic, instant tests and no new dependency.
2. **tenacity.** Declarative policies, but a dependency, and its wait strategies must be patched to make tests deterministic.

## Decision

- **Scope:** option 1. `infrastructure/fpt/` holds `FptClient` (transport and retries), `FptChatModel` and `FptEmbedder`. httpx moves from a dev dependency to a runtime dependency, used only in `infrastructure/`.
- **Retries** (option 1):
  - At most `EKA_MODEL_MAX_ATTEMPTS` attempts (default 3, first attempt included).
  - Retried: 429, 408, 500, 502, 503, 504, connection errors and timeouts.
  - Backoff is exponential with full jitter (`random × min(8 s, 0.5 s × 2^(n-1))`). A delay-seconds `Retry-After` is honoured up to the same 8 s cap.
  - Never retried: 401/403, other 4xx, and a success status with a malformed body.
  - Each answer's overall deadline (`EKA_ANSWER_TIMEOUT_SECONDS`, 45 s, which must be at least one request timeout) bounds everything, retries and the repair attempt included.
- **Errors:** provider-neutral classes in `domain/errors.py`, so ingestion records them as `error_category` and the API maps them in one place:
  - `model_rate_limited`: 503, `retryable`
  - `model_unavailable`: 502, `retryable`
  - `model_auth_failed`: 502
  - `model_request_rejected`: 502
  - `model_invalid_response`: 502

  Messages carry the method, path and status only, never the request or response body, the prompt or the key.
- **Chat:**
  - The request is `{model, messages, temperature, max_tokens, stream: false}`.
  - `response_format: {"type": "json_object"}` is sent only when `EKA_LLM_JSON_MODE=true`. It is off by default because FPT does not document it; the model trial decides. The prompt asks for JSON either way, and the parser tolerates code fences (ADR-0009).
  - `choices[0].message.content` must be non-blank text.
  - Missing `usage` is recorded as 0 tokens.
  - Latency is measured around the HTTP call, retries included.
- **Embeddings:**
  - The request is `{model, input: [texts]}`, with no request for an empty list.
  - Results are ordered by `index`.
  - The count must match the inputs, and every vector must have `EKA_EMBEDDING_DIMENSION` finite numbers before it can reach the database.
  - The ingestion use case batches 32 texts per call.
- **Settings:**
  - `EKA_LLM_BASE_URL`, `EKA_LLM_API_KEY` (secret), `EKA_LLM_MODEL`, `EKA_LLM_JSON_MODE`, `EKA_LLM_REQUEST_TIMEOUT_SECONDS` (25 s)
  - `EKA_EMBEDDING_PROVIDER` (`hashing` | `fpt`), `EKA_EMBEDDING_BASE_URL`, `EKA_EMBEDDING_API_KEY`, `EKA_EMBEDDING_MODEL` (`Vietnamese_Embedding`), `EKA_EMBEDDING_REQUEST_TIMEOUT_SECONDS` (20 s)
  - `EKA_ANSWER_TOP_K` (5), `EKA_ANSWER_MIN_SCORE` (off), `EKA_ANSWER_TIMEOUT_SECONDS` (45 s)
  - Validation: `fpt` requires an embedding key, and an LLM key requires a model.
- **Wiring:**
  - The httpx clients open and close with the app lifespan.
  - `/v1/answers` is enabled exactly when `EKA_LLM_API_KEY` is set.
  - No LLM model is defaulted: the ADR-0004 trial chooses it.
- **Tests:** `httpx.MockTransport` with scripted responses. No test or CI run reaches the network.

## Consequences

- Switching `EKA_EMBEDDING_PROVIDER` or `EKA_EMBEDDING_MODEL` makes previously indexed chunks invisible, because search filters by `embedding_model`. Documents must be re-uploaded or re-indexed; a re-index command is out of scope until JOB-01.
- The ADR-0004 model trial must confirm or correct the undocumented parts: JSON mode, `usage`, error statuses, rate limits and the `Retry-After` form. Any correction amends this ADR.
- Retrying a chat request after a read timeout can bill twice for one answer. The attempt cap bounds the cost; token usage per answer is logged.
- `retryable` on errors lets the Week 5 worker decide between requeueing a job and failing it, without re-classifying HTTP statuses.
