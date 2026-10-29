import pytest
from pydantic import ValidationError

from enterprise_knowledge.domain.access import AccessPolicy, Principal, ensure_accessible
from enterprise_knowledge.domain.errors import AccessViolationError
from enterprise_knowledge.domain.ids import ChunkId, GroupId, TenantId, UserId

ACME = TenantId("acme")
OTHER = TenantId("other")


def policy(tenant: TenantId = ACME, *groups: str) -> AccessPolicy:
    return AccessPolicy(tenant_id=tenant, allowed_groups=frozenset(GroupId(g) for g in groups))


def principal(tenant: TenantId = ACME, *groups: str) -> Principal:
    return Principal(
        tenant_id=tenant, user_id=UserId("u1"), groups=frozenset(GroupId(g) for g in groups)
    )


def test_access_granted_when_tenant_matches_and_groups_intersect() -> None:
    assert principal(ACME, "all-staff", "hr").can_access(policy(ACME, "hr"))


def test_access_denied_without_shared_group() -> None:
    assert not principal(ACME, "all-staff").can_access(policy(ACME, "hr"))


def test_access_denied_across_tenants_even_with_same_group() -> None:
    assert not principal(OTHER, "all-staff").can_access(policy(ACME, "all-staff"))


def test_principal_without_groups_sees_nothing() -> None:
    assert not principal(ACME).can_access(policy(ACME, "all-staff"))


def test_policy_requires_at_least_one_group() -> None:
    with pytest.raises(ValidationError, match="allowed_groups"):
        AccessPolicy(tenant_id=ACME, allowed_groups=frozenset())


@pytest.mark.parametrize("bad", ["", "HR", "has space", "x" * 65])
def test_group_names_are_validated(bad: str) -> None:
    with pytest.raises(ValidationError):
        policy(ACME, bad)


class _Item:
    def __init__(self, chunk_id: str, access: AccessPolicy) -> None:
        self.chunk_id = ChunkId(chunk_id)
        self.access = access


def test_ensure_accessible_passes_for_permitted_items() -> None:
    ensure_accessible(principal(ACME, "hr"), [_Item("c1", policy(ACME, "hr"))])


def test_ensure_accessible_raises_on_any_forbidden_item() -> None:
    items = [_Item("ok", policy(ACME, "all-staff")), _Item("leak", policy(ACME, "hr"))]

    with pytest.raises(AccessViolationError, match="leak"):
        ensure_accessible(principal(ACME, "all-staff"), items)
