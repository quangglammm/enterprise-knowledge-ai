"""AGENT-01: the bounded plan -> retrieve -> answer workflow and its state machine."""

import json

import pytest
from pydantic import ValidationError

from enterprise_knowledge.agents.errors import (
    InvalidWorkflowTransitionError,
    WorkflowLimitError,
    WorkflowTimeoutError,
)
from enterprise_knowledge.agents.prompts import PLANNER_PROMPT_VERSION
from enterprise_knowledge.agents.workflow import (
    AnswerWorkflow,
    WorkflowLimits,
    WorkflowRun,
    WorkflowState,
    merge_evidence,
)
from enterprise_knowledge.domain.access import AccessPolicy, Principal
from enterprise_knowledge.domain.answers import AnswerStatus
from enterprise_knowledge.domain.errors import AccessViolationError
from enterprise_knowledge.domain.ports import Vector
from enterprise_knowledge.domain.retrieval import RetrievedEvidence
from enterprise_knowledge.ingestion.ingest import IngestDocument
from enterprise_knowledge.retrieval.search import SearchKnowledge
from tests.factories import TENANT, make_evidence, make_policy, make_principal
from tests.fakes.blob_store import InMemoryBlobStore
from tests.fakes.chat_model import ScriptedChatModel
from tests.fakes.document_store import InMemoryDocumentStore
from tests.fakes.embedder import HashEmbedder

LEAVE = "# Leave policy\n\nEmployees receive fourteen days of annual leave per year."
VPN = "# VPN guide\n\nRestart the network adapter when the VPN client shows error 809."
SALARY = "# Salary bands\n\nSalary bands for engineers are reviewed every April."
QUESTION = "How many days of annual leave do I get, and what fixes VPN error 809?"


def plan(*sub_questions: str) -> str:
    return json.dumps({"sub_questions": list(sub_questions)})


def answered(*labels: str) -> str:
    return json.dumps(
        {"status": "answered", "answer": "14 days; restart the adapter.", "citations": list(labels)}
    )


class Harness:
    def __init__(self, *script: str | Exception, limits: WorkflowLimits | None = None) -> None:
        self.store = InMemoryDocumentStore()
        self.embedder = HashEmbedder()
        self.chat = ScriptedChatModel(script)
        self._ingest = IngestDocument(
            documents=self.store, embedder=self.embedder, blobs=InMemoryBlobStore()
        )
        self.workflow = AnswerWorkflow(
            search=SearchKnowledge(search=self.store, embedder=self.embedder),
            chat=self.chat,
            limits=limits or WorkflowLimits(k_per_question=2, timeout_seconds=1.0),
        )

    async def add(self, text: str, access: AccessPolicy | None = None) -> None:
        await self._ingest(data=text.encode(), filename="doc.md", access=access or make_policy())

    def prompt(self, call: int) -> str:
        return self.chat.requests[call].messages[1].content


async def indexed(*script: str | Exception, limits: WorkflowLimits | None = None) -> Harness:
    harness = Harness(*script, limits=limits)
    for text in (LEAVE, VPN):
        await harness.add(text)
    return harness


# --- the workflow -----------------------------------------------------------------------


async def test_complex_question_is_planned_retrieved_per_part_and_answered_once() -> None:
    h = await indexed(
        plan("How many days of annual leave do I get?", "What fixes VPN error 809?"),
        answered("E1", "E2"),
    )

    result = await h.workflow(make_principal(), QUESTION)

    assert result.final_state is WorkflowState.DONE
    assert result.sub_questions == (
        "How many days of annual leave do I get?",
        "What fixes VPN error 809?",
    )
    assert result.model_calls == 2  # one plan, one answer
    assert result.steps == 4  # plan, two retrievals, answer
    assert result.answer.response.status is AnswerStatus.ANSWERED
    evidence_text = " ".join(e.text for e in result.answer.evidence)
    assert "fourteen days" in evidence_text
    assert "error 809" in evidence_text
    assert result.planner_prompt_version == PLANNER_PROMPT_VERSION


async def test_answer_prompt_gets_the_original_question() -> None:
    h = await indexed(plan("leave days?", "vpn 809?"), answered("E1"))

    await h.workflow(make_principal(), QUESTION)

    assert QUESTION.replace("?", "") in h.prompt(1)


async def test_planner_sees_only_the_question_never_documents() -> None:
    h = await indexed(plan(QUESTION), answered("E1"))

    await h.workflow(make_principal(), QUESTION)

    system, user = h.chat.requests[0].messages
    assert "<evidence" not in user.content
    assert "fourteen days" not in user.content + system.content


@pytest.mark.parametrize(
    "bad_plan",
    ["not json", json.dumps({"sub_questions": []}), json.dumps({"sub_questions": [" "]})],
    ids=["invalid-json", "empty", "blank"],
)
async def test_unusable_plan_falls_back_to_the_original_question(bad_plan: str) -> None:
    h = await indexed(bad_plan, answered("E1"))

    result = await h.workflow(make_principal(), QUESTION)

    assert result.plan_fallback
    assert result.sub_questions == (QUESTION,)
    assert result.final_state is WorkflowState.DONE
    assert result.model_calls == 2


async def test_plan_is_capped_and_deduplicated() -> None:
    limits = WorkflowLimits(max_sub_questions=2, k_per_question=2, timeout_seconds=1.0)
    h = await indexed(
        plan("a leave?", "a leave?", "vpn?", "salary?"), answered("E1"), limits=limits
    )

    result = await h.workflow(make_principal(), QUESTION)

    assert result.sub_questions == ("a leave?", "vpn?")


async def test_no_evidence_abstains_without_an_answer_call() -> None:
    h = Harness(plan("parking?"))  # nothing indexed

    result = await h.workflow(make_principal(), "Is there parking support?")

    assert result.final_state is WorkflowState.ABSTAINED
    assert result.answer.response.status is AnswerStatus.INSUFFICIENT_EVIDENCE
    assert result.model_calls == 1
    assert len(h.chat.requests) == 1


async def test_restricted_chunks_never_reach_the_evidence() -> None:
    h = await indexed(plan("salary bands?", "leave days?"), answered("E1"))
    await h.add(SALARY, access=make_policy(TENANT, "hr"))

    result = await h.workflow(make_principal(TENANT, "all-staff"), "Salary bands and leave days?")

    assert all("Salary bands" not in e.text for e in result.answer.evidence)


class _LeakySearch:
    """An adapter bug: returns an HR-only chunk to anyone."""

    async def search(
        self, principal: Principal, query_vector: Vector, *, k: int, embedding_model: str
    ) -> list[RetrievedEvidence]:
        return [make_evidence("leak", access=make_policy(TENANT, "hr"))]

    async def search_lexical(
        self,
        principal: Principal,
        query_text: str,
        query_vector: Vector,
        *,
        k: int,
        embedding_model: str,
    ) -> list[RetrievedEvidence]:
        return []


async def test_a_leaking_search_fails_the_workflow() -> None:
    workflow = AnswerWorkflow(
        search=SearchKnowledge(search=_LeakySearch(), embedder=HashEmbedder()),
        chat=ScriptedChatModel([plan("salary?")]),
        limits=WorkflowLimits(timeout_seconds=1.0),
    )

    with pytest.raises(AccessViolationError):
        await workflow(make_principal(TENANT, "all-staff"), "salary?")


async def test_deadline_ends_in_a_typed_failure_not_a_partial_answer() -> None:
    h = await indexed(plan("leave?"), answered("E1"), limits=WorkflowLimits(timeout_seconds=0.05))
    h.chat.delay_seconds = 0.2

    with pytest.raises(WorkflowTimeoutError) as caught:
        await h.workflow(make_principal(), QUESTION)

    assert caught.value.category == "workflow_timeout"


# --- the state machine and its limits ----------------------------------------------------


def test_allowed_transitions_follow_the_documented_workflow() -> None:
    run = WorkflowRun(WorkflowLimits())

    run.advance(WorkflowState.RETRIEVING)
    run.advance(WorkflowState.RETRIEVING)
    run.advance(WorkflowState.ANSWERING)
    run.advance(WorkflowState.DONE)

    assert run.state is WorkflowState.DONE
    assert run.steps == 4


@pytest.mark.parametrize(
    ("path", "bad"),
    [
        ([], WorkflowState.ANSWERING),  # cannot answer before retrieving
        ([WorkflowState.RETRIEVING, WorkflowState.ANSWERING], WorkflowState.PLANNING),
        (
            [WorkflowState.RETRIEVING, WorkflowState.ANSWERING, WorkflowState.DONE],
            WorkflowState.RETRIEVING,
        ),
    ],
    ids=["skip-retrieval", "back-to-planning", "after-done"],
)
def test_invalid_transitions_raise(path: list[WorkflowState], bad: WorkflowState) -> None:
    run = WorkflowRun(WorkflowLimits())
    for state in path:
        run.advance(state)

    with pytest.raises(InvalidWorkflowTransitionError):
        run.advance(bad)


def test_step_and_model_call_limits_are_enforced() -> None:
    limits = WorkflowLimits(max_sub_questions=1, max_steps=3)
    run = WorkflowRun(limits)  # planning is step 1
    run.advance(WorkflowState.RETRIEVING)
    run.advance(WorkflowState.RETRIEVING)  # one retrieval more than the plan allows

    with pytest.raises(WorkflowLimitError, match="steps"):
        run.advance(WorkflowState.ANSWERING)

    calls = WorkflowRun(WorkflowLimits())
    calls.count_model_calls(3)
    with pytest.raises(WorkflowLimitError, match="model calls"):
        calls.count_model_calls(1)


@pytest.mark.parametrize(
    "values",
    [
        {"max_model_calls": 2},  # plan + answer + repair needs 3
        {"max_sub_questions": 3, "max_steps": 4},  # plan + 3 retrievals + answer needs 5
        {"max_sub_questions": 0},
        {"timeout_seconds": 0},
    ],
    ids=["too-few-calls", "too-few-steps", "no-sub-questions", "no-time"],
)
def test_limits_that_cannot_complete_the_workflow_are_rejected(values: dict[str, float]) -> None:
    with pytest.raises(ValidationError):
        WorkflowLimits.model_validate(values)


def test_evidence_is_merged_round_robin_deduplicated_and_capped() -> None:
    a = [make_evidence("a1"), make_evidence("shared"), make_evidence("a3")]
    b = [make_evidence("shared"), make_evidence("b2")]

    merged = merge_evidence([a, b], max_items=4)

    assert [e.chunk_id for e in merged] == ["a1", "shared", "b2", "a3"][:4]


async def test_a_repaired_answer_counts_two_model_calls() -> None:
    h = await indexed(plan("leave days?"), "not json", answered("E1"))

    result = await h.workflow(make_principal(), QUESTION)

    assert result.answer.repaired
    assert result.model_calls == 3  # plan, answer, repair: exactly the budget
