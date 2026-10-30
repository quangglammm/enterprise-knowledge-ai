"""Typed application configuration.

All settings come from environment variables prefixed with ``EKA_`` (or a local ``.env``
file). Required values have no default, so a missing variable fails at startup with a
clear validation error instead of surfacing later as a runtime bug.
"""

from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Literal, Self

from pydantic import Field, PostgresDsn, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

FPT_BASE_URL = "https://mkp-api.fptcloud.com"
_HTTP_URL = r"^https?://[^\s]+$"


class Environment(StrEnum):
    LOCAL = "local"
    TEST = "test"
    DEV = "dev"
    PROD = "prod"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="EKA_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        # A blank placeholder such as `EKA_LLM_API_KEY=` means unset, not an empty key.
        env_ignore_empty=True,
        frozen=True,
    )

    environment: Environment = Environment.LOCAL
    service_name: str = "enterprise-knowledge-api"

    # Required: no default. Kept as a secret so it never appears in logs or reprs.
    database_url: SecretStr = Field(
        description="PostgreSQL DSN, e.g. postgresql://user:pass@localhost:5432/eka",
    )

    database_pool_min_size: int = Field(default=1, ge=0)
    database_pool_max_size: int = Field(default=10, ge=1)

    # Must match the vector column created by migrations (ADR-0004); checked at startup.
    embedding_dimension: int = Field(default=1024, ge=1)
    # "hashing" is a deterministic dev embedder with no semantics; "fpt" calls FPT AI
    # Marketplace (ADR-0010). Switching provider or model needs a re-index.
    embedding_provider: Literal["hashing", "fpt"] = "hashing"
    embedding_base_url: str = Field(default=FPT_BASE_URL, pattern=_HTTP_URL)
    embedding_api_key: SecretStr | None = None
    embedding_model: str = Field(default="Vietnamese_Embedding", min_length=1)
    embedding_request_timeout_seconds: float = Field(default=20.0, gt=0)

    # Chat model for /v1/answers. Without an API key, answers return 503 (ADR-0010).
    llm_base_url: str = Field(default=FPT_BASE_URL, pattern=_HTTP_URL)
    llm_api_key: SecretStr | None = None
    llm_model: str | None = Field(default=None, min_length=1)
    # FPT does not document response_format; enable once the model trial confirms it.
    llm_json_mode: bool = False
    llm_request_timeout_seconds: float = Field(default=25.0, gt=0)

    # Attempts per model call, including the first; only transient failures are retried.
    model_max_attempts: int = Field(default=3, ge=1, le=6)

    # Ranking for /v1/search and /v1/answers (ADR-0014): "vector" or "hybrid", which adds
    # full-text search fused by reciprocal rank fusion with constant rrf_k over the top
    # hybrid_candidates of each list. Recorded with every benchmark run (ADR-0013).
    retrieval_mode: Literal["vector", "hybrid"] = "vector"
    rrf_k: int = Field(default=60, ge=1)
    hybrid_candidates: int = Field(default=50, ge=1, le=200)

    # Ingestion jobs (JOB-01, ADR-0016). Attempts include the first; a retry waits
    # base * 2^(attempt-1) seconds, capped and jittered. A message not acked within the
    # visibility timeout is delivered again, so it must exceed the slowest ingestion.
    job_max_attempts: int = Field(default=3, ge=1, le=10)
    job_retry_base_seconds: float = Field(default=10.0, gt=0)
    job_retry_max_seconds: float = Field(default=300.0, gt=0)
    job_visibility_seconds: float = Field(default=300.0, ge=30)
    worker_wait_seconds: float = Field(default=10.0, ge=0)

    answer_top_k: int = Field(default=5, ge=1, le=20)
    # Evidence scoring below this is not sent to the model; None disables the gate until
    # Week 4 calibrates it on the benchmark.
    answer_min_score: float | None = Field(default=None, ge=-1.0, le=1.0)
    # Deadline for one answer, retries and the repair attempt included.
    answer_timeout_seconds: float = Field(default=45.0, gt=0)

    # Identity from X-Tenant-ID / X-User-ID / X-User-Groups headers. Development only:
    # anyone can claim any identity, so it is refused outside local and test environments.
    auth_mode: Literal["dev-headers"] = "dev-headers"

    blob_dir: Path = Path("data/blobs")
    max_upload_bytes: int = Field(default=20 * 1024 * 1024, ge=1)

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_json: bool = True

    api_host: str = "127.0.0.1"
    api_port: int = Field(default=8000, ge=1, le=65535)

    @model_validator(mode="after")
    def _job_backoff_is_ordered(self) -> Self:
        if self.job_retry_max_seconds < self.job_retry_base_seconds:
            raise ValueError("job_retry_max_seconds must be at least job_retry_base_seconds")
        return self

    @model_validator(mode="after")
    def _model_providers_are_complete(self) -> Self:
        if self.embedding_provider == "fpt" and self.embedding_api_key is None:
            raise ValueError("embedding_provider=fpt needs EKA_EMBEDDING_API_KEY")
        if self.llm_api_key is not None and self.llm_model is None:
            raise ValueError("EKA_LLM_API_KEY is set but EKA_LLM_MODEL is not")
        if self.answer_timeout_seconds < self.llm_request_timeout_seconds:
            raise ValueError("answer_timeout_seconds must be at least llm_request_timeout_seconds")
        return self

    @model_validator(mode="after")
    def _dev_only_features_stay_local(self) -> Self:
        if self.environment in (Environment.LOCAL, Environment.TEST):
            return self
        if self.auth_mode == "dev-headers":
            raise ValueError(f"auth_mode=dev-headers is not allowed in {self.environment.value}")
        if self.embedding_provider == "hashing":
            raise ValueError(
                f"embedding_provider=hashing is not allowed in {self.environment.value}"
            )
        return self

    def database_dsn(self) -> PostgresDsn:
        """Validate and return the database DSN. Raises if it is not a Postgres URL."""
        return PostgresDsn(self.database_url.get_secret_value())


@lru_cache
def get_settings() -> Settings:
    """Load settings once per process. Tests pass a Settings instance to create_app instead."""
    return Settings()  # values come from the environment
