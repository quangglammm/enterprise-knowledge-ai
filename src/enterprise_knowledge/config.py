"""Typed application configuration.

All settings come from environment variables prefixed with ``EKA_`` (or a local ``.env``
file). Required values have no default, so a missing variable fails at startup with a
clear validation error instead of surfacing later as a runtime bug.
"""

from enum import StrEnum
from functools import lru_cache
from typing import Literal

from pydantic import Field, PostgresDsn, SecretStr
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

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_json: bool = True

    api_host: str = "127.0.0.1"
    api_port: int = Field(default=8000, ge=1, le=65535)

    def database_dsn(self) -> PostgresDsn:
        """Validate and return the database DSN. Raises if it is not a Postgres URL."""
        return PostgresDsn(self.database_url.get_secret_value())


@lru_cache
def get_settings() -> Settings:
    """Load settings once per process. Tests pass a Settings instance to create_app instead."""
    return Settings()  # values come from the environment
