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
    # "hashing" is a deterministic dev embedder with no semantics; FPT arrives in Week 3.
    embedding_provider: Literal["hashing"] = "hashing"

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
