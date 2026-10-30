"""Answer-quality evaluation (EVAL-02, ADR-0015) with a scripted answerer and judge."""

import json
from pathlib import Path
from typing import Any

from enterprise_knowledge.agents.modes import ModeAnswer
from enterprise_knowledge.domain.access import Principal
from enterprise_knowledge.domain.answers import AnswerResponse, AnswerStatus, Citation
from enterprise_knowledge.domain.ids import ChunkId, DocumentId, chunk_id_for
from enterprise_knowledge.evaluation.answer_quality import AnswerRunSettings, evaluate_answers
from enterprise_knowledge.evaluation.benchmark import BenchmarkDataset, BenchmarkQuestion, Corpus
from enterprise_knowledge.evaluation.judge import AnswerJudge
from enterprise_knowledge.generation.answer import AnswerResult
from enterprise_knowledge.generation.errors import ModelTimeoutError
from enterprise_knowledge.ingestion.chunking import ChunkingSettings
from enterprise_knowledge.retrieval.search import RetrievalSettings
from tests.factories import make_evidence
from tests.fakes.chat_model import ScriptedChatModel

GOLD = chunk_id_for(DocumentId("leave"), 2, 0)
OTHER = chunk_id_for(DocumentId("vpn"), 1, 0)
STAFF = {"tenant": "bamboo", "groups": ["all-staff"]}
SETTINGS = AnswerRunSettings(
    retrieval=RetrievalSettings(), k=5, min_score=None, embedding_model="fake-embed"
)


def question(qid: str, *, answerable: bool = True) -> BenchmarkQuestion:
    gold = [{"document_id": "leave", "version": 2, "chunk_index": 0, "chunk_id": GOLD}]
    return BenchmarkQuestion.model_validate(
        {
            "id": qid,
            "question": "How many days of annual leave?",
            "language": "en",
            "types": ["english"] if answerable else ["english", "unanswerable"],
            "principal": STAFF,
            "evidence": [gold] if answerable else [],
            "reference_answer": "14 days." if answerable else None,
        }
    )


def dataset(*questions: BenchmarkQuestion) -> BenchmarkDataset:
    corpus = Corpus(root=Path("."), manifest_sha256="a" * 64, documents=())
    return BenchmarkDataset(
        version="v2", corpus=corpus, chunking=ChunkingSettings(), questions=questions
    )


EVIDENCE = (make_evidence(str(OTHER), text="VPN error 809."), make_evidence(str(GOLD)))


def answered(*cited: ChunkId) -> AnswerResult:
    return AnswerResult(
        response=AnswerResponse(
            status=AnswerStatus.ANSWERED,
            answer="14 days [E2].",
            citations=tuple(Citation(chunk_id=c) for c in cited),
        ),
        evidence=EVIDENCE,
        prompt_version="answer-v1",
        model_id="fake-answer",
        input_tokens=100,
        output_tokens=10,
    )


def abstained() -> AnswerResult:
    return AnswerResult(
        response=AnswerResponse.abstain(reason="insufficient"),
        evidence=EVIDENCE,
        prompt_version="answer-v1",
        model_id="fake-answer",
        input_tokens=90,
        output_tokens=5,
    )


class ScriptedAnswerer:
    """Returns one scripted result (or raises) per call, in order, as direct RAG would."""

    def __init__(self, *script: AnswerResult | ModeAnswer | Exception) -> None:
        self._script = list(script)
        self.questions: list[str] = []

    async def __call__(self, principal: Principal, text: str) -> ModeAnswer:
        self.questions.append(text)
        step = self._script.pop(0)
        if isinstance(step, Exception):
            raise step
        if isinstance(step, ModeAnswer):
            return step
        return ModeAnswer(mode="direct", answer=step, steps=2, model_calls=1)


def judge(*replies: dict[str, Any]) -> tuple[AnswerJudge, ScriptedChatModel]:
    chat = ScriptedChatModel([json.dumps(r) for r in replies], model_id="fake-judge")
    return AnswerJudge(chat=chat), chat


CORRECT = {"verdict": "correct", "reason": "same"}
GROUNDED = {"claims": [{"claim": "14 days", "supported_by": ["E2"]}]}
UNGROUNDED = {"claims": [{"claim": "14 days", "supported_by": []}]}


async def test_answered_question_is_judged_on_three_separate_metrics() -> None:
    answer_judge, _ = judge(CORRECT, GROUNDED)

    report = await evaluate_answers(
        dataset(question("q001")), ScriptedAnswerer(answered(GOLD)), answer_judge, SETTINGS
    )

    [outcome] = report.outcomes
    assert outcome.status == "answered"
    assert outcome.status_correct
    assert outcome.correctness == "correct"
    assert outcome.faithful is True
    assert outcome.citation_supported is True
    assert outcome.cites_gold is True
    assert outcome.retrieved_gold is True
    assert (report.correct_rate, report.faithfulness_rate, report.citation_support_rate) == (
        1.0,
        1.0,
        1.0,
    )


async def test_citation_outside_the_gold_chunks_is_reported() -> None:
    answer_judge, _ = judge(CORRECT, UNGROUNDED)

    report = await evaluate_answers(
        dataset(question("q001")), ScriptedAnswerer(answered(OTHER)), answer_judge, SETTINGS
    )

    [outcome] = report.outcomes
    assert outcome.cites_gold is False
    assert outcome.faithful is False
    assert report.gold_citation_rate == 0.0


async def test_correct_abstention_needs_no_judge() -> None:
    answer_judge, chat = judge()

    report = await evaluate_answers(
        dataset(question("q050", answerable=False)),
        ScriptedAnswerer(abstained()),
        answer_judge,
        SETTINGS,
    )

    [outcome] = report.outcomes
    assert outcome.status_correct
    assert outcome.correctness is None
    assert chat.requests == []
    assert report.abstention_accuracy == 1.0


async def test_abstaining_on_an_answerable_question_counts_against_correctness() -> None:
    answer_judge, chat = judge()

    report = await evaluate_answers(
        dataset(question("q001")), ScriptedAnswerer(abstained()), answer_judge, SETTINGS
    )

    [outcome] = report.outcomes
    assert not outcome.status_correct
    assert report.answer_rate == 0.0
    assert report.correct_rate == 0.0  # over all answerable questions, not only answered ones
    assert report.faithfulness_rate is None  # nothing answered, nothing to check
    assert chat.requests == []


async def test_answering_an_unanswerable_question_is_still_checked_for_grounding() -> None:
    answer_judge, chat = judge(UNGROUNDED)

    report = await evaluate_answers(
        dataset(question("q050", answerable=False)),
        ScriptedAnswerer(answered(OTHER)),
        answer_judge,
        SETTINGS,
    )

    [outcome] = report.outcomes
    assert not outcome.status_correct
    assert outcome.correctness is None  # there is no reference answer
    assert outcome.faithful is False
    assert len(chat.requests) == 1


async def test_failures_are_recorded_and_the_run_continues() -> None:
    answer_judge, _ = judge({"verdict": "nonsense"}, {"verdict": "nonsense"}, GROUNDED)

    report = await evaluate_answers(
        dataset(question("q001"), question("q002")),
        ScriptedAnswerer(ModelTimeoutError("slow"), answered(GOLD)),
        answer_judge,
        SETTINGS,
    )

    first, second = report.outcomes
    assert first.error_category == "model_timeout"
    assert first.status is None
    assert second.judge_error_category == "judge_output_invalid"
    assert second.correctness is None
    assert second.faithful is True  # the grounding call still ran
    assert (report.answer_errors, report.judge_errors) == (1, 1)


async def test_report_records_every_version_and_no_text_by_default() -> None:
    answer_judge, _ = judge(CORRECT, GROUNDED)

    report = await evaluate_answers(
        dataset(question("q001")),
        ScriptedAnswerer(answered(GOLD)),
        answer_judge,
        SETTINGS,
        code_revision="abc1234",
    )

    assert report.dataset_version == "v2"
    assert report.corpus_manifest_sha256 == "a" * 64
    assert report.answer_model == "fake-answer"
    assert report.answer_prompt_version == "answer-v1"
    assert report.judge_model == "fake-judge"
    assert report.judge_prompt_version == "judge-v2"
    assert report.settings == SETTINGS
    assert report.code_revision == "abc1234"
    assert report.answer_input_tokens == 100
    assert report.judge_input_tokens > 0
    assert "14 days [E2]" not in report.model_dump_json()


async def test_workflow_usage_is_recorded_for_comparison_with_direct() -> None:
    answer_judge, _ = judge(CORRECT, GROUNDED)
    workflow_answer = ModeAnswer(
        mode="workflow",
        answer=answered(GOLD),
        sub_questions=("leave days?", "carry-over?"),
        steps=4,
        model_calls=2,
        planner_input_tokens=40,
        planner_output_tokens=12,
        verified=True,
        revisions=1,
        verifier_input_tokens=30,
        verifier_output_tokens=8,
    )

    report = await evaluate_answers(
        dataset(question("q001")), ScriptedAnswerer(workflow_answer), answer_judge, SETTINGS
    )

    [outcome] = report.outcomes
    assert (outcome.mode, outcome.sub_questions, outcome.steps, outcome.model_calls) == (
        "workflow",
        2,
        4,
        2,
    )
    assert (report.model_calls, report.planner_input_tokens, report.planner_output_tokens) == (
        2,
        40,
        12,
    )
    assert (outcome.verified, outcome.revisions) == (True, 1)
    assert (report.revised_answers, report.verifier_input_tokens) == (1, 30)
