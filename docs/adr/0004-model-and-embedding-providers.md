# ADR-0004: Model and embedding providers

- Status: Accepted; LLM chosen by the model trial of 2026-10-29 (see Model trial)
- Date: 2026-10-29

## Context

The original plan used Amazon Bedrock for both the LLM and embeddings. The project's positioning has changed: AWS demonstrates deployment and operation at scale (S3, SQS, ECS Fargate, CloudWatch, CDK), not the model provider. The corpus is bilingual Vietnamese and English (ADR-0005), so Vietnamese retrieval and generation quality matters more than provider brand.

FPT AI Marketplace offers open-weight LLMs (Llama 3.x, Llama 4 Scout, Qwen2.5, DeepSeek-R1, FPT SaoLa) and embedding models (`Vietnamese_Embedding`, `FPT.AI-e5-large`, `FPT.AI-gte-base`), with inference hosted in Vietnam. `Vietnamese_Embedding` is a BGE-M3 fine-tune (1024 dimensions, 2048-token input, Apache 2.0) with a substantial reported gain over base BGE-M3 on Vietnamese legal retrieval.

Unknowns at the time of writing: whether the API is fully OpenAI-compatible, support for JSON mode or tool calling, rate limits, and model retirement policy.

## Options considered

1. **Amazon Bedrock.** Pros: IAM auth, same cloud as deployment, strong structured output with Claude models. Cons: weaker fit for Vietnamese-tuned embeddings; no longer required by the project's positioning.
2. **FPT AI Marketplace.** Pros: Vietnamese-tuned embeddings, Vietnam data residency, open-weight models. Cons: API-key auth from outside AWS, less documented API, structured-output reliability unproven.
3. **Self-hosted open models.** Pros: full control. Cons: GPU operation is out of scope.

## Decision

Use FPT AI Marketplace for both the LLM and embeddings, behind the `ChatModel` and `Embedder` ports.

- **Embeddings:** default `Vietnamese_Embedding`, dimension 1024. The dimension is configuration, validated at startup against the vector column; every stored embedding records `embedding_model` and `embedding_dim`. One embedding model per index; changing it means re-indexing.
- **Bilingual check:** because the model is tuned for Vietnamese, Week 4 compares it with at least one multilingual candidate (for example `FPT.AI-e5-large`) on the bilingual benchmark, including cross-lingual questions, before the baseline is frozen.
- **LLM:** chosen in a Week 3 spike from the marketplace's instruct models. Acceptance criteria: at least 95% schema-valid JSON over 20 grounded-answer prompts (Vietnamese and English) after at most one repair attempt; correct abstention on no-evidence prompts; latency and cost recorded. The result amends this ADR.
- **Adapter:** one HTTP adapter in `infrastructure/` (httpx), configured by `EKA_LLM_*` and `EKA_EMBEDDING_*` settings: base URL, model ID, API key as `SecretStr`, timeouts. Model IDs are pinned and recorded in every evaluation run.
- **Bedrock** is not implemented. The ports keep it possible as a future adapter.
- **AWS** remains the deployment platform. In AWS, the FPT API key lives in Secrets Manager and calls leave the VPC over HTTPS.
- **Tests and CI** never call FPT. They use deterministic fakes with the same embedding dimension.

## Model trial (2026-10-29)

`scripts/model_trial.py` ran `datasets/model_trial/cases-v1.jsonl` (24 cases: 6 Vietnamese, 5 English, 4 cross-lingual, 5 unanswerable, 4 prompt injection) through the production generation path (`GenerateAnswer`, prompt `answer-v1`), one run per configuration, at temperature 0. Raw results without answer text: `docs/evaluation/model-trial-20261029-145905.json`.

| Model | JSON mode | Passed | Schema-valid (first try) | Abstention | Injection | Citations | Facts | Language | p50 / p95 latency | Tokens in/out per answer |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Llama-3.3-70B-Instruct | off | 22/24 | 100% (100%) | 5/5 | 4/4 | 100% | 94% | 94% | 1.36 s / 2.33 s | 393 / 38 |
| Llama-3.3-70B-Instruct | on | 22/24 | 100% (100%) | 5/5 | 4/4 | 100% | 94% | 94% | 1.33 s / 2.56 s | 393 / 38 |
| Qwen2.5-7B-instruct | both | — | — | — | — | — | — | — | — | — |
| Llama-4-Scout-17B-16E | both | — | — | — | — | — | — | — | — | — |

- **Decision:** `Llama-3.3-70B-Instruct` meets the acceptance criteria (≥ 95% schema-valid after at most one repair; correct abstention on every unanswerable case) and is the LLM. `EKA_LLM_MODEL` stays an explicit setting rather than a code default.
- **JSON mode:** results were identical with and without `response_format`, and the prompt alone produced valid JSON on the first try in 24/24 cases. `EKA_LLM_JSON_MODE` stays `false`, so the app does not depend on an undocumented provider feature.
- **Failures (the same two in both modes):**
  - `x-02`, a real defect: an English question over Vietnamese evidence was answered in Vietnamese. The other 3 cross-lingual cases passed.
  - `en-05`, a strict check: asked which gateway serves Ho Chi Minh City, the model returned the gateway's address instead of its name `HCM-1`. The answer is grounded, but it is not what was asked.
- **Observed but not scored:** answers are terse and carry no inline `[E#]` markers, although the prompt asks for them; citations come only from the `citations` list. A later prompt version can address both this and the language slip, and the trial measures the change.
- **Not compared:** the Qwen and Llama 4 IDs were rejected by the gateway (`model_request_rejected`) on the first call, so they were never evaluated. Their exact IDs or availability on this account must be checked on the marketplace before comparing them.
- **Limits:** 24 cases and one run per configuration, with deterministic string checks. This is evidence for the choice, not a quality benchmark; EVAL-01/02 measure answer quality. Cost is reported as tokens only, because FPT prices were not recorded.

## Consequences

- Retries handle FPT throttling and transient errors with backoff and a budget; authentication and validation errors are not retried.
- Traces and logs record provider, model ID, token counts and latency, but never prompts or completions.
- Marketplace models can be retired. The benchmark records model IDs so results stay interpretable, and the runbook covers switching models.
- Revisit if the spike fails its structured-output criteria, if the API proves unstable, or if a target role specifically requires Bedrock.
