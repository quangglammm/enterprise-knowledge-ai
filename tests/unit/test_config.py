from pathlib import Path

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


def settings(**values: object) -> Settings:
    return Settings.model_validate({"database_url": "postgresql://u:p@db/eka", **values})


def test_model_providers_default_to_offline_development_mode() -> None:
    defaults = settings()

    assert defaults.embedding_provider == "hashing"
    assert defaults.llm_api_key is None
    assert defaults.llm_json_mode is False
    assert defaults.embedding_model == "Vietnamese_Embedding"
    assert defaults.llm_base_url == defaults.embedding_base_url == "https://mkp-api.fptcloud.com"


def test_fpt_embeddings_require_an_api_key() -> None:
    with pytest.raises(ValidationError, match="EKA_EMBEDDING_API_KEY"):
        settings(embedding_provider="fpt")


def test_llm_api_key_requires_a_model() -> None:
    with pytest.raises(ValidationError, match="EKA_LLM_MODEL"):
        settings(llm_api_key="sk-x")


def test_answer_deadline_must_cover_one_model_request() -> None:
    with pytest.raises(ValidationError, match="answer_timeout_seconds"):
        settings(llm_request_timeout_seconds=30, answer_timeout_seconds=10)


def test_model_api_keys_are_not_exposed() -> None:
    configured = settings(
        llm_api_key="sk-llm-secret",
        llm_model="Llama-3.3-70B-Instruct",
        embedding_provider="fpt",
        embedding_api_key="sk-emb-secret",
    )

    for text in (repr(configured), configured.model_dump_json()):
        assert "sk-llm-secret" not in text
        assert "sk-emb-secret" not in text


def test_tests_never_read_a_local_env_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A developer's real keys in .env must not reach tests (no paid calls, CLAUDE.md)."""
    (tmp_path / ".env").write_text("EKA_LLM_API_KEY=sk-real\nEKA_LLM_MODEL=m\n")
    monkeypatch.chdir(tmp_path)

    assert settings().llm_api_key is None


def test_env_example_loads_with_offline_defaults() -> None:
    """`cp .env.example .env` must start the app: blank placeholders mean unset."""
    example = Path(__file__).resolve().parents[2] / ".env.example"

    loaded = Settings(_env_file=example)

    assert loaded.embedding_provider == "hashing"
    assert (loaded.llm_api_key, loaded.llm_model, loaded.embedding_api_key) == (None, None, None)


def test_retrieval_defaults_to_vector_search() -> None:
    defaults = settings()

    assert (defaults.retrieval_mode, defaults.rrf_k, defaults.hybrid_candidates) == (
        "vector",
        60,
        50,
    )


def test_hybrid_retrieval_reads_its_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EKA_DATABASE_URL", "postgresql://u:p@db/eka")
    monkeypatch.setenv("EKA_RETRIEVAL_MODE", "hybrid")
    monkeypatch.setenv("EKA_RRF_K", "30")
    monkeypatch.setenv("EKA_HYBRID_CANDIDATES", "40")

    loaded = Settings(_env_file=None)

    assert (loaded.retrieval_mode, loaded.rrf_k, loaded.hybrid_candidates) == ("hybrid", 30, 40)


@pytest.mark.parametrize(
    ("field", "value"), [("retrieval_mode", "keyword"), ("rrf_k", 0), ("hybrid_candidates", 0)]
)
def test_invalid_retrieval_settings_fail_clearly(field: str, value: object) -> None:
    with pytest.raises(ValidationError, match=field):
        settings(**{field: value})
