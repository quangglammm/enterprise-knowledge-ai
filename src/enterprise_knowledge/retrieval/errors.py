from typing import ClassVar

from enterprise_knowledge.domain.errors import DomainError


class InvalidQueryError(DomainError):
    category: ClassVar[str] = "invalid_query"
