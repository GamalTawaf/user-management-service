from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.clock import utc_now
from app.identity.models import UserStatus
from app.identity.schemas import UserContext
from app.outbox.services import enqueue_status_notice
from app.shared.errors import ConflictError, ForbiddenError, raise_field
from app.users.services.common import audit_commit_refresh, get_user


def disable_user(db: Session, admin: UserContext, user_id: uuid.UUID):
    if admin.user_id == user_id:
        raise ForbiddenError("Cannot disable your own account")
    user = get_user(db, user_id, for_update=True)
    if user.status == UserStatus.disabled:
        raise ConflictError("User already disabled")
    previous = user.status.value
    user.status = UserStatus.disabled
    user.disabled_at = utc_now()
    enqueue_status_notice(db, user, previous=previous)
    return audit_commit_refresh(
        db,
        user,
        actor_user_id=admin.user_id,
        action="user_disable",
        payload={"user_id": str(user_id), "from": previous, "to": "disabled"},
    )


def enable_user(db: Session, admin: UserContext, user_id: uuid.UUID):
    user = get_user(db, user_id, for_update=True)
    if user.status != UserStatus.disabled:
        raise ConflictError("User is not disabled")
    previous = user.status.value
    user.status = UserStatus.active
    user.disabled_at = None
    enqueue_status_notice(db, user, previous=previous)
    return audit_commit_refresh(
        db,
        user,
        actor_user_id=admin.user_id,
        action="user_enable",
        payload={"user_id": str(user_id), "from": previous, "to": "active"},
    )


def activate_user(db: Session, admin: UserContext, user_id: uuid.UUID):
    user = get_user(db, user_id, for_update=True)
    if user.status != UserStatus.invited:
        raise_field(
            "invalid_status",
            "status",
            "Only invited users can be activated",
        )
    previous = user.status.value
    user.status = UserStatus.active
    enqueue_status_notice(db, user, previous=previous)
    return audit_commit_refresh(
        db,
        user,
        actor_user_id=admin.user_id,
        action="user_activate",
        payload={"user_id": str(user_id), "from": previous, "to": "active"},
    )
