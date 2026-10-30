"""HTTP behavior of POST /v1/answers, with in-memory adapters and a scripted model."""

import dataclasses
import json

import pytest
from fastapi.testclient import TestClient

from enterprise_knowledge.api.app import create_app
from enterprise_knowledge.domain.errors import (
    ModelAuthenticationError,
    ModelProviderError,
    ModelRateLimitedError,
    ModelResponseError,
    ModelUnavailableError,
)
from enterprise_knowledge.generation.answer import AnswerQuestion
from tests.fakes.chat_model import ScriptedChatModel
from tests.fakes.document_store import InMemoryDocumentStore
from tests.unit.api.test_documents_api import STAFF, make_services, make_settings, upload

QUESTION = {"question": "Nhân viên có bao nhiêu ngày phép năm?"}


def answered(*labels: str) -> str:
    return json.dumps({"status": "answered", "answer": "12 ngày [E1].", "citations": list(labels)})


class Client:
    """An app whose answer use case replays ``script`` as the model's replies."""

    def __init__(self, *script: str | Exception) -> None:
        services, drain = make_services(InMemoryDocumentStore())
        answer = AnswerQuestion(
            search=services.search, chat=ScriptedChatModel(script), timeout_seconds=0.05
        )
        services = dataclasses.replace(services, answer=answer)
        app = create_app(make_settings(), services=services)
        app.state.drain = drain  # upload() runs queued ingestion jobs through it
        self.http = TestClient(app)


def test_answer_returns_text_and_citations_with_source_metadata() -> None:
    client = Client(answered("E1"))
    with client.http as http:
        doc_id = upload(http, STAFF).body["document"]["id"]

        response = http.post("/v1/answers", headers=STAFF, json=QUESTION)

    assert response.status_code == 200
    body = response.json()
    assert (body["status"], body["answer"], body["abstention_reason"]) == (
        "answered",
        "12 ngày [E1].",
        None,
    )
    [citation] = body["citations"]
    assert citation["label"] == "E1"
    assert citation["document_id"] == doc_id
    assert citation["document_version"] == 1
    assert citation["title"] == "Quy chế nghỉ phép"
    assert citation["page"] == 1
    assert (body["model_id"], body["prompt_version"]) == ("fake-chat", "answer-v1")


def test_no_evidence_is_a_200_abstention() -> None:
    with Client().http as http:
        response = http.post("/v1/answers", headers=STAFF, json=QUESTION)

    assert response.status_code == 200
    body = response.json()
    assert (body["status"], body["answer"], body["citations"]) == (
        "insufficient_evidence",
        None,
        [],
    )
    assert body["abstention_reason"] == "no_relevant_evidence"


@pytest.mark.parametrize(
    ("script", "status", "category"),
    [
        (("prose", "more prose"), 502, "invalid_model_output"),
        ((answered("E9"), answered("E9")), 502, "unknown_citation"),
        ((TimeoutError("slow"),), 504, "model_timeout"),
    ],
    ids=["invalid-output", "unknown-citation", "timeout"],
)
def test_model_failures_map_to_gateway_errors(
    script: tuple[str | Exception, ...], status: int, category: str
) -> None:
    with Client(*script).http as http:
        upload(http, STAFF)

        response = http.post("/v1/answers", headers=STAFF, json=QUESTION)

    assert response.status_code == status
    assert response.json()["error"]["category"] == category


def test_question_without_words_is_422() -> None:
    with Client().http as http:
        response = http.post("/v1/answers", headers=STAFF, json={"question": "?!"})

    assert response.status_code == 422
    assert response.json()["error"]["category"] == "invalid_query"


def test_answers_return_503_when_no_model_is_configured() -> None:
    services, _ = make_services(InMemoryDocumentStore())
    with TestClient(create_app(make_settings(), services=services)) as http:
        response = http.post("/v1/answers", headers=STAFF, json=QUESTION)

    assert response.status_code == 503
    assert response.json()["error"]["category"] == "service_unavailable"


@pytest.mark.parametrize(
    ("error", "status", "category"),
    [
        (ModelRateLimitedError("POST /chat/completions returned 429"), 503, "model_rate_limited"),
        (ModelUnavailableError("POST /chat/completions returned 503"), 502, "model_unavailable"),
        (ModelAuthenticationError("POST /chat/completions returned 401"), 502, "model_auth_failed"),
        (ModelResponseError("completion has no choices"), 502, "model_invalid_response"),
    ],
    ids=["rate-limited", "unavailable", "auth", "bad-response"],
)
def test_provider_failures_map_to_upstream_errors(
    error: ModelProviderError, status: int, category: str
) -> None:
    with Client(error).http as http:
        upload(http, STAFF)

        response = http.post("/v1/answers", headers=STAFF, json=QUESTION)

    assert response.status_code == status
    assert response.json()["error"]["category"] == category
