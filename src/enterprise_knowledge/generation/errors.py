"""Typed generation failures. The API maps them to 502/504; they are never abstentions."""

from collections.abc import Iterable
from typing import ClassVar

from enterprise_knowledge.domain.errors import DomainError


class GenerationError(DomainError):
    category: ClassVar[str] = "generation_error"


class InvalidModelOutputError(GenerationError):
    """The model's reply is not a valid answer object, even after one repair attempt."""

    category: ClassVar[str] = "invalid_model_output"


class UnresolvedCitationError(GenerationError):
    """The model cited a label that was not one of the evidence blocks it was given."""

    category: ClassVar[str] = "unknown_citation"

    def __init__(self, labels: Iterable[str]) -> None:
        self.labels = frozenset(labels)
        super().__init__(f"citations not in the provided evidence: {sorted(self.labels)}")


class ModelTimeoutError(GenerationError):
    category: ClassVar[str] = "model_timeout"
