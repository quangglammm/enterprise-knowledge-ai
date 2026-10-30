"""parse_answer: model text to a validated AnswerResponse with resolved citations."""

import json

import pytest

from enterprise_knowledge.domain.answers import AnswerStatus
from enterprise_knowledge.domain.ids import ChunkId
from enterprise_knowledge.generation.errors import (
    InvalidModelOutputError,
    UnresolvedCitationError,
)
from enterprise_knowledge.generation.output import clean_json_reply, parse_answer

LABELS = {"E1": ChunkId("c1"), "E2": ChunkId("c2")}


def answered(answer: str, *citations: str) -> str:
    return json.dumps({"status": "answered", "answer": answer, "citations": list(citations)})


def test_answer_citations_resolve_to_chunk_ids() -> None:
    response = parse_answer(answered("12 ngày [E2].", "E2", "E1"), LABELS)

    assert response.status is AnswerStatus.ANSWERED
    assert response.answer == "12 ngày [E2]."
    assert [c.chunk_id for c in response.citations] == ["c2", "c1"]


def test_json_inside_a_code_fence_is_accepted() -> None:
    content = "```json\n" + answered("12 ngày.", "E1") + "\n```"

    assert parse_answer(content, LABELS).citations[0].chunk_id == "c1"


def test_repeated_citations_are_collapsed() -> None:
    response = parse_answer(answered("12 ngày.", "E1", "E1"), LABELS)

    assert [c.chunk_id for c in response.citations] == ["c1"]


def test_inline_marker_counts_as_a_citation() -> None:
    response = parse_answer(answered("12 ngày [E2].", "E1"), LABELS)

    assert [c.chunk_id for c in response.citations] == ["c1", "c2"]


def test_model_abstention_becomes_insufficient_evidence() -> None:
    content = json.dumps(
        {"status": "insufficient_evidence", "answer": None, "abstention_reason": "x" * 500}
    )

    response = parse_answer(content, LABELS)

    assert response.status is AnswerStatus.INSUFFICIENT_EVIDENCE
    assert response.answer is None
    assert response.abstention_reason == "x" * 200


def test_abstention_without_a_reason_gets_a_default() -> None:
    response = parse_answer(json.dumps({"status": "insufficient_evidence"}), LABELS)

    assert response.abstention_reason == "insufficient_evidence"


@pytest.mark.parametrize(
    "content",
    [
        "Nhân viên có 12 ngày phép.",
        '{"status": "answered", "answer": "12 ngày"',
        json.dumps({"status": "maybe", "answer": "12 ngày", "citations": ["E1"]}),
        json.dumps(["E1"]),
        answered("12 ngày."),
        answered("   ", "E1"),
    ],
    ids=["prose", "truncated", "bad-status", "not-an-object", "no-citations", "blank-answer"],
)
def test_invalid_output_raises_a_typed_error(content: str) -> None:
    with pytest.raises(InvalidModelOutputError) as excinfo:
        parse_answer(content, LABELS)

    assert excinfo.value.category == "invalid_model_output"


@pytest.mark.parametrize(
    "content",
    [answered("12 ngày.", "E1", "E9"), answered("12 ngày [E7].", "E1"), answered("x", "c1")],
    ids=["listed", "inline", "raw-chunk-id"],
)
def test_citation_outside_the_evidence_raises(content: str) -> None:
    with pytest.raises(UnresolvedCitationError) as excinfo:
        parse_answer(content, LABELS)

    assert excinfo.value.category == "unknown_citation"


@pytest.mark.parametrize(
    ("content", "cleaned"),
    [
        ('```json\n{"a": 1}\n```', '{"a": 1}'),
        ('{"claims": [{"x": 1}]', '{"claims": [{"x": 1}]}'),  # final "}" dropped
        ('{"a": "text with } and ] inside"', '{"a": "text with } and ] inside"}'),
        ('{"a": "cut inside a str', '{"a": "cut inside a str'),  # never guessed
        ('{"a": 1}', '{"a": 1}'),
        # Seen from Llama-3.3-70B on calibration case grnd-en-05: a note after the object.
        ('{"a": [1]}\n\nNote: the answer cites the wrong block.', '{"a": [1]}'),
        ('{"a": "} not the end"} trailing', '{"a": "} not the end"}'),
    ],
    ids=[
        "fence",
        "unterminated",
        "brackets-in-string",
        "cut-in-string",
        "untouched",
        "trailing-note",
        "brace-in-string-then-note",
    ],
)
def test_json_replies_are_cleaned_without_inventing_content(content: str, cleaned: str) -> None:
    assert clean_json_reply(content) == cleaned


def test_answer_missing_its_final_brace_is_accepted() -> None:
    content = answered("12 ngày.", "E1").removesuffix("}")

    assert parse_answer(content, LABELS).citations[0].chunk_id == "c1"
