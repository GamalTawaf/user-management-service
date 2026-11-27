from __future__ import annotations

import re
import uuid

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.audit.writer import write_audit
from app.identity.models import User
from app.shared.errors import FieldError, NotFoundError

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def validate_email(value: str) -> list[FieldError]:
    email = value.strip().lower()
    if not EMAIL_RE.match(email):
        return [
            FieldError(
                error_code="invalid_email",
                field="email",
                message="Email format looks invalid",
            )
        ]
    return []


def get_user(db: Session, user_id: uuid.UUID, *, for_update: bool = False) -> User:
    stmt = select(User).where(User.uuid == user_id)
    if for_update:
        stmt = stmt.with_for_update()
    user = db.scalar(stmt)
    if user is None:
        raise NotFoundError("User not found")
    return user


def apply_after_id(
    stmt: Select[tuple[User]],
    *,
    after: uuid.UUID | None,
    newest_first: bool,
) -> Select[tuple[User]]:
    created = User.created_at
    rid = User.uuid
    created_desc = created.desc()
    rid_desc = rid.desc()
    created_asc = created.asc()
    rid_asc = rid.asc()
    if newest_first:
        ordered = stmt.order_by(created_desc, rid_desc)
    else:
        ordered = stmt.order_by(created_asc, rid_asc)
    if after is None:
        return ordered
    cursor_created = select(created).where(rid == after).scalar_subquery()
    if newest_first:
        older = created < cursor_created
        tie = (created == cursor_created) & (rid < after)
        return ordered.where(older | tie)
    newer = created > cursor_created
    tie = (created == cursor_created) & (rid > after)
    return ordered.where(newer | tie)


def audit_commit_refresh(
    db: Session,
    user: User,
    *,
    actor_user_id: uuid.UUID,
    action: str,
    payload: dict,
) -> User:
    write_audit(
        db,
        actor_user_id=actor_user_id,
        action=action,
        payload=payload,
        subject_user_id=user.uuid,
    )
    db.commit()
    db.refresh(user)
    return user
