"""Chat model that replays scripted outputs and records requests.

Script entries are either response text or an exception to raise, so tests can simulate
throttling, timeouts and invalid JSON without a real provider. ``delay_seconds`` makes
every call slow, to exercise caller-side timeouts.
"""

import asyncio
from collections import deque
from collections.abc import Iterable

from enterprise_knowledge.domain.chat import ChatRequest, ChatResponse


class ScriptedChatModel:
    def __init__(self, script: Iterable[str | Exception], *, model_id: str = "fake-chat") -> None:
        self._script: deque[str | Exception] = deque(script)
        self._model_id = model_id
        self.requests: list[ChatRequest] = []
        self.delay_seconds = 0.0

    @property
    def model_id(self) -> str:
        return self._model_id

    async def complete(self, request: ChatRequest) -> ChatResponse:
        self.requests.append(request)
        if self.delay_seconds:
            await asyncio.sleep(self.delay_seconds)
        if not self._script:
            raise AssertionError("ScriptedChatModel: no scripted response left")
        step = self._script.popleft()
        if isinstance(step, Exception):
            raise step
        prompt_chars = sum(len(m.content) for m in request.messages)
        return ChatResponse(
            content=step,
            model_id=self._model_id,
            input_tokens=prompt_chars // 4,
            output_tokens=len(step) // 4,
            latency_ms=0.0,
        )
