from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.audit.models import AuditEvent


def write_audit(
    db: Session,
    *,
    actor_user_id: uuid.UUID,
    action: str,
    payload: dict,
    subject_user_id: uuid.UUID | None = None,
) -> AuditEvent:
    event = AuditEvent(
        actor_user_id=actor_user_id,
        action=action,
        payload=payload,
        subject_user_id=subject_user_id,
    )
    db.add(event)
    return event
