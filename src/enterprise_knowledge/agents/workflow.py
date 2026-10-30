"""The bounded answer workflow (AGENT-01, ADR-0017): plan, retrieve per part, answer once.

    PLANNING --> RETRIEVING (once per sub-question) --> ANSWERING --> DONE
                      |
                      +--> ABSTAINED (no usable evidence: the answer model is not called)

Planning is one model call that splits the question into at most ``max_sub_questions``
standalone sub-questions; an unusable plan falls back to the original question. Each
sub-question is searched separately through ``SearchKnowledge`` (tenant and ACL filters in
the query, ADR-0003). The evidence is merged round-robin, so every part keeps its best
chunks, deduplicated and capped, then ``GenerateAnswer`` answers the original question:
the same prompt, parser, citation checks and single repair as direct RAG.

The only tools are search and generation, fixed in code. Limits on steps, model calls and
one wall-clock deadline are enforced; hitting one is a typed failure, never a partial
answer.
"""

import asyncio
import json
import logging
import re
from collections.abc import Sequence
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from enterprise_knowledge.agents.errors import (
    InvalidWorkflowTransitionError,
    WorkflowLimitError,
    WorkflowTimeoutError,
)
from enterprise_knowledge.agents.prompts import PLANNER_PROMPT_VERSION, planner_messages
from enterprise_knowledge.domain.access import Principal
from enterprise_knowledge.domain.answers import AnswerResponse
from enterprise_knowledge.domain.chat import ChatRequest
from enterprise_knowledge.domain.ports import ChatModel
from enterprise_knowledge.domain.retrieval import RetrievedEvidence
from enterprise_knowledge.domain.text import normalize_nfc
from enterprise_knowledge.generation.answer import NO_EVIDENCE_REASON, AnswerResult, GenerateAnswer
from enterprise_knowledge.generation.prompts import PROMPT_VERSION
from enterprise_knowledge.retrieval.search import SearchKnowledge

logger = logging.getLogger(__name__)

_FENCE = re.compile(r"^```(?:json)?\s*(?P<body>.*?)\s*```$", re.DOTALL | re.IGNORECASE)
MAX_SUB_QUESTION_CHARS = 500
_GENERATION_CALLS = 2  # the answer plus at most one repair (ADR-0009)
_PLANNER_MAX_OUTPUT_TOKENS = 300


class WorkflowState(StrEnum):
    PLANNING = "planning"
    RETRIEVING = "retrieving"
    ANSWERING = "answering"
    DONE = "done"
    ABSTAINED = "abstained"


_ALLOWED: dict[WorkflowState, frozenset[WorkflowState]] = {
    WorkflowState.PLANNING: frozenset({WorkflowState.RETRIEVING}),
    WorkflowState.RETRIEVING: frozenset(
        {WorkflowState.RETRIEVING, WorkflowState.ANSWERING, WorkflowState.ABSTAINED}
    ),
    WorkflowState.ANSWERING: frozenset({WorkflowState.DONE}),
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
    max_model_calls: int = Field(default=3, ge=1)
    max_steps: int = Field(default=5, ge=1)
    timeout_seconds: float = Field(default=60.0, gt=0)

    @model_validator(mode="after")
    def _can_complete(self) -> Self:
        if self.max_model_calls < 1 + _GENERATION_CALLS:
            raise ValueError("max_model_calls must cover the plan, the answer and one repair")
        if self.max_steps < self.max_sub_questions + 2:
            raise ValueError("max_steps must cover planning, every retrieval and answering")
        return self


class WorkflowRun:
    """Mutable bookkeeping of one run: current state, steps taken and model calls made."""

    def __init__(self, limits: WorkflowLimits) -> None:
        self._limits = limits
        self.state = WorkflowState.PLANNING
        self.steps = 1  # planning
        self.model_calls = 0

    def advance(self, to: WorkflowState) -> None:
        if to not in _ALLOWED[self.state]:
            raise InvalidWorkflowTransitionError(
                f"cannot move from {self.state.value} to {to.value}"
            )
        if to not in _OUTCOMES:  # reaching an outcome is not a step of work
            if self.steps + 1 > self._limits.max_steps:
                raise WorkflowLimitError(f"workflow would exceed {self._limits.max_steps} steps")
            self.steps += 1
        self.state = to

    def require_model_calls(self, calls: int) -> None:
        """Raise unless ``calls`` more model calls fit in the budget."""
        if self.model_calls + calls > self._limits.max_model_calls:
            raise WorkflowLimitError(
                f"workflow would exceed {self._limits.max_model_calls} model calls"
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
    planner_prompt_version: str = PLANNER_PROMPT_VERSION
    planner_input_tokens: int = 0
    planner_output_tokens: int = 0


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

        if not evidence:
            run.advance(WorkflowState.ABSTAINED)
            answer = AnswerResult(
                response=AnswerResponse.abstain(reason=NO_EVIDENCE_REASON),
                evidence=(),
                prompt_version=PROMPT_VERSION,
            )
        else:
            run.advance(WorkflowState.ANSWERING)
            run.require_model_calls(_GENERATION_CALLS)  # the answer and its possible repair
            answer = await self._generate(question, evidence)
            run.count_model_calls(2 if answer.repaired else 1)
            run.advance(WorkflowState.DONE)

        logger.info(
            "answer workflow finished",
            extra={
                "state": run.state.value,
                "sub_questions": len(sub_questions),
                "plan_fallback": fallback,
                "evidence": len(evidence),
                "steps": run.steps,
                "model_calls": run.model_calls,
            },
        )
        return WorkflowResult(
            answer=answer,
            final_state=run.state,
            sub_questions=tuple(sub_questions),
            plan_fallback=fallback,
            steps=run.steps,
            model_calls=run.model_calls,
            planner_input_tokens=planner_tokens[0],
            planner_output_tokens=planner_tokens[1],
        )

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
    body = content.strip()
    fenced = _FENCE.match(body)
    try:
        plan = _Plan.model_validate_json(fenced.group("body") if fenced else body)
    except (ValidationError, json.JSONDecodeError):
        return []
    cleaned: list[str] = []
    for item in plan.sub_questions:
        text = normalize_nfc(item).strip()[:MAX_SUB_QUESTION_CHARS]
        if text and text not in cleaned:
            cleaned.append(text)
    return cleaned[:limit]
