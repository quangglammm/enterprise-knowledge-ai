import pytest
from pydantic import SecretStr, ValidationError

from enterprise_knowledge.config import Settings


def test_missing_database_url_fails_clearly(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("EKA_DATABASE_URL", raising=False)

    with pytest.raises(ValidationError, match="database_url"):
        Settings(_env_file=None)


def test_reads_prefixed_environment_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EKA_DATABASE_URL", "postgresql://u:p@db:5432/eka")
    monkeypatch.setenv("EKA_LOG_LEVEL", "DEBUG")

    settings = Settings(_env_file=None)

    assert settings.log_level == "DEBUG"
    assert settings.database_dsn().hosts()[0]["host"] == "db"


def test_database_url_is_not_exposed_in_repr() -> None:
    settings = Settings(database_url=SecretStr("postgresql://u:supersecret@db/eka"))

    assert "supersecret" not in repr(settings)
    assert "supersecret" not in settings.model_dump_json()


def test_rejects_invalid_log_level(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EKA_DATABASE_URL", "postgresql://u:p@db/eka")
    monkeypatch.setenv("EKA_LOG_LEVEL", "LOUD")

    with pytest.raises(ValidationError, match="log_level"):
        Settings(_env_file=None)
