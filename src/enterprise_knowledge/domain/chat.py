"""Provider-neutral chat request and response (ADR-0004)."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ChatMessage(BaseModel):
    model_config = ConfigDict(frozen=True)

    role: Literal["system", "user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    messages: tuple[ChatMessage, ...] = Field(min_length=1)
    max_output_tokens: int = Field(default=1024, ge=1, le=32_000)
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    json_mode: bool = False


class ChatResponse(BaseModel):
    """Usage fields are recorded for cost and latency tracking; content is never logged."""

    model_config = ConfigDict(frozen=True)

    content: str
    model_id: str
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    latency_ms: float = Field(ge=0)
