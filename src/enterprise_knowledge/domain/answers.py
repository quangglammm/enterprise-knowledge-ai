"""Answers with citations, and the rule that every citation must resolve to evidence."""

from collections.abc import Iterable
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from enterprise_knowledge.domain.errors import UnknownCitationError
from enterprise_knowledge.domain.ids import ChunkId
from enterprise_knowledge.domain.retrieval import RetrievedEvidence


class AnswerStatus(StrEnum):
    ANSWERED = "answered"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class Citation(BaseModel):
    model_config = ConfigDict(frozen=True)

    chunk_id: ChunkId


class AnswerResponse(BaseModel):
    """Abstention is an explicit status, not a phrase inside the answer text."""

    model_config = ConfigDict(frozen=True)

    status: AnswerStatus
    answer: str | None = None
    citations: tuple[Citation, ...] = ()
    abstention_reason: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def _consistent_with_status(self) -> Self:
        if self.status is AnswerStatus.ANSWERED:
            if self.answer is None or not self.answer.strip():
                raise ValueError("answered responses need non-blank answer text")
            if not self.citations:
                raise ValueError("answered responses need at least one citation")
            ids = [c.chunk_id for c in self.citations]
            if len(ids) != len(set(ids)):
                raise ValueError("duplicate citation chunk ids")
            if self.abstention_reason is not None:
                raise ValueError("answered responses must not carry an abstention_reason")
        else:
            if self.answer is not None or self.citations:
                raise ValueError("an abstention must not include answer text or citations")
            if not self.abstention_reason:
                raise ValueError("an abstention needs an abstention_reason")
        return self

    @classmethod
    def abstain(cls, *, reason: str) -> "AnswerResponse":
        return cls(status=AnswerStatus.INSUFFICIENT_EVIDENCE, abstention_reason=reason)

    def verify_citations(self, evidence: Iterable[RetrievedEvidence]) -> None:
        """Raise unless every cited chunk was actually retrieved (RAG-02)."""
        retrieved = {item.chunk_id for item in evidence}
        unknown = {c.chunk_id for c in self.citations} - retrieved
        if unknown:
            raise UnknownCitationError(unknown)
