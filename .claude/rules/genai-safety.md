---
paths:
  - "src/enterprise_knowledge/retrieval/**/*.py"
  - "src/enterprise_knowledge/generation/**/*.py"
  - "src/enterprise_knowledge/agents/**/*.py"
  - "src/enterprise_knowledge/infrastructure/**/*.py"
---

# Retrieval, generation and agent rules

## Retrieval

- Tenant and ACL filters are part of the SQL or vector query itself. Never retrieve first and filter in Python.
- With an HNSW index, filtered queries can return fewer than k rows. Handle that explicitly (iterative scan or a documented fallback) and test it.
- Empty retrieval results lead to abstention, not to calling the model with no evidence.
- Retrieval parameters (k, chunk size, fusion weights, model names) come from settings and are recorded with each evaluation run.

## Prompts and generation

- Prompts live in versioned template files or constants with a version string, not inline f-strings scattered through code.
- Retrieved text goes into a clearly delimited evidence section, labeled as untrusted. System instructions never include document content.
- Model output is parsed into a Pydantic schema. Invalid output gets at most one repair attempt, then a typed failure.
- After parsing, verify every cited chunk ID is in the retrieved set. Unknown citations reject the answer.
- Abstention is an explicit field in the response schema, not a phrase in the answer text.

## Model calls

- All model access goes through the `ModelProvider` / `Embedder` ports. No direct SDK calls outside `infrastructure/`.
- Every call has a timeout and a bounded retry with backoff and jitter for throttling and transient errors only. Never retry validation errors.
- Record model ID, input and output token counts, and latency for each call as structured log fields or metrics. Do not log the prompt or completion text.

## Agents

- Implement workflows as an explicit state machine with typed states and allowed transitions. Invalid transitions raise.
- Enforce max steps, max model calls and a wall-clock deadline per request. Hitting a limit ends in abstention or a controlled failure, never a partial unverified answer.
- Tools available to an agent are an allowlist chosen in code. Retrieved content cannot add or enable tools.
- Route simple questions to direct RAG. The agent path must justify itself in the evaluation.
