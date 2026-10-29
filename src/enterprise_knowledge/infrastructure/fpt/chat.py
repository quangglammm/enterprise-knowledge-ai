"""ChatModel over FPT's OpenAI-style /chat/completions (ADR-0004, ADR-0010)."""

import time
from collections.abc import Callable
from typing import Any

from enterprise_knowledge.domain.chat import ChatRequest, ChatResponse
from enterprise_knowledge.domain.errors import ModelResponseError
from enterprise_knowledge.infrastructure.fpt.client import FptClient

_PATH = "/chat/completions"


class FptChatModel:
    def __init__(
        self,
        client: FptClient,
        *,
        model: str,
        json_mode: bool,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        self._client = client
        self._model = model
        # FPT does not document response_format; it is sent only once the model trial
        # confirms support (EKA_LLM_JSON_MODE). The prompt asks for JSON either way.
        self._json_mode = json_mode
        self._clock = clock

    @property
    def model_id(self) -> str:
        return self._model

    async def complete(self, request: ChatRequest) -> ChatResponse:
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": [{"role": m.role, "content": m.content} for m in request.messages],
            "temperature": request.temperature,
            "max_tokens": request.max_output_tokens,
            "stream": False,
        }
        if request.json_mode and self._json_mode:
            payload["response_format"] = {"type": "json_object"}

        started = self._clock()
        body = await self._client.post_json(_PATH, payload)
        latency_ms = (self._clock() - started) * 1000

        raw_usage = body.get("usage")
        usage: dict[str, Any] = raw_usage if isinstance(raw_usage, dict) else {}
        return ChatResponse(
            content=_content(body),
            model_id=str(body.get("model") or self._model),
            input_tokens=_count(usage, "prompt_tokens"),
            output_tokens=_count(usage, "completion_tokens"),
            latency_ms=round(latency_ms, 1),
        )


def _content(body: dict[str, Any]) -> str:
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise ModelResponseError("completion has no choices")
    message = choices[0].get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str) or not content.strip():
        raise ModelResponseError("completion has no text content")
    return content


def _count(usage: dict[str, Any], key: str) -> int:
    """Token counts are optional in FPT's docs; a missing or odd value is recorded as 0."""
    value = usage.get(key)
    return value if isinstance(value, int) and value >= 0 else 0
