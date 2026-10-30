"""Answer-quality evaluation (EVAL-02, ADR-0015): the production answer path, scored.

Each benchmark question is answered through ``AnswerQuestion`` (retrieval, the evidence
gate, generation) and scored on separate metrics:

- deterministic: whether it answered or abstained correctly; whether its citations hit
  the benchmark's gold chunks; whether retrieval surfaced a gold chunk at all;
- judged (``AnswerJudge``): correctness against the reference answer, faithfulness to the
  retrieved evidence, and support by the cited evidence.

An answer error (provider, timeout, invalid output) counts as a failure in every rate it
would enter; a judge error leaves that one verdict unknown and out of its rate. Reports
record every version that produced them and no answer text unless asked.
"""

from collections.abc import Awaitable, Callable, Iterable, Sequence
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict

from enterprise_knowledge.agents.modes import ModeAnswer
from enterprise_knowledge.agents.workflow import WorkflowLimits
from enterprise_knowledge.domain.access import Principal
from enterprise_knowledge.domain.answers import AnswerStatus
from enterprise_knowledge.domain.errors import DomainError
from enterprise_knowledge.evaluation.benchmark import (
    BenchmarkDataset,
    BenchmarkQuestion,
    QuestionType,
)
from enterprise_knowledge.evaluation.judge import (
    JUDGE_PROMPT_VERSION,
    AnswerJudge,
    Correctness,
    CorrectnessJudgment,
    GroundingJudgment,
)
from enterprise_knowledge.generation.prompts import PROMPT_VERSION, evidence_label
from enterprise_knowledge.ingestion.chunking import ChunkingSettings
from enterprise_knowledge.retrieval.search import RetrievalSettings

# AnswerModes bound to one mode: direct RAG or the workflow (ADR-0017).
Answerer = Callable[[Principal, str], Awaitable[ModeAnswer]]


class AnswerRunSettings(BaseModel):
    """How answers were produced, beyond the models: retrieval and the evidence gate."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    retrieval: RetrievalSettings
    k: int
    min_score: float | None
    embedding_model: str
    mode: str = "direct"
    workflow: WorkflowLimits | None = None  # set for workflow runs


class AnswerOutcome(BaseModel):
    """One question. Fields that do not apply, or that a failure left unknown, are None."""

    model_config = ConfigDict(frozen=True)

    question_id: str
    types: list[QuestionType]
    answerable: bool
    status: str | None = None
    status_correct: bool = False
    error_category: str | None = None
    retrieved_gold: bool | None = None
    cites_gold: bool | None = None
    correctness: str | None = None
    faithful: bool | None = None
    citation_supported: bool | None = None
    claims: int | None = None
    unsupported_claims: int | None = None
    judge_error_category: str | None = None
    answer_model: str | None = None
    judge_model: str | None = None
    mode: str | None = None
    sub_questions: int | None = None  # workflow runs only
    steps: int | None = None
    model_calls: int | None = None  # answer-side calls, the planner included
    answer_input_tokens: int = 0
    answer_output_tokens: int = 0
    planner_input_tokens: int = 0
    planner_output_tokens: int = 0
    verified: bool | None = None  # workflow verification (ADR-0019)
    revisions: int = 0
    verifier_input_tokens: int = 0
    verifier_output_tokens: int = 0
    judge_input_tokens: int = 0
    judge_output_tokens: int = 0
    answer: str | None = None  # only with keep_text


class TypeQuality(BaseModel):
    model_config = ConfigDict(frozen=True)

    questions: int
    correct_rate: float | None
    faithfulness_rate: float | None


class AnswerQualityReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    started_at: datetime
    dataset_version: str
    corpus_manifest_sha256: str
    chunking: ChunkingSettings
    settings: AnswerRunSettings
    answer_model: str | None
    answer_prompt_version: str = PROMPT_VERSION
    judge_model: str | None
    judge_prompt_version: str = JUDGE_PROMPT_VERSION
    code_revision: str | None = None
    questions: int
    answerable: int
    unanswerable: int
    answer_errors: int
    judge_errors: int
    answer_rate: float | None  # answerable questions answered
    abstention_accuracy: float | None  # unanswerable questions abstained
    correct_rate: float | None  # answerable questions answered correctly
    correct_or_partial_rate: float | None
    faithfulness_rate: float | None  # answered questions with every claim grounded
    citation_support_rate: float | None  # answered questions with every claim cited
    gold_citation_rate: float | None  # answered answerable questions citing a gold chunk
    retrieval_gold_rate: float | None  # answerable questions with a gold chunk retrieved
    by_type: dict[QuestionType, TypeQuality]
    model_calls: int
    answer_input_tokens: int
    answer_output_tokens: int
    planner_input_tokens: int
    planner_output_tokens: int
    revised_answers: int  # workflow answers regenerated after failed verification
    verification_abstentions: int  # answers withheld because verification failed
    verifier_input_tokens: int
    verifier_output_tokens: int
    judge_input_tokens: int
    judge_output_tokens: int
    outcomes: list[AnswerOutcome]


async def evaluate_answers(
    dataset: BenchmarkDataset,
    answer: Answerer,
    judge: AnswerJudge,
    settings: AnswerRunSettings,
    *,
    code_revision: str | None = None,
    keep_text: bool = False,
) -> AnswerQualityReport:
    started_at = datetime.now(UTC)
    outcomes = [
        await _evaluate(question, answer, judge, keep_text=keep_text)
        for question in dataset.questions
    ]
    answerable = [o for o in outcomes if o.answerable]
    unanswerable = [o for o in outcomes if not o.answerable]
    answered = [o for o in outcomes if o.status == AnswerStatus.ANSWERED.value]
    return AnswerQualityReport(
        started_at=started_at,
        dataset_version=dataset.version,
        corpus_manifest_sha256=dataset.corpus.manifest_sha256,
        chunking=dataset.chunking,
        settings=settings,
        answer_model=next((o.answer_model for o in outcomes if o.answer_model), None),
        judge_model=next((o.judge_model for o in outcomes if o.judge_model), None),
        code_revision=code_revision,
        questions=len(outcomes),
        answerable=len(answerable),
        unanswerable=len(unanswerable),
        answer_errors=sum(1 for o in outcomes if o.error_category is not None),
        judge_errors=sum(1 for o in outcomes if o.judge_error_category is not None),
        answer_rate=_rate(o.status == AnswerStatus.ANSWERED.value for o in answerable),
        abstention_accuracy=_rate(o.status_correct for o in unanswerable),
        correct_rate=_rate(_is(o, {Correctness.CORRECT}) for o in answerable),
        correct_or_partial_rate=_rate(
            _is(o, {Correctness.CORRECT, Correctness.PARTIALLY_CORRECT}) for o in answerable
        ),
        faithfulness_rate=_rate(o.faithful for o in answered),
        citation_support_rate=_rate(o.citation_supported for o in answered),
        gold_citation_rate=_rate(o.cites_gold for o in answered if o.answerable),
        retrieval_gold_rate=_rate(o.retrieved_gold for o in answerable),
        by_type={t: _by_type([o for o in outcomes if t in o.types]) for t in QuestionType},
        model_calls=sum(o.model_calls or 0 for o in outcomes),
        answer_input_tokens=sum(o.answer_input_tokens for o in outcomes),
        answer_output_tokens=sum(o.answer_output_tokens for o in outcomes),
        planner_input_tokens=sum(o.planner_input_tokens for o in outcomes),
        planner_output_tokens=sum(o.planner_output_tokens for o in outcomes),
        revised_answers=sum(1 for o in outcomes if o.revisions),
        verification_abstentions=sum(1 for o in outcomes if o.verified is False),
        verifier_input_tokens=sum(o.verifier_input_tokens for o in outcomes),
        verifier_output_tokens=sum(o.verifier_output_tokens for o in outcomes),
        judge_input_tokens=sum(o.judge_input_tokens for o in outcomes),
        judge_output_tokens=sum(o.judge_output_tokens for o in outcomes),
        outcomes=outcomes,
    )


async def _evaluate(
    question: BenchmarkQuestion, answer: Answerer, judge: AnswerJudge, *, keep_text: bool
) -> AnswerOutcome:
    base = {"question_id": question.id, "types": question.types, "answerable": question.answerable}
    try:
        answered = await answer(question.principal.principal(), question.question)
    except DomainError as exc:  # recorded; the run goes on
        return AnswerOutcome(**base, error_category=exc.category)

    result = answered.answer
    response = result.response
    is_answer = response.status is AnswerStatus.ANSWERED
    gold = {chunk for group in question.groups() for chunk in group}
    labels = {item.chunk_id: evidence_label(i) for i, item in enumerate(result.evidence)}
    cited = [labels[c.chunk_id] for c in response.citations]
    fields: dict[str, object] = {
        "status": response.status.value,
        "status_correct": is_answer == question.answerable,
        "answer_model": result.model_id,
        "answer_input_tokens": result.input_tokens,
        "answer_output_tokens": result.output_tokens,
        "mode": answered.mode,
        "sub_questions": len(answered.sub_questions) if answered.mode == "workflow" else None,
        "steps": answered.steps,
        "model_calls": answered.model_calls,
        "planner_input_tokens": answered.planner_input_tokens,
        "planner_output_tokens": answered.planner_output_tokens,
        "verified": answered.verified,
        "revisions": answered.revisions,
        "verifier_input_tokens": answered.verifier_input_tokens,
        "verifier_output_tokens": answered.verifier_output_tokens,
    }
    if question.answerable:
        fields["retrieved_gold"] = any(item.chunk_id in gold for item in result.evidence)
    if not is_answer:
        return AnswerOutcome(**base, **fields)

    text = response.answer or ""
    if keep_text:
        fields["answer"] = text
    if question.answerable:
        fields["cites_gold"] = any(c.chunk_id in gold for c in response.citations)
    judge_tokens = [0, 0]
    judge_errors: list[str] = []
    if question.reference_answer is not None:
        correctness = await _judged(
            judge.correctness(
                question=question.question, reference=question.reference_answer, answer=text
            ),
            judge_errors,
        )
        if isinstance(correctness, CorrectnessJudgment):
            fields["correctness"] = correctness.verdict.value
            fields["judge_model"] = correctness.model_id
            judge_tokens = [correctness.input_tokens, correctness.output_tokens]
    grounding = await _judged(
        judge.grounding(
            question=question.question, answer=text, evidence=result.evidence, cited=cited
        ),
        judge_errors,
    )
    if isinstance(grounding, GroundingJudgment):
        fields.update(
            faithful=grounding.faithful,
            citation_supported=grounding.citation_supported,
            claims=grounding.claims,
            unsupported_claims=grounding.unsupported_claims,
            judge_model=grounding.model_id,
        )
        judge_tokens = [
            judge_tokens[0] + grounding.input_tokens,
            judge_tokens[1] + grounding.output_tokens,
        ]
    return AnswerOutcome(
        **base,
        **fields,
        judge_error_category=judge_errors[0] if judge_errors else None,
        judge_input_tokens=judge_tokens[0],
        judge_output_tokens=judge_tokens[1],
    )


async def _judged[T](call: Awaitable[T], errors: list[str]) -> T | None:
    """The verdict, or None with its error category appended to ``errors``."""
    try:
        return await call
    except DomainError as exc:
        errors.append(exc.category)
        return None


def _is(outcome: AnswerOutcome, verdicts: set[Correctness]) -> bool | None:
    """Answered with one of ``verdicts``; unknown when the judge failed on an answer."""
    if outcome.status != AnswerStatus.ANSWERED.value:
        return False
    if outcome.correctness is None:
        return None
    return Correctness(outcome.correctness) in verdicts


def _by_type(outcomes: Sequence[AnswerOutcome]) -> TypeQuality:
    answered = [o for o in outcomes if o.status == AnswerStatus.ANSWERED.value]
    return TypeQuality(
        questions=len(outcomes),
        correct_rate=_rate(_is(o, {Correctness.CORRECT}) for o in outcomes if o.answerable),
        faithfulness_rate=_rate(o.faithful for o in answered),
    )


def _rate(values: Iterable[bool | None]) -> float | None:
    applicable = [v for v in values if v is not None]
    return sum(applicable) / len(applicable) if applicable else None
