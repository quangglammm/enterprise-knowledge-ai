"""Authenticated JSON POST to the FPT AI Marketplace gateway, with bounded retries (ADR-0010).

Only throttling and transient failures are retried, with exponential backoff and full
jitter, honouring Retry-After up to the delay cap. Authentication errors, rejected
requests and malformed bodies fail at once. Errors and logs carry the path, status and
attempt number, never the request body, response body or API key.
"""

import asyncio
import logging
import random as random_module
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any, Self

import httpx
from pydantic import SecretStr

from enterprise_knowledge.domain.errors import (
    ModelAuthenticationError,
    ModelProviderError,
    ModelRateLimitedError,
    ModelRequestRejectedError,
    ModelResponseError,
    ModelUnavailableError,
)

logger = logging.getLogger(__name__)

_RETRYABLE_STATUS = frozenset({408, 429, 500, 502, 503, 504})
_AUTH_STATUS = frozenset({401, 403})


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    max_attempts: int = 3
    base_delay_seconds: float = 0.5
    max_delay_seconds: float = 8.0

    def delay(self, *, attempt: int, retry_after: float | None, jitter: float) -> float:
        """Seconds to wait after failed ``attempt`` (1-based). ``jitter`` is in [0, 1)."""
        if retry_after is not None:
            return min(retry_after, self.max_delay_seconds)
        ceiling = self.base_delay_seconds * 2.0 ** (attempt - 1)
        return jitter * min(self.max_delay_seconds, ceiling)


class FptClient:
    def __init__(
        self,
        http: httpx.AsyncClient,
        *,
        api_key: SecretStr,
        retry: RetryPolicy | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        random: Callable[[], float] = random_module.random,
    ) -> None:
        self._http = http
        self._api_key = api_key
        self._retry = retry or RetryPolicy()
        self._sleep = sleep
        self._random = random

    @classmethod
    def create(
        cls,
        *,
        base_url: str,
        api_key: SecretStr,
        timeout_seconds: float,
        retry: RetryPolicy | None = None,
    ) -> Self:
        """A client that owns its connection pool; close it with ``aclose``."""
        timeout = httpx.Timeout(timeout_seconds, connect=min(timeout_seconds, 10.0))
        return cls(
            httpx.AsyncClient(base_url=base_url, timeout=timeout), api_key=api_key, retry=retry
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def post_json(self, path: str, payload: Mapping[str, object]) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {self._api_key.get_secret_value()}"}
        for attempt in range(1, self._retry.max_attempts + 1):
            try:
                response = await self._http.post(path, json=payload, headers=headers)
            except httpx.TransportError as exc:
                error: ModelProviderError = ModelUnavailableError(
                    f"POST {path} failed: {type(exc).__name__}"
                )
                retry_after = None
                outcome = type(exc).__name__
            else:
                if response.is_success:
                    return _json_object(response, path)
                error = _status_error(response.status_code, path)
                if response.status_code not in _RETRYABLE_STATUS:
                    raise error
                retry_after = _retry_after(response)
                outcome = str(response.status_code)

            if attempt == self._retry.max_attempts:
                logger.warning(
                    "model call failed",
                    extra={"path": path, "outcome": outcome, "attempts": attempt},
                )
                raise error
            delay = self._retry.delay(
                attempt=attempt, retry_after=retry_after, jitter=self._random()
            )
            logger.warning(
                "model call retrying",
                extra={"path": path, "outcome": outcome, "attempt": attempt, "delay_s": delay},
            )
            await self._sleep(delay)
        raise AssertionError("unreachable: max_attempts must be at least 1")


def _status_error(status: int, path: str) -> ModelProviderError:
    message = f"POST {path} returned {status}"
    if status == 429:
        return ModelRateLimitedError(message)
    if status in _AUTH_STATUS:
        return ModelAuthenticationError(message)
    if status in _RETRYABLE_STATUS:
        return ModelUnavailableError(message)
    return ModelRequestRejectedError(message)


def _retry_after(response: httpx.Response) -> float | None:
    """Delay-seconds form only; an HTTP-date falls back to computed backoff."""
    value = response.headers.get("retry-after", "").strip()
    return float(value) if value.isdigit() else None


def _json_object(response: httpx.Response, path: str) -> dict[str, Any]:
    try:
        body = response.json()
    except ValueError:
        raise ModelResponseError(f"POST {path} returned a non-JSON body") from None
    if not isinstance(body, dict):
        raise ModelResponseError(f"POST {path} returned JSON that is not an object")
    return body
