"""Answer a question in a chosen mode, reporting comparable usage (AGENT-01, ADR-0017).

``direct`` is standard RAG (``AnswerQuestion``): one search, at most one answer call plus
its repair. ``workflow`` is the bounded plan -> retrieve -> answer workflow. The caller
picks the mode; there is no automatic router until the evaluation shows when the workflow
is worth its extra call.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict

from enterprise_knowledge.agents.workflow import AnswerWorkflow
from enterprise_knowledge.domain.access import Principal
from enterprise_knowledge.generation.answer import AnswerQuestion, AnswerResult

AnswerMode = Literal["direct", "workflow"]


class ModeAnswer(BaseModel):
    model_config = ConfigDict(frozen=True)

    mode: AnswerMode
    answer: AnswerResult
    sub_questions: tuple[str, ...] = ()
    steps: int
    model_calls: int
    # The workflow's planning call, on top of the answer's own tokens; 0 in direct mode.
    planner_input_tokens: int = 0
    planner_output_tokens: int = 0


class AnswerModes:
    def __init__(self, *, direct: AnswerQuestion, workflow: AnswerWorkflow) -> None:
        self._direct = direct
        self._workflow = workflow

    async def __call__(
        self, principal: Principal, question: str, *, mode: AnswerMode
    ) -> ModeAnswer:
        if mode == "workflow":
            run = await self._workflow(principal, question)
            return ModeAnswer(
                mode=mode,
                answer=run.answer,
                sub_questions=run.sub_questions,
                steps=run.steps,
                model_calls=run.model_calls,
                planner_input_tokens=run.planner_input_tokens,
                planner_output_tokens=run.planner_output_tokens,
            )
        answer = await self._direct(principal, question)
        generated = bool(answer.evidence)  # AnswerQuestion calls the model only with evidence
        return ModeAnswer(
            mode=mode,
            answer=answer,
            steps=2 if generated else 1,
            model_calls=(2 if answer.repaired else 1) if generated else 0,
        )
