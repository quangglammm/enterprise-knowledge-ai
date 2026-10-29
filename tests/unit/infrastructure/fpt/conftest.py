"""Scripted HTTP for the FPT adapters: no network, instant and deterministic retries."""

import json
from collections import deque
from collections.abc import Iterable
from typing import Any

import httpx
from pydantic import SecretStr

from enterprise_knowledge.infrastructure.fpt.client import FptClient, RetryPolicy

API_KEY = "sk-test-0123456789"
BASE_URL = "https://mkp.test"

Step = httpx.Response | Exception


def ok(body: dict[str, Any]) -> httpx.Response:
    return httpx.Response(200, json=body)


class ScriptedTransport:
    """Replays responses (or raises transport errors) and records every request."""

    def __init__(self, steps: Iterable[Step]) -> None:
        self._steps: deque[Step] = deque(steps)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        step = self._steps.popleft()
        if isinstance(step, Exception):
            raise step
        return step

    def body(self, index: int = 0) -> Any:
        return json.loads(self.requests[index].content)


class Harness:
    def __init__(self, *steps: Step, max_attempts: int = 3) -> None:
        self.transport = ScriptedTransport(steps)
        self.sleeps: list[float] = []
        self.client = FptClient(
            httpx.AsyncClient(base_url=BASE_URL, transport=httpx.MockTransport(self.transport)),
            api_key=SecretStr(API_KEY),
            retry=RetryPolicy(
                max_attempts=max_attempts, base_delay_seconds=0.5, max_delay_seconds=8
            ),
            sleep=self._sleep,
            random=lambda: 0.5,
        )

    async def _sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
