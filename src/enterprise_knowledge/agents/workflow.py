"""The bounded answer workflow (AGENT-01/02, ADR-0017, ADR-0019).

    PLANNING --> RETRIEVING (once per sub-question) --> ANSWERING --> VERIFYING --> DONE
                      |                                   |   ^           |
                      |                                   |   +-----------+ one revision
                      +--> ABSTAINED (no usable evidence) +--> ABSTAINED <+ still unsupported,
                                                         (model abstained)  or unverifiable

Planning is one model call that splits the question into at most ``max_sub_questions``
standalone sub-questions; an unusable plan falls back to the original question. Each
sub-question is searched separately through ``SearchKnowledge`` (tenant and ACL filters in
the query, ADR-0003). The evidence is merged round-robin, so every part keeps its best
chunks, deduplicated and capped, then ``GenerateAnswer`` answers the original question:
the same prompt, parser, citation checks and single repair as direct RAG.

Every answer is then verified claim by claim against its evidence (``AnswerVerifier``).
Unsupported claims get one revision (a fixed instruction, not the claims echoed back) and a
second verification; still unsupported, or unreadable verifier output, ends in abstention.
An unverified answer is never returned.

The only tools are search, generation and verification, fixed in code. Limits on steps,
model calls and one wall-clock deadline are enforced; hitting one is a typed failure,
never a partial answer.
"""

import asyncio
import json
import logging
from collections.abc import Sequence
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from enterprise_knowledge.agents.errors import (
    InvalidWorkflowTransitionError,
    VerifierOutputError,
    WorkflowLimitError,
    WorkflowTimeoutError,
)
from enterprise_knowledge.agents.prompts import PLANNER_PROMPT_VERSION, planner_messages
from enterprise_knowledge.agents.verify import VERIFIER_PROMPT_VERSION, AnswerVerifier
from enterprise_knowledge.domain.access import Principal
from enterprise_knowledge.domain.answers import AnswerResponse, AnswerStatus
from enterprise_knowledge.domain.chat import ChatRequest
from enterprise_knowledge.domain.ports import ChatModel
from enterprise_knowledge.domain.retrieval import RetrievedEvidence
from enterprise_knowledge.domain.text import normalize_nfc
from enterprise_knowledge.generation.answer import NO_EVIDENCE_REASON, AnswerResult, GenerateAnswer
from enterprise_knowledge.generation.output import clean_json_reply
from enterprise_knowledge.generation.prompts import PROMPT_VERSION
from enterprise_knowledge.retrieval.search import SearchKnowledge

logger = logging.getLogger(__name__)

MAX_SUB_QUESTION_CHARS = 500
_GENERATION_CALLS = 2  # the answer plus at most one repair (ADR-0009)
_ANSWER_ROUND_CALLS = _GENERATION_CALLS + 1  # ... and its verification
_PLANNER_MAX_OUTPUT_TOKENS = 300
UNSUPPORTED_CLAIMS = "unsupported_claims"
VERIFICATION_UNAVAILABLE = "verification_unavailable"


class WorkflowState(StrEnum):
    PLANNING = "planning"
    RETRIEVING = "retrieving"
    ANSWERING = "answering"
    VERIFYING = "verifying"
    DONE = "done"
    ABSTAINED = "abstained"


_ALLOWED: dict[WorkflowState, frozenset[WorkflowState]] = {
    WorkflowState.PLANNING: frozenset({WorkflowState.RETRIEVING}),
    WorkflowState.RETRIEVING: frozenset(
        {WorkflowState.RETRIEVING, WorkflowState.ANSWERING, WorkflowState.ABSTAINED}
    ),
    # A model abstention ends the run; any answer must be verified before it is DONE.
    WorkflowState.ANSWERING: frozenset({WorkflowState.VERIFYING, WorkflowState.ABSTAINED}),
    WorkflowState.VERIFYING: frozenset(
        {WorkflowState.DONE, WorkflowState.ANSWERING, WorkflowState.ABSTAINED}
    ),
    WorkflowState.DONE: frozenset(),
    WorkflowState.ABSTAINED: frozenset(),
}
_OUTCOMES = frozenset({WorkflowState.DONE, WorkflowState.ABSTAINED})


class WorkflowLimits(BaseModel):
    """Bounds of one run. Validated so a run that obeys them can always finish."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    max_sub_questions: int = Field(default=3, ge=1, le=5)
    k_per_question: int = Field(default=5, ge=1, le=20)
    max_evidence: int = Field(default=8, ge=1, le=20)
    max_revisions: int = Field(default=1, ge=0, le=1)  # answers again after failed checks
    # Derived from the shape above when not given; given values must still allow a run.
    max_model_calls: int | None = Field(default=None, ge=1)
    max_steps: int | None = Field(default=None, ge=1)
    timeout_seconds: float = Field(default=60.0, gt=0)

    @property
    def _rounds(self) -> int:
        return 1 + self.max_revisions

    @property
    def model_call_budget(self) -> int:
        """Plan, then per round: the answer, its repair and its verification."""
        needed = 1 + _ANSWER_ROUND_CALLS * self._rounds
        return self.max_model_calls if self.max_model_calls is not None else needed

    @property
    def step_budget(self) -> int:
        """Planning, one retrieval per sub-question, then answering and verifying per round."""
        needed = 1 + self.max_sub_questions + 2 * self._rounds
        return self.max_steps if self.max_steps is not None else needed

    @model_validator(mode="after")
    def _can_complete(self) -> Self:
        if self.model_call_budget < 1 + _ANSWER_ROUND_CALLS * self._rounds:
            raise ValueError("max_model_calls must cover the plan and every answer round")
        if self.step_budget < 1 + self.max_sub_questions + 2 * self._rounds:
            raise ValueError("max_steps must cover planning, every retrieval and every round")
        return self


class WorkflowRun:
    """Mutable bookkeeping of one run: current state, steps taken and model calls made."""

    def __init__(self, limits: WorkflowLimits) -> None:
        self._limits = limits
        self.state = WorkflowState.PLANNING
        self.steps = 1  # planning
        self.model_calls = 0
        self.revisions = 0

    def advance(self, to: WorkflowState) -> None:
        if to not in _ALLOWED[self.state]:
            raise InvalidWorkflowTransitionError(
                f"cannot move from {self.state.value} to {to.value}"
            )
        revising = self.state is WorkflowState.VERIFYING and to is WorkflowState.ANSWERING
        if revising and self.revisions >= self._limits.max_revisions:
            raise WorkflowLimitError(
                f"workflow would exceed {self._limits.max_revisions} revision(s)"
            )
        if to not in _OUTCOMES:  # reaching an outcome is not a step of work
            if self.steps + 1 > self._limits.step_budget:
                raise WorkflowLimitError(f"workflow would exceed {self._limits.step_budget} steps")
            self.steps += 1
        if revising:
            self.revisions += 1
        self.state = to

    def require_model_calls(self, calls: int) -> None:
        """Raise unless ``calls`` more model calls fit in the budget."""
        if self.model_calls + calls > self._limits.model_call_budget:
            raise WorkflowLimitError(
                f"workflow would exceed {self._limits.model_call_budget} model calls"
            )

    def count_model_calls(self, calls: int) -> None:
        self.require_model_calls(calls)
        self.model_calls += calls


class WorkflowResult(BaseModel):
    """The answer plus how the workflow reached it. ``sub_questions`` derive from the
    user's own question (the planner never sees documents), so they are safe to show."""

    model_config = ConfigDict(frozen=True)

    answer: AnswerResult
    final_state: WorkflowState
    sub_questions: tuple[str, ...]
    plan_fallback: bool
    steps: int
    model_calls: int
    # True: the final answer passed verification. False: it did not, and the run abstained.
    # None: nothing to verify (no evidence, or the model itself abstained).
    verified: bool | None = None
    revisions: int = 0
    planner_prompt_version: str = PLANNER_PROMPT_VERSION
    verifier_prompt_version: str = VERIFIER_PROMPT_VERSION
    planner_input_tokens: int = 0
    planner_output_tokens: int = 0
    verifier_input_tokens: int = 0
    verifier_output_tokens: int = 0


class _Plan(BaseModel):
    sub_questions: list[str]


class AnswerWorkflow:
    def __init__(
        self,
        *,
        search: SearchKnowledge,
        chat: ChatModel,
        limits: WorkflowLimits | None = None,
        min_score: float | None = None,
    ) -> None:
        self._search = search
        self._chat = chat
        self._limits = limits or WorkflowLimits()
        self._min_score = min_score
        self._generate = GenerateAnswer(chat=chat, timeout_seconds=self._limits.timeout_seconds)
        self._verifier = AnswerVerifier(chat=chat)

    async def __call__(self, principal: Principal, question: str) -> WorkflowResult:
        text = normalize_nfc(question).strip()
        run = WorkflowRun(self._limits)
        try:
            async with asyncio.timeout(self._limits.timeout_seconds):
                return await self._run(run, principal, text)
        except TimeoutError as exc:
            logger.warning(
                "answer workflow timed out",
                extra={
                    "state": run.state.value,
                    "steps": run.steps,
                    "model_calls": run.model_calls,
                },
            )
            raise WorkflowTimeoutError(
                f"workflow did not finish within {self._limits.timeout_seconds}s"
            ) from exc

    async def _run(self, run: WorkflowRun, principal: Principal, question: str) -> WorkflowResult:
        sub_questions, fallback, planner_tokens = await self._plan(run, question)

        rankings: list[list[RetrievedEvidence]] = []
        for sub_question in sub_questions:
            run.advance(WorkflowState.RETRIEVING)
            rankings.append(
                await self._search(principal, sub_question, k=self._limits.k_per_question)
            )
        evidence = [
            item
            for item in merge_evidence(rankings, max_items=self._limits.max_evidence)
            if self._min_score is None or item.score >= self._min_score
        ]

        verified: bool | None = None
        verifier_tokens = (0, 0)
        if not evidence:
            run.advance(WorkflowState.ABSTAINED)
            answer = AnswerResult(
                response=AnswerResponse.abstain(reason=NO_EVIDENCE_REASON),
                evidence=(),
                prompt_version=PROMPT_VERSION,
            )
        else:
            run.advance(WorkflowState.ANSWERING)
            answer = await self._answer(run, question, evidence, revise=False)
            while True:
                if answer.response.status is AnswerStatus.INSUFFICIENT_EVIDENCE:
                    run.advance(WorkflowState.ABSTAINED)  # nothing claimed, nothing to verify
                    break
                run.advance(WorkflowState.VERIFYING)
                run.count_model_calls(1)
                try:
                    check = await self._verifier.verify(
                        question=question, answer=answer.response.answer or "", evidence=evidence
                    )
                except VerifierOutputError:
                    logger.warning("verifier output unusable; abstaining")
                    verified = False
                    answer = _abstained(answer, VERIFICATION_UNAVAILABLE)
                    run.advance(WorkflowState.ABSTAINED)
                    break
                verifier_tokens = (
                    verifier_tokens[0] + check.input_tokens,
                    verifier_tokens[1] + check.output_tokens,
                )
                verified = check.supported
                if check.supported:
                    run.advance(WorkflowState.DONE)
                    break
                logger.info(
                    "answer failed verification",
                    extra={"claims": check.claims, "unsupported": check.unsupported_claims},
                )
                if run.revisions < self._limits.max_revisions:
                    run.advance(WorkflowState.ANSWERING)
                    answer = await self._answer(run, question, evidence, revise=True)
                    continue
                answer = _abstained(answer, UNSUPPORTED_CLAIMS)
                run.advance(WorkflowState.ABSTAINED)
                break

        logger.info(
            "answer workflow finished",
            extra={
                "state": run.state.value,
                "sub_questions": len(sub_questions),
                "plan_fallback": fallback,
                "evidence": len(evidence),
                "steps": run.steps,
                "model_calls": run.model_calls,
                "verified": verified,
                "revisions": run.revisions,
            },
        )
        return WorkflowResult(
            answer=answer,
            final_state=run.state,
            sub_questions=tuple(sub_questions),
            plan_fallback=fallback,
            steps=run.steps,
            model_calls=run.model_calls,
            verified=verified,
            revisions=run.revisions,
            planner_input_tokens=planner_tokens[0],
            planner_output_tokens=planner_tokens[1],
            verifier_input_tokens=verifier_tokens[0],
            verifier_output_tokens=verifier_tokens[1],
        )

    async def _answer(
        self,
        run: WorkflowRun,
        question: str,
        evidence: Sequence[RetrievedEvidence],
        *,
        revise: bool,
    ) -> AnswerResult:
        run.require_model_calls(_GENERATION_CALLS)  # the answer and its possible repair
        answer = await self._generate(question, evidence, revise=revise)
        run.count_model_calls(2 if answer.repaired else 1)
        return answer

    async def _plan(
        self, run: WorkflowRun, question: str
    ) -> tuple[list[str], bool, tuple[int, int]]:
        """Sub-questions, whether the plan fell back to the question itself, and tokens."""
        run.count_model_calls(1)
        reply = await self._chat.complete(
            ChatRequest(
                messages=planner_messages(
                    question, max_sub_questions=self._limits.max_sub_questions
                ),
                max_output_tokens=_PLANNER_MAX_OUTPUT_TOKENS,
                temperature=0.0,
                json_mode=True,
            )
        )
        tokens = (reply.input_tokens, reply.output_tokens)
        sub_questions = _parse_plan(reply.content, limit=self._limits.max_sub_questions)
        if not sub_questions:
            logger.warning("planner output unusable; using the question as its only part")
            return [question], True, tokens
        return sub_questions, False, tokens


def _abstained(answer: AnswerResult, reason: str) -> AnswerResult:
    """The run's abstention, keeping what produced it (evidence, model, usage)."""
    return answer.model_copy(update={"response": AnswerResponse.abstain(reason=reason)})


def merge_evidence(
    rankings: Sequence[Sequence[RetrievedEvidence]], *, max_items: int
) -> list[RetrievedEvidence]:
    """Round-robin over the rankings by rank, skipping chunks already taken, up to max."""
    merged: dict[str, RetrievedEvidence] = {}
    depth = max((len(r) for r in rankings), default=0)
    for rank in range(depth):
        for ranking in rankings:
            if rank < len(ranking) and ranking[rank].chunk_id not in merged:
                merged[ranking[rank].chunk_id] = ranking[rank]
                if len(merged) == max_items:
                    return list(merged.values())
    return list(merged.values())


def _parse_plan(content: str, *, limit: int) -> list[str]:
    """Usable sub-questions in order, deduplicated and capped; empty if the reply is unusable."""
    try:
        plan = _Plan.model_validate_json(clean_json_reply(content))
    except (ValidationError, json.JSONDecodeError):
        return []
    cleaned: list[str] = []
    for item in plan.sub_questions:
        text = normalize_nfc(item).strip()[:MAX_SUB_QUESTION_CHARS]
        if text and text not in cleaned:
            cleaned.append(text)
    return cleaned[:limit]
