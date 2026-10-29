"""FptChatModel: ChatRequest to /chat/completions and back to a ChatResponse."""

from typing import Any

import pytest

from enterprise_knowledge.domain.chat import ChatMessage, ChatRequest
from enterprise_knowledge.domain.errors import ModelResponseError
from enterprise_knowledge.domain.ports import ChatModel
from enterprise_knowledge.infrastructure.fpt.chat import FptChatModel
from tests.unit.infrastructure.fpt.conftest import Harness, ok

MODEL = "Llama-3.3-70B-Instruct"
REQUEST = ChatRequest(
    messages=(
        ChatMessage(role="system", content="rules"),
        ChatMessage(role="user", content="question"),
    ),
    max_output_tokens=512,
    temperature=0.0,
    json_mode=True,
)


def completion(content: Any = '{"status": "answered"}', **extra: Any) -> dict[str, Any]:
    return {
        "model": MODEL,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": content}}],
        "usage": {"prompt_tokens": 120, "completion_tokens": 30, "total_tokens": 150},
        **extra,
    }


def chat_model(harness: Harness, *, json_mode: bool = False) -> FptChatModel:
    ticks = iter([10.0, 10.25])
    return FptChatModel(harness.client, model=MODEL, json_mode=json_mode, clock=lambda: next(ticks))


async def test_request_is_an_openai_style_chat_completion() -> None:
    harness = Harness(ok(completion()))
    model: ChatModel = chat_model(harness)

    await model.complete(REQUEST)

    assert harness.transport.requests[0].url.path == "/chat/completions"
    assert harness.transport.body() == {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": "rules"},
            {"role": "user", "content": "question"},
        ],
        "temperature": 0.0,
        "max_tokens": 512,
        "stream": False,
    }


@pytest.mark.parametrize("enabled", [True, False])
async def test_json_mode_is_requested_only_when_enabled(enabled: bool) -> None:
    harness = Harness(ok(completion()))

    await chat_model(harness, json_mode=enabled).complete(REQUEST)

    sent = harness.transport.body().get("response_format")
    assert sent == ({"type": "json_object"} if enabled else None)


async def test_response_carries_content_usage_model_and_latency() -> None:
    harness = Harness(ok(completion()))

    response = await chat_model(harness).complete(REQUEST)

    assert response.content == '{"status": "answered"}'
    assert (response.model_id, response.input_tokens, response.output_tokens) == (MODEL, 120, 30)
    assert response.latency_ms == 250.0


async def test_missing_usage_is_recorded_as_zero_tokens() -> None:
    body = completion()
    del body["usage"]
    harness = Harness(ok(body))

    response = await chat_model(harness).complete(REQUEST)

    assert (response.input_tokens, response.output_tokens) == (0, 0)


@pytest.mark.parametrize(
    "body",
    [
        {"choices": []},
        {"model": MODEL},
        completion(content=None),
        completion(content="   "),
        completion(content=["parts"]),
    ],
    ids=["no-choices", "no-choices-key", "null-content", "blank-content", "non-string-content"],
)
async def test_unusable_completion_is_a_response_error(body: dict[str, Any]) -> None:
    harness = Harness(ok(body))

    with pytest.raises(ModelResponseError):
        await chat_model(harness).complete(REQUEST)


async def test_model_id_falls_back_to_the_configured_model() -> None:
    body = completion()
    del body["model"]
    harness = Harness(ok(body))

    response = await chat_model(harness).complete(REQUEST)

    assert response.model_id == MODEL
