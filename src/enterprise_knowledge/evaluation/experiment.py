"""Versioned experiment configurations for retrieval comparisons (Week 4, ADR-0013).

An experiment names everything that changes a retrieval result: the corpus, the label set
(which pins the chunking settings), the embedder and the embedding input. Each report
records its configuration, so a number can always be traced back to how it was produced.
"""

import tomllib
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from enterprise_knowledge.retrieval.search import RetrievalSettings

_SLUG = r"^[a-z0-9][a-z0-9-]{0,63}$"


class ExperimentConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(pattern=_SLUG)
    description: str = ""
    corpus: str = Field(pattern=_SLUG)  # datasets/corpus/<corpus>
    benchmark: str = Field(pattern=_SLUG)  # datasets/benchmark/<benchmark>, pins chunking
    embedding: Literal["hashing", "fpt"]
    embedding_header: bool = True  # the "title > section" prefix of ADR-0006
    k_values: tuple[int, ...] = (1, 3, 5, 10)
    # Ranking (ADR-0014); defaults match production's EKA_RETRIEVAL_MODE and friends.
    retrieval: Literal["vector", "hybrid"] = "vector"
    rrf_k: int = Field(default=60, ge=1)
    candidates: int = Field(default=50, ge=1)

    @model_validator(mode="after")
    def _k_values_are_usable(self) -> Self:
        if not self.k_values or min(self.k_values) < 1:
            raise ValueError("k_values must be positive")
        if len(set(self.k_values)) != len(self.k_values):
            raise ValueError("k_values must be distinct")
        return self

    def retrieval_settings(self) -> RetrievalSettings:
        return RetrievalSettings(mode=self.retrieval, rrf_k=self.rrf_k, candidates=self.candidates)


def load_experiment(path: Path) -> ExperimentConfig:
    return ExperimentConfig.model_validate(tomllib.loads(path.read_text(encoding="utf-8")))
