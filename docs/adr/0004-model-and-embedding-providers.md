# ADR-0004: Model and embedding providers

- Status: Accepted (model choice within FPT pending the Week 3 spike)
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

## Consequences

- Retries handle FPT throttling and transient errors with backoff and a budget; authentication and validation errors are not retried.
- Traces and logs record provider, model ID, token counts and latency, but never prompts or completions.
- Marketplace models can be retired. The benchmark records model IDs so results stay interpretable, and the runbook covers switching models.
- Revisit if the spike fails its structured-output criteria, if the API proves unstable, or if a target role specifically requires Bedrock.
