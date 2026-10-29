"""FptClient: authenticated JSON POST with bounded retries for transient failures only."""

import logging

import httpx
import pytest

from enterprise_knowledge.domain.errors import (
    ModelAuthenticationError,
    ModelProviderError,
    ModelRateLimitedError,
    ModelRequestRejectedError,
    ModelResponseError,
    ModelUnavailableError,
)
from enterprise_knowledge.infrastructure.fpt.client import RetryPolicy
from tests.unit.infrastructure.fpt.conftest import API_KEY, Harness, ok


async def test_success_returns_json_and_sends_the_key_as_bearer_token() -> None:
    harness = Harness(ok({"answer": 42}))

    body = await harness.client.post_json("/chat/completions", {"model": "m"})

    assert body == {"answer": 42}
    [request] = harness.transport.requests
    assert request.url == "https://mkp.test/chat/completions"
    assert request.headers["authorization"] == f"Bearer {API_KEY}"
    assert harness.transport.body() == {"model": "m"}


@pytest.mark.parametrize(
    "transient",
    [
        httpx.Response(429),
        httpx.Response(408),
        httpx.Response(500),
        httpx.Response(502),
        httpx.Response(503),
        httpx.Response(504),
        httpx.ConnectError("refused"),
        httpx.ReadTimeout("slow"),
    ],
    ids=["429", "408", "500", "502", "503", "504", "connect", "read-timeout"],
)
async def test_transient_failures_are_retried(transient: httpx.Response | Exception) -> None:
    harness = Harness(transient, ok({"ok": True}))

    assert await harness.client.post_json("/x", {}) == {"ok": True}

    assert len(harness.transport.requests) == 2
    assert harness.sleeps == [0.25]  # full jitter: 0.5 x base delay 0.5


async def test_backoff_grows_exponentially() -> None:
    harness = Harness(httpx.Response(503), httpx.Response(503), ok({}), max_attempts=3)

    await harness.client.post_json("/x", {})

    assert harness.sleeps == [0.25, 0.5]


async def test_retry_after_is_honoured_up_to_the_cap() -> None:
    harness = Harness(
        httpx.Response(429, headers={"retry-after": "3"}),
        httpx.Response(429, headers={"retry-after": "120"}),
        ok({}),
    )

    await harness.client.post_json("/x", {})

    assert harness.sleeps == [3.0, 8.0]


@pytest.mark.parametrize(
    ("failure", "error"),
    [(httpx.Response(429), ModelRateLimitedError), (httpx.Response(503), ModelUnavailableError)],
    ids=["throttled", "unavailable"],
)
async def test_retries_are_bounded_and_end_in_a_typed_failure(
    failure: httpx.Response, error: type[ModelProviderError]
) -> None:
    harness = Harness(failure, failure, failure, ok({}), max_attempts=3)

    with pytest.raises(error):
        await harness.client.post_json("/x", {})

    assert len(harness.transport.requests) == 3
    assert len(harness.sleeps) == 2


@pytest.mark.parametrize(
    ("status", "error"),
    [
        (401, ModelAuthenticationError),
        (403, ModelAuthenticationError),
        (400, ModelRequestRejectedError),
        (404, ModelRequestRejectedError),
        (422, ModelRequestRejectedError),
    ],
)
async def test_permanent_failures_are_not_retried(
    status: int, error: type[ModelProviderError]
) -> None:
    harness = Harness(httpx.Response(status), ok({}))

    with pytest.raises(error, match=str(status)):
        await harness.client.post_json("/x", {})

    assert len(harness.transport.requests) == 1
    assert harness.sleeps == []


@pytest.mark.parametrize(
    "response",
    [httpx.Response(200, text="<html>gateway</html>"), httpx.Response(200, json=[1, 2])],
    ids=["not-json", "not-an-object"],
)
async def test_malformed_success_body_is_a_response_error(response: httpx.Response) -> None:
    harness = Harness(response, ok({}))

    with pytest.raises(ModelResponseError):
        await harness.client.post_json("/x", {})

    assert len(harness.transport.requests) == 1


async def test_errors_and_logs_never_contain_the_key_or_the_body(
    caplog: pytest.LogCaptureFixture,
) -> None:
    echo = f"invalid key {API_KEY} for prompt: secret question"
    harness = Harness(httpx.Response(503, text=echo), httpx.Response(401, text=echo))

    with caplog.at_level(logging.DEBUG), pytest.raises(ModelAuthenticationError) as excinfo:
        await harness.client.post_json("/x", {"messages": "secret question"})

    logged = " ".join(f"{r.getMessage()} {r.__dict__}" for r in caplog.records)
    for text in (API_KEY, "secret question"):
        assert text not in str(excinfo.value)
        assert text not in logged
        assert text not in repr(harness.client)


def test_policy_delay_is_capped() -> None:
    policy = RetryPolicy(max_attempts=10, base_delay_seconds=1, max_delay_seconds=8)

    assert policy.delay(attempt=6, retry_after=None, jitter=1.0) == 8
    assert policy.delay(attempt=1, retry_after=None, jitter=0.0) == 0
