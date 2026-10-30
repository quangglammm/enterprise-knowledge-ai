"""Choosing direct RAG or the workflow per request, with comparable usage (AGENT-01)."""

import json

from enterprise_knowledge.agents.modes import AnswerModes
from enterprise_knowledge.agents.workflow import AnswerWorkflow, WorkflowLimits
from enterprise_knowledge.generation.answer import AnswerQuestion
from enterprise_knowledge.ingestion.ingest import IngestDocument
from enterprise_knowledge.retrieval.search import SearchKnowledge
from tests.factories import make_policy, make_principal
from tests.fakes.blob_store import InMemoryBlobStore
from tests.fakes.chat_model import ScriptedChatModel
from tests.fakes.document_store import InMemoryDocumentStore
from tests.fakes.embedder import HashEmbedder

ANSWER = json.dumps({"status": "answered", "answer": "14 days [E1].", "citations": ["E1"]})
PLAN = json.dumps({"sub_questions": ["annual leave days?"]})


async def modes(*script: str, documents: bool = True) -> tuple[AnswerModes, ScriptedChatModel]:
    store, embedder = InMemoryDocumentStore(), HashEmbedder()
    if documents:
        ingest = IngestDocument(documents=store, embedder=embedder, blobs=InMemoryBlobStore())
        await ingest(
            data=b"# Leave\n\nEmployees get fourteen days of annual leave.",
            filename="leave.md",
            access=make_policy(),
        )
    search = SearchKnowledge(search=store, embedder=embedder)
    chat = ScriptedChatModel(script)
    return (
        AnswerModes(
            direct=AnswerQuestion(search=search, chat=chat, k=3),
            workflow=AnswerWorkflow(
                search=search, chat=chat, limits=WorkflowLimits(timeout_seconds=1.0)
            ),
        ),
        chat,
    )


async def test_direct_mode_makes_no_agent_calls() -> None:
    answer, chat = await modes(ANSWER)

    result = await answer(make_principal(), "How many days of annual leave?", mode="direct")

    assert result.mode == "direct"
    assert (result.model_calls, result.steps) == (1, 2)  # retrieve, answer
    assert result.sub_questions == ()
    assert len(chat.requests) == 1  # no planner


async def test_direct_abstention_without_evidence_costs_no_model_call() -> None:
    answer, chat = await modes(documents=False)

    result = await answer(make_principal(), "Is there parking?", mode="direct")

    assert (result.model_calls, result.steps) == (0, 1)
    assert chat.requests == []


async def test_workflow_mode_reports_its_plan_and_usage() -> None:
    answer, chat = await modes(PLAN, ANSWER)

    result = await answer(make_principal(), "How many days of annual leave?", mode="workflow")

    assert result.mode == "workflow"
    assert result.sub_questions == ("annual leave days?",)
    assert (result.model_calls, result.steps) == (2, 3)  # plan, retrieve, answer
    assert len(chat.requests) == 2
