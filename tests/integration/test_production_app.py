"""The production composition root against a real database."""

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from enterprise_knowledge.api.app import create_production_app
from enterprise_knowledge.config import Environment, Settings
from enterprise_knowledge.infrastructure.postgres.store import SchemaMismatchError

pytestmark = pytest.mark.integration


def settings_for(url: str, **overrides: object) -> Settings:
    values: dict[str, object] = {
        "environment": Environment.TEST,
        "database_url": SecretStr(url),
    }
    values.update(overrides)
    return Settings.model_validate(values)


def test_readiness_reports_database(postgres_url: str) -> None:
    app = create_production_app(settings_for(postgres_url))

    with TestClient(app) as client:  # the context manager runs startup and shutdown
        response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "checks": {"database": "ok"}}


def test_startup_fails_fast_on_wrong_embedding_dimension(postgres_url: str) -> None:
    app = create_production_app(settings_for(postgres_url, embedding_dimension=768))

    with pytest.raises(SchemaMismatchError), TestClient(app):
        pass
