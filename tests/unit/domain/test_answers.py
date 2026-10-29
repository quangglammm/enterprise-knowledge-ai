import pytest
from pydantic import ValidationError

from enterprise_knowledge.domain.answers import AnswerResponse, AnswerStatus, Citation
from enterprise_knowledge.domain.errors import UnknownCitationError
from enterprise_knowledge.domain.ids import ChunkId
from tests.factories import make_evidence


def answered(*chunk_ids: str, text: str = "Nhân viên có 12 ngày phép năm.") -> AnswerResponse:
    return AnswerResponse(
        status=AnswerStatus.ANSWERED,
        answer=text,
        citations=tuple(Citation(chunk_id=ChunkId(c)) for c in chunk_ids),
    )


def test_answered_response_requires_text_and_citations() -> None:
    with pytest.raises(ValidationError, match="citation"):
        answered()
    with pytest.raises(ValidationError, match="answer"):
        answered("c1", text="  ")


def test_citations_must_be_unique() -> None:
    with pytest.raises(ValidationError, match="duplicate"):
        answered("c1", "c1")


def test_abstention_has_no_answer_or_citations() -> None:
    response = AnswerResponse.abstain(reason="no_relevant_evidence")

    assert response.status is AnswerStatus.INSUFFICIENT_EVIDENCE
    assert response.answer is None
    assert response.citations == ()
    assert response.abstention_reason == "no_relevant_evidence"


def test_abstention_with_answer_text_is_rejected() -> None:
    with pytest.raises(ValidationError, match="abstention"):
        AnswerResponse(
            status=AnswerStatus.INSUFFICIENT_EVIDENCE,
            answer="I think it is 12 days",
            abstention_reason="no_relevant_evidence",
        )


def test_verify_citations_accepts_retrieved_chunks() -> None:
    evidence = [make_evidence("c1"), make_evidence("c2")]

    answered("c1", "c2").verify_citations(evidence)


def test_verify_citations_rejects_unknown_chunk() -> None:
    evidence = [make_evidence("c1")]

    with pytest.raises(UnknownCitationError) as excinfo:
        answered("c1", "invented").verify_citations(evidence)

    assert excinfo.value.unknown_ids == frozenset({ChunkId("invented")})
    assert excinfo.value.category == "unknown_citation"


def test_abstention_passes_citation_check_trivially() -> None:
    AnswerResponse.abstain(reason="no_relevant_evidence").verify_citations([])
