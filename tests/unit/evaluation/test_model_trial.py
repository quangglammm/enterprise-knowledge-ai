"""Model trial scoring (ADR-0004): deterministic checks over real GenerateAnswer runs."""

import json
from pathlib import Path

import pytest

from enterprise_knowledge.domain.errors import ModelUnavailableError
from enterprise_knowledge.evaluation.model_trial import (
    CaseKind,
    CaseOutcome,
    TrialCase,
    load_cases,
    run_trial,
    summarize,
)
from enterprise_knowledge.generation.answer import GenerateAnswer
from tests.fakes.chat_model import ScriptedChatModel

DATASET = Path(__file__).resolve().parents[3] / "datasets" / "model_trial" / "cases-v1.jsonl"
LEAVE = {"title": "Quy chế nghỉ phép", "section": "Điều 2", "page": 1, "text": "12 ngày phép."}
OTHER = {"title": "VPN runbook", "text": "Restart the network adapter."}


def case(**overrides: object) -> TrialCase:
    values: dict[str, object] = {
        "id": "vi-01",
        "kind": "answerable",
        "question": "Được nghỉ phép bao nhiêu ngày?",
        "question_language": "vi",
        "evidence": [OTHER, LEAVE],
        "expect_status": "answered",
        "expect_citations": ["E2"],
        "must_contain": ["12|mười hai"],
    }
    values.update(overrides)
    return TrialCase.model_validate(values)


def answered(text: str, *labels: str) -> str:
    return json.dumps({"status": "answered", "answer": text, "citations": list(labels)})


ABSTAIN = json.dumps({"status": "insufficient_evidence", "abstention_reason": "not covered"})


async def run_one(
    trial_case: TrialCase, *script: str | Exception, keep_text: bool = False
) -> CaseOutcome:
    generate = GenerateAnswer(chat=ScriptedChatModel(script))
    [outcome] = await run_trial([trial_case], generate, keep_text=keep_text)
    return outcome


async def test_correct_answer_passes_every_check() -> None:
    outcome = await run_one(case(), answered("Được nghỉ 12 ngày [E2].", "E2"))

    assert outcome.passed
    assert (outcome.schema_valid, outcome.first_try_valid, outcome.status_correct) == (
        True,
        True,
        True,
    )
    assert (outcome.cites_expected, outcome.facts_present, outcome.language_ok) == (
        True,
        True,
        True,
    )
    assert outcome.output_tokens > 0
    assert outcome.answer is None  # text is kept only on request


@pytest.mark.parametrize(
    ("reply", "failed_check"),
    [
        (answered("Được nghỉ 12 ngày [E1].", "E1"), "cites_expected"),
        (answered("Được nghỉ 15 ngày [E2].", "E2"), "facts_present"),
        (answered("Employees get 12 days [E2].", "E2"), "language_ok"),
        (ABSTAIN, "status_correct"),
    ],
    ids=["wrong-citation", "wrong-fact", "wrong-language", "abstained"],
)
async def test_each_check_can_fail_on_its_own(reply: str, failed_check: str) -> None:
    outcome = await run_one(case(), reply)

    assert not outcome.passed
    assert getattr(outcome, failed_check) is False


async def test_repaired_output_is_valid_but_not_first_try() -> None:
    outcome = await run_one(case(), "prose", answered("12 ngày [E2].", "E2"))

    assert (outcome.schema_valid, outcome.first_try_valid, outcome.passed) == (True, False, True)


async def test_invalid_output_after_repair_is_a_schema_failure() -> None:
    outcome = await run_one(case(), "prose", "still prose")

    assert (outcome.schema_valid, outcome.passed) == (False, False)
    assert outcome.error_category == "invalid_model_output"


async def test_provider_error_is_recorded_not_raised() -> None:
    outcome = await run_one(case(), ModelUnavailableError("POST /chat/completions returned 503"))

    assert outcome.error_category == "model_unavailable"
    assert not outcome.passed


async def test_unanswerable_case_passes_only_on_abstention() -> None:
    unanswerable = case(
        kind="unanswerable",
        expect_status="insufficient_evidence",
        expect_citations=[],
        must_contain=[],
    )

    assert (await run_one(unanswerable, ABSTAIN)).passed
    assert not (await run_one(unanswerable, answered("Chắc là 12 ngày [E2].", "E2"))).passed


async def test_obeying_an_injection_fails_the_case() -> None:
    injected = case(kind="injection", must_not_contain=["BANANA"])

    obeyed = await run_one(injected, answered("Được nghỉ 12 ngày [E2]. BANANA", "E2"))
    resisted = await run_one(injected, answered("Được nghỉ 12 ngày [E2].", "E2"))

    assert (obeyed.injection_resisted, obeyed.passed) == (False, False)
    assert (resisted.injection_resisted, resisted.passed) == (True, True)


async def test_answer_text_is_kept_only_on_request() -> None:
    outcome = await run_one(case(), answered("12 ngày [E2].", "E2"), keep_text=True)

    assert outcome.answer == "12 ngày [E2]."


async def test_summary_reports_rates_and_the_adr_0004_verdict() -> None:
    unanswerable = case(
        id="u-01",
        kind="unanswerable",
        expect_status="insufficient_evidence",
        expect_citations=[],
        must_contain=[],
    )
    generate = GenerateAnswer(
        chat=ScriptedChatModel([answered("12 ngày [E2].", "E2"), "prose", "prose", ABSTAIN])
    )
    outcomes = await run_trial([case(), case(id="vi-02"), unanswerable], generate)

    summary = summarize(outcomes, model="m", json_mode=False)

    assert summary.cases == 3
    assert summary.schema_valid_rate == pytest.approx(2 / 3)
    assert summary.abstention_accuracy == 1.0
    assert summary.pass_rate == pytest.approx(2 / 3)
    assert summary.meets_adr_0004 is False  # 67% schema-valid is below 95%


def test_cases_must_cite_labels_that_exist() -> None:
    with pytest.raises(ValueError, match="E3"):
        case(expect_citations=["E3"])


def test_answerable_cases_need_an_expected_citation() -> None:
    with pytest.raises(ValueError, match="expect_citations"):
        case(expect_citations=[])


def test_case_ids_must_be_unique(tmp_path: Path) -> None:
    path = tmp_path / "cases.jsonl"
    line = case().model_dump_json()
    path.write_text(f"{line}\n{line}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="duplicate"):
        load_cases(path)


def test_bundled_dataset_is_valid_and_balanced() -> None:
    cases = load_cases(DATASET)

    kinds = [c.kind for c in cases]
    assert len(cases) == 24
    assert kinds.count(CaseKind.UNANSWERABLE) == 5
    assert kinds.count(CaseKind.INJECTION) == 4
    assert {c.question_language for c in cases} == {"vi", "en"}
    cross_lingual = [c for c in cases if c.id.startswith("x-")]
    assert len(cross_lingual) == 4
