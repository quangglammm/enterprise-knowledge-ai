"""AnswerQuestion use case: a question to a grounded, cited answer or an abstention (RAG-02).

Retrieval applies access control inside the query (ADR-0003). Without usable evidence the
model is never called. The model's reply gets at most one repair attempt; a reply that
is still invalid is a typed failure, never an abstention (ADR-0009).
"""

import asyncio
import logging
from collections.abc import Mapping, Sequence
from typing import TypedDict

from pydantic import BaseModel, ConfigDict

from enterprise_knowledge.domain.access import Principal
from enterprise_knowledge.domain.answers import AnswerResponse
from enterprise_knowledge.domain.chat import ChatMessage, ChatRequest, ChatResponse
from enterprise_knowledge.domain.ids import ChunkId
from enterprise_knowledge.domain.ports import ChatModel
from enterprise_knowledge.domain.retrieval import RetrievedEvidence
from enterprise_knowledge.domain.text import normalize_nfc
from enterprise_knowledge.generation.errors import (
    InvalidModelOutputError,
    ModelTimeoutError,
    UnresolvedCitationError,
)
from enterprise_knowledge.generation.output import parse_answer
from enterprise_knowledge.generation.prompts import (
    PROMPT_VERSION,
    answer_messages,
    evidence_label,
    repair_message,
)
from enterprise_knowledge.retrieval.search import SearchKnowledge

logger = logging.getLogger(__name__)

NO_EVIDENCE_REASON = "no_relevant_evidence"
DEFAULT_K = 5
DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_MAX_OUTPUT_TOKENS = 1024


class AnswerResult(BaseModel):
    """The response plus what produced it. ``evidence`` is in label order (E1 first)."""

    model_config = ConfigDict(frozen=True)

    response: AnswerResponse
    evidence: tuple[RetrievedEvidence, ...]
    prompt_version: str
    model_id: str | None = None
    repaired: bool = False
    revised: bool = False  # answered again after verification found unsupported claims
    # Summed over the model calls of this answer (the repair included); 0 without a call.
    input_tokens: int = 0
    output_tokens: int = 0
    model_latency_ms: float = 0.0


class GenerateAnswer:
    """Evidence already chosen to a validated answer: prompt, model, parse, one repair.

    Shared by AnswerQuestion and the offline model trial, so the trial measures exactly
    the production path.
    """

    def __init__(
        self,
        *,
        chat: ChatModel,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
    ) -> None:
        self._chat = chat
        self._timeout = timeout_seconds
        self._max_output_tokens = max_output_tokens

    async def __call__(
        self, question: str, evidence: Sequence[RetrievedEvidence], *, revise: bool = False
    ) -> AnswerResult:
        """``question`` must already be NFC-normalized; ``evidence`` must not be empty.

        ``revise`` adds the fixed revision instruction (AGENT-02) to the same prompt."""
        if not evidence:
            raise ValueError("generation needs at least one evidence item")
        evidence = tuple(evidence)
        labels = {evidence_label(i): item.chunk_id for i, item in enumerate(evidence)}
        messages = answer_messages(question, evidence, revise=revise)
        # One deadline for the whole answer, the repair attempt included (ADR-0009).
        try:
            async with asyncio.timeout(self._timeout):
                replies = [await self._complete(messages)]
                try:
                    response = parse_answer(replies[0].content, labels)
                except (InvalidModelOutputError, UnresolvedCitationError) as exc:
                    retry = (
                        *messages,
                        ChatMessage(role="assistant", content=replies[0].content),
                        repair_message(str(exc), evidence_count=len(evidence)),
                    )
                    replies.append(await self._complete(retry))
                    response = self._parse_final(replies, labels)
        except TimeoutError as exc:
            logger.warning("model call timed out", extra={"timeout_seconds": self._timeout})
            raise ModelTimeoutError(f"model did not answer within {self._timeout}s") from exc
        response.verify_citations(evidence)  # defense in depth: labels already resolved

        usage = _usage(replies)
        logger.info(
            "answer generated",
            extra={
                "status": response.status.value,
                "evidence": len(evidence),
                "citations": len(response.citations),
                "repaired": len(replies) > 1,
                **usage,
            },
        )
        return AnswerResult(
            response=response,
            evidence=evidence,
            prompt_version=PROMPT_VERSION,
            model_id=replies[-1].model_id,
            repaired=len(replies) > 1,
            revised=revise,
            input_tokens=usage["input_tokens"],
            output_tokens=usage["output_tokens"],
            model_latency_ms=usage["latency_ms"],
        )

    async def _complete(self, messages: Sequence[ChatMessage]) -> ChatResponse:
        request = ChatRequest(
            messages=tuple(messages),
            max_output_tokens=self._max_output_tokens,
            temperature=0.0,
            json_mode=True,
        )
        return await self._chat.complete(request)

    @staticmethod
    def _parse_final(replies: list[ChatResponse], labels: Mapping[str, ChunkId]) -> AnswerResponse:
        try:
            return parse_answer(replies[-1].content, labels)
        except (InvalidModelOutputError, UnresolvedCitationError) as exc:
            logger.warning(
                "answer rejected after repair",
                extra={"error_category": exc.category, **_usage(replies)},
            )
            raise


class AnswerQuestion:
    """Retrieve access-checked evidence, then generate; abstain when none is usable."""

    def __init__(
        self,
        *,
        search: SearchKnowledge,
        chat: ChatModel,
        k: int = DEFAULT_K,
        min_score: float | None = None,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
    ) -> None:
        self._search = search
        self._k = k
        self._min_score = min_score
        self._generate = GenerateAnswer(
            chat=chat, timeout_seconds=timeout_seconds, max_output_tokens=max_output_tokens
        )

    async def __call__(self, principal: Principal, question: str) -> AnswerResult:
        text = normalize_nfc(question).strip()
        hits = await self._search(principal, text, k=self._k)
        evidence = tuple(h for h in hits if self._min_score is None or h.score >= self._min_score)
        if not evidence:
            logger.info("answer abstained without generation", extra={"retrieved": len(hits)})
            return AnswerResult(
                response=AnswerResponse.abstain(reason=NO_EVIDENCE_REASON),
                evidence=(),
                prompt_version=PROMPT_VERSION,
            )
        return await self._generate(text, evidence)


class _Usage(TypedDict):
    model_id: str
    input_tokens: int
    output_tokens: int
    latency_ms: float
    prompt_version: str


def _usage(replies: Sequence[ChatResponse]) -> _Usage:
    """Model ID, tokens and latency summed over the calls of one answer. Never content."""
    return {
        "model_id": replies[-1].model_id,
        "input_tokens": sum(r.input_tokens for r in replies),
        "output_tokens": sum(r.output_tokens for r in replies),
        "latency_ms": round(sum(r.latency_ms for r in replies), 1),
        "prompt_version": PROMPT_VERSION,
    }
