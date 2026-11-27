from __future__ import annotations

from app.identity.models import User
from app.orgs.models import Organization
from app.users.schemas import OrgOut, UserOut


def to_user_out(user: User) -> UserOut:
    return UserOut(
        uuid=user.uuid,
        email=user.email,
        display_name=user.display_name,
        role=user.role.value,
        status=user.status.value,
        org_id=user.org_id,
        disabled_at=user.disabled_at,
        created_at=user.created_at,
    )


def to_org_out(org: Organization) -> OrgOut:
    return OrgOut(
        uuid=org.uuid,
        name=org.name,
        notification_email=org.notification_email,
        created_at=org.created_at,
    )
