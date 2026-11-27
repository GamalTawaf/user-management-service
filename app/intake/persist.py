from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.audit.writer import write_audit
from app.intake.models import IntakeRejection
from app.shared.errors import FieldError
from app.telemetry import record_intake_rejection


def persist_intake_rejection(
    db: Session,
    *,
    actor_user_id: uuid.UUID,
    practice_id: uuid.UUID,
    payload: dict,
    errors: list[FieldError],
) -> str:
    """Write IntakeRejection + audit; return correlation_id (caller raises ValidationFailure)."""
    correlation_id = uuid.uuid4().hex
    field_errors = [e.model_dump() for e in errors]
    rejection = IntakeRejection(
        correlation_id=correlation_id,
        actor_user_id=actor_user_id,
        practice_id=practice_id,
        payload_snapshot=payload,
        field_errors=field_errors,
    )
    db.add(rejection)
    db.flush()
    practice_id_str = str(practice_id)
    write_audit(
        db,
        actor_user_id=actor_user_id,
        action="intake_reject",
        payload={
            "correlation_id": correlation_id,
            "fields": [e.field for e in errors],
            "practice_id": practice_id_str,
        },
        intake_rejection_id=rejection.uuid,
    )
    db.commit()
    record_intake_rejection()
    return correlation_id
