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
    request_id: uuid.UUID | None = None,
    intake_rejection_id: uuid.UUID | None = None,
) -> AuditEvent:
    event = AuditEvent(
        actor_user_id=actor_user_id,
        action=action,
        payload=payload,
        request_id=request_id,
        intake_rejection_id=intake_rejection_id,
    )
    db.add(event)
    return event
