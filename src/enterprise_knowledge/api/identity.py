"""Who is calling. Development-only header identity until real authentication (SEC-01).

Settings refuse ``auth_mode=dev-headers`` outside local and test environments, because any
caller can claim any tenant and group with these headers.
"""

from fastapi import Request
from pydantic import ValidationError

from enterprise_knowledge.api.errors import AuthenticationError
from enterprise_knowledge.domain.access import Principal

TENANT_HEADER = "x-tenant-id"
USER_HEADER = "x-user-id"
GROUPS_HEADER = "x-user-groups"


def current_principal(request: Request) -> Principal:
    tenant = request.headers.get(TENANT_HEADER)
    user = request.headers.get(USER_HEADER)
    if not tenant or not user:
        raise AuthenticationError(f"missing {TENANT_HEADER} or {USER_HEADER} header")
    groups = request.headers.get(GROUPS_HEADER, "")
    try:
        return Principal.model_validate(
            {
                "tenant_id": tenant.strip(),
                "user_id": user.strip(),
                "groups": frozenset(g.strip() for g in groups.split(",") if g.strip()),
            }
        )
    except ValidationError as exc:
        raise AuthenticationError("invalid identity headers") from exc
