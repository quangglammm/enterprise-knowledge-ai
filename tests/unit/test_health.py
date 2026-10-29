from fastapi.testclient import TestClient

from enterprise_knowledge.config import Settings
from tests.conftest import make_client


def test_liveness_returns_ok(client: TestClient) -> None:
    response = client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_ok_when_all_checks_pass(settings: Settings) -> None:
    async def passing() -> None:
        return None

    client = make_client(settings, {"database": passing})

    response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "checks": {"database": "ok"}}


def test_readiness_503_when_a_check_fails(settings: Settings) -> None:
    async def passing() -> None:
        return None

    async def failing() -> None:
        raise ConnectionError("db down")

    client = make_client(settings, {"database": failing, "queue": passing})

    response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {
        "status": "unavailable",
        "checks": {"database": "failed", "queue": "ok"},
    }
    # Failure details stay in logs, never in the response body.
    assert "db down" not in response.text


def test_liveness_ignores_failing_dependencies(settings: Settings) -> None:
    async def failing() -> None:
        raise ConnectionError("db down")

    client = make_client(settings, {"database": failing})

    assert client.get("/health/live").status_code == 200
