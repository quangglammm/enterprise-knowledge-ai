from pydantic import BaseModel, ConfigDict, Field


class IngestionLimits(BaseModel):
    """Guards against resource exhaustion from oversized or adversarial uploads."""

    model_config = ConfigDict(frozen=True)

    max_bytes: int = Field(default=20 * 1024 * 1024, ge=1)
    max_pages: int = Field(default=500, ge=1)
