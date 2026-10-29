"""/v1/answers: grounded answers with validated citations (RAG-02)."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from enterprise_knowledge.api.errors import ServiceUnavailableError
from enterprise_knowledge.api.identity import current_principal
from enterprise_knowledge.api.services import Services, get_services
from enterprise_knowledge.domain.access import Principal
from enterprise_knowledge.domain.retrieval import RetrievedEvidence
from enterprise_knowledge.generation.answer import AnswerResult
from enterprise_knowledge.generation.prompts import evidence_label

router = APIRouter(prefix="/v1", tags=["answers"])

PrincipalDep = Annotated[Principal, Depends(current_principal)]
ServicesDep = Annotated[Services, Depends(get_services)]
_ERRORS: dict[int | str, dict[str, Any]] = {
    code: {"description": "Error body: {error: {category, message, request_id}}"}
    for code in (401, 422, 502, 503, 504)
}


class AnswerIn(BaseModel):
    question: str = Field(min_length=1, max_length=2000)


class CitationOut(BaseModel):
    """A cited chunk with enough source metadata to show and highlight it."""

    label: str
    chunk_id: str
    document_id: str
    document_version: int
    title: str
    page: int | None
    section: str | None
    char_start: int | None
    char_end: int | None

    @classmethod
    def of(cls, label: str, evidence: RetrievedEvidence) -> "CitationOut":
        return cls(
            label=label,
            chunk_id=evidence.chunk_id,
            document_id=evidence.document_id,
            document_version=evidence.document_version,
            title=evidence.title,
            page=evidence.source.page,
            section=evidence.source.section,
            char_start=evidence.source.char_start,
            char_end=evidence.source.char_end,
        )


class AnswerOut(BaseModel):
    status: str
    answer: str | None
    abstention_reason: str | None
    citations: list[CitationOut]
    model_id: str | None
    prompt_version: str

    @classmethod
    def of(cls, result: AnswerResult) -> "AnswerOut":
        labelled = {
            item.chunk_id: (evidence_label(i), item) for i, item in enumerate(result.evidence)
        }
        response = result.response
        return cls(
            status=response.status.value,
            answer=response.answer,
            abstention_reason=response.abstention_reason,
            citations=[CitationOut.of(*labelled[c.chunk_id]) for c in response.citations],
            model_id=result.model_id,
            prompt_version=result.prompt_version,
        )


@router.post("/answers", responses=_ERRORS)
async def answer_question(
    body: AnswerIn, principal: PrincipalDep, services: ServicesDep
) -> AnswerOut:
    """Answer from evidence the caller may read, or abstain. Model failures are 502/504."""
    if services.answer is None:
        raise ServiceUnavailableError("answer generation is not configured")
    return AnswerOut.of(await services.answer(principal, body.question))
