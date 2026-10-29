"""Smoke-test the FPT AI Marketplace adapters against the real API (ADR-0004, ADR-0010).

    uv run python scripts/smoke_fpt.py

Makes four small paid calls with the keys in .env and checks what FPT's docs leave open:
whether chat replies carry ``usage``, whether ``response_format: json_object`` is accepted,
the embedding dimension, and one grounded answer through the real prompt and parser.
Prints only metadata (status, field names, token counts, latency, dimensions): never the
API key, prompts or completions. Not part of the test suite; CI never runs it.
"""

import asyncio
import json
import math
import sys
import time

from enterprise_knowledge.config import Settings, get_settings
from enterprise_knowledge.domain.access import AccessPolicy
from enterprise_knowledge.domain.chat import ChatMessage, ChatRequest
from enterprise_knowledge.domain.documents import Language, SourceLocation
from enterprise_knowledge.domain.errors import ModelProviderError
from enterprise_knowledge.domain.ids import ChunkId, DocumentId, GroupId, TenantId
from enterprise_knowledge.domain.retrieval import RetrievedEvidence
from enterprise_knowledge.generation.errors import GenerationError
from enterprise_knowledge.generation.output import parse_answer
from enterprise_knowledge.generation.prompts import answer_messages, evidence_label
from enterprise_knowledge.infrastructure.fpt.chat import FptChatModel
from enterprise_knowledge.infrastructure.fpt.client import FptClient, RetryPolicy
from enterprise_knowledge.infrastructure.fpt.embeddings import FptEmbedder

# Synthetic Bamboo Harbor content, matching datasets/fixtures/leave-policy-vi.pdf.
EVIDENCE_TEXT = (
    "Người lao động có thời gian làm việc đủ 12 tháng được nghỉ phép năm 12 ngày làm việc, "
    "hưởng nguyên lương. Cứ đủ 5 năm làm việc thì được nghỉ thêm 1 ngày."
)
QUESTION = "How many days of annual leave does an employee with 12 months of service get?"
PING = 'Reply with exactly this JSON object and nothing else: {"ok": true}'


def report(name: str, ok: bool, **facts: object) -> bool:
    details = ", ".join(f"{k}={v}" for k, v in facts.items())
    print(f"[{'PASS' if ok else 'FAIL'}] {name}: {details}")
    return ok


async def probe_raw_chat(client: FptClient, model: str) -> bool:
    """Raw body shape: which top-level and usage fields FPT actually returns."""
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": PING}],
        "temperature": 0.0,
        "max_tokens": 20,
        "stream": False,
    }
    started = time.perf_counter()
    body = await client.post_json("/chat/completions", payload)
    usage = body.get("usage")
    return report(
        "chat completion shape",
        isinstance(body.get("choices"), list) and bool(body["choices"]),
        latency_ms=round((time.perf_counter() - started) * 1000),
        top_level_keys=sorted(body),
        usage_keys=sorted(usage) if isinstance(usage, dict) else None,
        model_returned=body.get("model"),
    )


async def probe_json_mode(client: FptClient, model: str) -> bool:
    """Is response_format accepted, and does the reply parse as JSON?"""
    chat = FptChatModel(client, model=model, json_mode=True)
    request = ChatRequest(
        messages=(ChatMessage(role="user", content=PING),), max_output_tokens=20, json_mode=True
    )
    try:
        reply = await chat.complete(request)
    except ModelProviderError as exc:
        return report("json mode", False, accepted=False, category=exc.category, error=str(exc))
    try:
        json.loads(reply.content)
        parses = True
    except ValueError:
        parses = False
    return report(
        "json mode",
        parses,
        accepted=True,
        reply_is_json=parses,
        input_tokens=reply.input_tokens,
        output_tokens=reply.output_tokens,
        latency_ms=reply.latency_ms,
    )


async def probe_embeddings(client: FptClient, settings: Settings) -> bool:
    embedder = FptEmbedder(
        client, model=settings.embedding_model, dimension=settings.embedding_dimension
    )
    started = time.perf_counter()
    try:
        vi, en, unrelated = await embedder.embed_documents(
            [EVIDENCE_TEXT, QUESTION, "The forklift battery must be charged overnight."]
        )
    except ModelProviderError as exc:
        return report("embeddings", False, category=exc.category, error=str(exc))
    related, distant = _cosine(vi, en), _cosine(vi, unrelated)
    return report(
        "embeddings",
        related > distant,
        model=embedder.model,
        dimension=len(vi),
        latency_ms=round((time.perf_counter() - started) * 1000),
        cosine_vi_doc_vs_en_question=round(related, 3),
        cosine_vi_doc_vs_unrelated=round(distant, 3),
    )


async def probe_grounded_answer(client: FptClient, settings: Settings, model: str) -> bool:
    """One cross-lingual answer through the real prompt, parser and citation check."""
    evidence = RetrievedEvidence(
        chunk_id=ChunkId("smoke-chunk-1"),
        document_id=DocumentId("smoke-doc"),
        document_version=1,
        title="Quy chế nghỉ phép",
        text=EVIDENCE_TEXT,
        score=0.9,
        source=SourceLocation(page=1, section="Điều 2. Số ngày nghỉ phép năm"),
        access=AccessPolicy(
            tenant_id=TenantId("bamboo-harbor"), allowed_groups=frozenset({GroupId("all-staff")})
        ),
        language=Language.VI,
    )
    chat = FptChatModel(client, model=model, json_mode=settings.llm_json_mode)
    request = ChatRequest(messages=answer_messages(QUESTION, [evidence]), json_mode=True)
    try:
        reply = await chat.complete(request)
    except ModelProviderError as exc:
        return report("grounded answer", False, category=exc.category, error=str(exc))
    try:
        response = parse_answer(reply.content, {evidence_label(0): evidence.chunk_id})
    except GenerationError as exc:
        fenced = reply.content.lstrip().startswith("```")
        return report(
            "grounded answer", False, category=exc.category, fenced=fenced, chars=len(reply.content)
        )
    return report(
        "grounded answer",
        response.status.value == "answered",
        status=response.status.value,
        citations=len(response.citations),
        mentions_12=bool(response.answer and "12" in response.answer),
        answer_chars=len(response.answer or ""),
        input_tokens=reply.input_tokens,
        output_tokens=reply.output_tokens,
        latency_ms=reply.latency_ms,
    )


def _cosine(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    return dot / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b)))


async def main() -> int:
    settings = get_settings()
    if settings.llm_api_key is None or settings.llm_model is None:
        print("EKA_LLM_API_KEY and EKA_LLM_MODEL must be set in .env")
        return 2
    embedding_key = settings.embedding_api_key or settings.llm_api_key
    retry = RetryPolicy(max_attempts=settings.model_max_attempts)
    chat_client = FptClient.create(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        timeout_seconds=settings.llm_request_timeout_seconds,
        retry=retry,
    )
    embedding_client = FptClient.create(
        base_url=settings.embedding_base_url,
        api_key=embedding_key,
        timeout_seconds=settings.embedding_request_timeout_seconds,
        retry=retry,
    )
    print(f"chat model={settings.llm_model} embeddings={settings.embedding_model}")
    results: list[bool] = []
    try:
        for probe in (
            probe_raw_chat(chat_client, settings.llm_model),
            probe_json_mode(chat_client, settings.llm_model),
            probe_embeddings(embedding_client, settings),
            probe_grounded_answer(chat_client, settings, settings.llm_model),
        ):
            try:
                results.append(await probe)
            except ModelProviderError as exc:
                results.append(report("probe", False, category=exc.category, error=str(exc)))
    finally:
        await chat_client.aclose()
        await embedding_client.aclose()
    print(f"{sum(results)}/{len(results)} probes passed")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
