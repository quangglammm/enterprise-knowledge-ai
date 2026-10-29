"""Liveness and readiness endpoints.

- ``/health/live``: the process is up. Never checks dependencies, so an outage in
  Postgres does not make the orchestrator restart healthy API containers.
- ``/health/ready``: the instance can serve traffic. Runs registered dependency checks
  (Postgres is added with persistence in Week 1 Day 4) and returns 503 if any fail.
"""

from collections.abc import Awaitable, Callable
from typing import Literal

from fastapi import APIRouter, Request, Response, status
from pydantic import BaseModel

ReadinessCheck = Callable[[], Awaitable[None]]  # raises on failure

router = APIRouter(prefix="/health", tags=["health"])


class LivenessResponse(BaseModel):
    status: Literal["ok"] = "ok"


class ReadinessResponse(BaseModel):
    status: Literal["ok", "unavailable"]
    checks: dict[str, Literal["ok", "failed"]]


@router.get("/live")
async def liveness() -> LivenessResponse:
    return LivenessResponse()


@router.get(
    "/ready",
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": ReadinessResponse}},
)
async def readiness(request: Request, response: Response) -> ReadinessResponse:
    checks_registry: dict[str, ReadinessCheck] = request.app.state.readiness_checks
    results: dict[str, Literal["ok", "failed"]] = {}
    for name, check in checks_registry.items():
        try:
            await check()
            results[name] = "ok"
        except Exception:
            request.app.state.logger.exception("readiness check failed", extra={"check": name})
            results[name] = "failed"

    if all(r == "ok" for r in results.values()):
        return ReadinessResponse(status="ok", checks=results)
    response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadinessResponse(status="unavailable", checks=results)
