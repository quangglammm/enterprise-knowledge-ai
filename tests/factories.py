"""Builders for domain objects with sensible defaults. Override only what a test cares about."""

from datetime import UTC, datetime
from typing import Any

from enterprise_knowledge.domain.access import AccessPolicy, Principal
from enterprise_knowledge.domain.documents import (
    ContentType,
    Document,
    DocumentStatus,
    Language,
    SourceLocation,
)
from enterprise_knowledge.domain.ids import ChunkId, DocumentId, GroupId, TenantId, UserId
from enterprise_knowledge.domain.retrieval import RetrievedEvidence

NOW = datetime(2026, 1, 1, tzinfo=UTC)
TENANT = TenantId("bamboo-harbor")


def make_policy(tenant: TenantId = TENANT, *groups: str) -> AccessPolicy:
    return AccessPolicy(
        tenant_id=tenant,
        allowed_groups=frozenset(GroupId(g) for g in (groups or ("all-staff",))),
    )


def make_principal(tenant: TenantId = TENANT, *groups: str, user: str = "user-1") -> Principal:
    return Principal(
        tenant_id=tenant,
        user_id=UserId(user),
        groups=frozenset(GroupId(g) for g in (groups or ("all-staff",))),
    )


def make_document(**overrides: Any) -> Document:
    fields: dict[str, Any] = {
        "id": DocumentId("doc-1"),
        "title": "Quy chế nghỉ phép",
        "filename": "leave-policy.pdf",
        "content_type": ContentType.PDF,
        "checksum": "0" * 64,
        "version": 1,
        "status": DocumentStatus.PENDING,
        "access": make_policy(),
        "language": Language.VI,
        "created_at": NOW,
        "updated_at": NOW,
    }
    fields.update(overrides)
    return Document(**fields)


def make_evidence(chunk_id: str, *, score: float = 0.9, **overrides: Any) -> RetrievedEvidence:
    fields: dict[str, Any] = {
        "chunk_id": ChunkId(chunk_id),
        "document_id": DocumentId("doc-1"),
        "document_version": 1,
        "title": "Quy chế nghỉ phép",
        "text": "Nhân viên có 12 ngày phép năm.",
        "score": score,
        "source": SourceLocation(page=1),
        "access": make_policy(),
        "language": Language.VI,
    }
    fields.update(overrides)
    return RetrievedEvidence(**fields)
