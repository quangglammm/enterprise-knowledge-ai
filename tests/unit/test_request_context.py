import logging

import pytest
from fastapi.testclient import TestClient


def test_generates_request_id_when_absent(client: TestClient) -> None:
    response = client.get("/health/live")

    request_id = response.headers["x-request-id"]
    assert len(request_id) == 32


def test_echoes_valid_caller_request_id(client: TestClient) -> None:
    response = client.get("/health/live", headers={"x-request-id": "trace-abc.123"})

    assert response.headers["x-request-id"] == "trace-abc.123"


@pytest.mark.parametrize("bad_id", ["has space", "x" * 65, "inject\u2028line"])
def test_replaces_unsafe_caller_request_id(client: TestClient, bad_id: str) -> None:
    response = client.get("/health/live", headers={"x-request-id": bad_id.encode("utf-8")})

    assert response.headers["x-request-id"] != bad_id
    assert len(response.headers["x-request-id"]) == 32


def test_request_log_carries_request_id(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger="enterprise_knowledge.api.request"):
        response = client.get("/health/live", headers={"x-request-id": "req-1"})

    records = [r for r in caplog.records if r.getMessage() == "request completed"]
    assert response.status_code == 200
    assert records, "expected a request log record"
    record = records[-1]
    assert record.request_id == "req-1"  # type: ignore[attr-defined]
    assert record.path == "/health/live"  # type: ignore[attr-defined]
    assert record.status_code == 200  # type: ignore[attr-defined]
    assert record.duration_ms >= 0  # type: ignore[attr-defined]
