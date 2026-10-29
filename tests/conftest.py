import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from enterprise_knowledge.api.app import create_app
from enterprise_knowledge.api.health import ReadinessCheck
from enterprise_knowledge.config import Environment, Settings
from enterprise_knowledge.infrastructure.postgres.migrate import migrate

TEST_DATABASE_ENV = "EKA_TEST_DATABASE_URL"


@pytest.fixture(autouse=True)
def _isolate_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests see only the settings they pass. A developer's .env or exported EKA_* values
    (real model API keys among them) must never reach a test: no paid calls (CLAUDE.md)."""
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    for name in [n for n in os.environ if n.startswith("EKA_") and n != TEST_DATABASE_ENV]:
        monkeypatch.delenv(name)


@pytest.fixture
def settings() -> Settings:
    return Settings(
        environment=Environment.TEST,
        database_url=SecretStr("postgresql://eka:eka@localhost:5432/eka_test"),
        log_json=True,
    )


def make_client(settings: Settings, checks: dict[str, ReadinessCheck] | None = None) -> TestClient:
    app: FastAPI = create_app(settings, readiness_checks=checks)
    return TestClient(app)


@pytest.fixture
def client(settings: Settings) -> TestClient:
    return make_client(settings)


@pytest.fixture(scope="session")
def postgres_url() -> str:
    """A migrated test database. Only integration tests request this fixture."""
    url = os.environ.get(TEST_DATABASE_ENV)
    if not url:
        pytest.fail(
            f"integration tests need {TEST_DATABASE_ENV}, e.g. "
            "postgresql://eka:eka@localhost:5432/eka_test (see README)"
        )
    migrate(url)
    return url
