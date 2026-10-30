"""Judge calibration (ADR-0015): the judge scored against hand-labelled verdicts."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from enterprise_knowledge.domain.errors import ModelRateLimitedError
from enterprise_knowledge.evaluation.judge import AnswerJudge, Correctness
from enterprise_knowledge.evaluation.judge_calibration import (
    CalibrationCase,
    load_calibration,
    run_calibration,
)
from tests.fakes.chat_model import ScriptedChatModel

REPO = Path(__file__).resolve().parents[3]

CORRECTNESS_CASE = {
    "id": "corr-vi-01",
    "kind": "correctness",
    "language": "vi",
    "question": "Phụ cấp ăn uống mỗi ngày là bao nhiêu?",
    "reference": "300.000 đồng.",
    "answer": "300.000 đồng mỗi ngày công tác.",
    "expect_verdict": "correct",
    "note": "paraphrase",
}
GROUNDING_CASE = {
    "id": "grnd-en-01",
    "kind": "grounding",
    "language": "en",
    "question": "How long must passwords be?",
    "answer": "At least 14 characters, changed every 90 days.",
    "evidence": [
        {"title": "Password Standard", "text": "Passwords must be at least 14 characters."}
    ],
    "cited": ["E1"],
    "expect_faithful": False,
    "expect_citation_supported": False,
    "note": "second claim is not in the evidence",
}


def test_cases_must_carry_the_expectations_of_their_kind() -> None:
    with pytest.raises(ValidationError, match="expect_verdict"):
        CalibrationCase.model_validate(CORRECTNESS_CASE | {"expect_verdict": None})
    with pytest.raises(ValidationError, match="evidence"):
        CalibrationCase.model_validate(GROUNDING_CASE | {"evidence": []})
    with pytest.raises(ValidationError, match="cited"):
        CalibrationCase.model_validate(GROUNDING_CASE | {"cited": ["E4"]})


async def test_agreement_is_measured_per_metric() -> None:
    cases = [CalibrationCase.model_validate(c) for c in (CORRECTNESS_CASE, GROUNDING_CASE)]
    chat = ScriptedChatModel(
        [
            json.dumps({"verdict": "partially_correct", "reason": "x"}),  # disagrees
            json.dumps(
                {
                    "claims": [
                        {"claim": "14 characters", "supported_by": ["E1"]},
                        {"claim": "90 days", "supported_by": []},
                    ]
                }
            ),  # agrees on both grounding metrics
        ]
    )

    report = await run_calibration(cases, AnswerJudge(chat=chat), dataset_sha256="0" * 64)

    assert report.correctness_agreement == 0.0
    assert report.faithfulness_agreement == 1.0
    assert report.citation_support_agreement == 1.0
    assert report.judge_errors == 0
    [first, second] = report.outcomes
    assert (first.expected, first.judged) == ("correct", Correctness.PARTIALLY_CORRECT.value)
    assert second.agrees
    assert report.judge_model == "fake-chat"
    assert report.judge_prompt_version == "judge-v2"


async def test_judge_failures_are_counted_not_hidden() -> None:
    cases = [CalibrationCase.model_validate(CORRECTNESS_CASE)]
    chat = ScriptedChatModel([ModelRateLimitedError("throttled")])

    report = await run_calibration(cases, AnswerJudge(chat=chat), dataset_sha256="0" * 64)

    assert report.judge_errors == 1
    assert report.outcomes[0].error_category == "model_rate_limited"
    assert report.correctness_agreement is None  # no case was judged


def test_bundled_calibration_set_covers_every_verdict() -> None:
    cases = load_calibration(REPO / "datasets" / "judge_calibration" / "cases-v2.jsonl")

    correctness = [c for c in cases if c.kind == "correctness"]
    grounding = [c for c in cases if c.kind == "grounding"]
    assert len(cases) >= 20
    assert {c.expect_verdict for c in correctness} == set(Correctness)
    assert {(c.expect_faithful, c.expect_citation_supported) for c in grounding} == {
        (True, True),
        (True, False),
        (False, False),
    }
    assert {c.language for c in cases} == {"vi", "en"}


def test_calibration_v2_keeps_v1_and_adds_terse_answers() -> None:
    folder = REPO / "datasets" / "judge_calibration"
    v1 = load_calibration(folder / "cases-v1.jsonl")

    v2 = load_calibration(folder / "cases-v2.jsonl")

    assert v1 == v2[: len(v1)]
    added = v2[len(v1) :]
    assert added
    assert all("terse" in case.note for case in added)
