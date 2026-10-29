"""Access control model (ADR-0003): tenant plus allowed groups, checked against a principal."""

from collections.abc import Iterable
from typing import Annotated, Protocol

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from enterprise_knowledge.domain.errors import AccessViolationError
from enterprise_knowledge.domain.ids import ChunkId, GroupId, TenantId, UserId

# Lowercase slugs keep IDs safe in SQL arrays, logs and URLs.
_SLUG = StringConstraints(pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")

TenantField = Annotated[TenantId, _SLUG]
GroupSet = frozenset[Annotated[GroupId, _SLUG]]


class AccessPolicy(BaseModel):
    """Who may read a document and its chunks. Copied onto every chunk (denormalized)."""

    model_config = ConfigDict(frozen=True)

    tenant_id: TenantField
    allowed_groups: GroupSet = Field(min_length=1)


class Principal(BaseModel):
    """The identity a request runs as. Required by every search (ADR-0003)."""

    model_config = ConfigDict(frozen=True)

    tenant_id: TenantField
    user_id: UserId
    groups: GroupSet = frozenset()

    def can_access(self, policy: AccessPolicy) -> bool:
        return self.tenant_id == policy.tenant_id and not self.groups.isdisjoint(
            policy.allowed_groups
        )


class _HasAccess(Protocol):
    @property
    def chunk_id(self) -> ChunkId: ...

    @property
    def access(self) -> AccessPolicy: ...


def ensure_accessible(principal: Principal, items: Iterable[_HasAccess]) -> None:
    """Defense in depth after a search: raise if any item escaped the query-level filter."""
    leaked = [item.chunk_id for item in items if not principal.can_access(item.access)]
    if leaked:
        raise AccessViolationError(leaked)
