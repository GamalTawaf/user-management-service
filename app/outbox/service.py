from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.clock import utc_now
from app.config import settings
from app.identity.models import User
from app.orgs.models import Organization
from app.outbox.mailer import send_smtp
from app.outbox.models import OutboxEvent, OutboxKind, OutboxStatus

_log = logging.getLogger(__name__)


def enqueue_user_welcome(db: Session, user: User) -> OutboxEvent:
    to_addr = user.email
    org = db.get(Organization, user.org_id) if user.org_id else None
    org_line = f" Organization: {org.name}." if org is not None else ""
    subject = f"Welcome, {user.display_name}"
    body = (
        f"Hello {user.display_name},\n\n"
        f"An account was created for {user.email} with role {user.role.value}."
        f"{org_line}\n"
        f"Status: {user.status.value}.\n"
    )
    event = OutboxEvent(
        kind=OutboxKind.user_welcome,
        subject_user_id=user.uuid,
        org_id=user.org_id,
        payload={"to": to_addr, "subject": subject, "body": body},
        status=OutboxStatus.pending,
        attempts=0,
    )
    db.add(event)
    return event


def enqueue_status_notice(db: Session, user: User, *, previous: str) -> OutboxEvent:
    subject = f"Account status updated: {user.status.value}"
    body = (
        f"Hello {user.display_name},\n\n"
        f"Your account status changed from {previous} to {user.status.value}.\n"
    )
    event = OutboxEvent(
        kind=OutboxKind.user_status,
        subject_user_id=user.uuid,
        org_id=user.org_id,
        payload={"to": user.email, "subject": subject, "body": body},
        status=OutboxStatus.pending,
        attempts=0,
    )
    db.add(event)
    return event


def claim_batch(db: Session, *, limit: int | None = None) -> list[OutboxEvent]:
    batch_size = limit if limit is not None else settings.outbox_batch_size
    pending = OutboxEvent.status == OutboxStatus.pending
    stmt = (
        select(OutboxEvent)
        .where(pending)
        .order_by(OutboxEvent.created_at)
        .limit(batch_size)
        .with_for_update(skip_locked=True)
    )
    rows = db.scalars(stmt).all()
    return list(rows)


def mark_sent(db: Session, event: OutboxEvent) -> None:
    event.status = OutboxStatus.sent
    event.attempts = event.attempts + 1
    event.sent_at = utc_now()
    event.last_error = None


def mark_failed(db: Session, event: OutboxEvent, error: str) -> None:
    """Record a send error; keep pending until attempts reach outbox_max_attempts."""
    event.attempts = event.attempts + 1
    event.last_error = error[:2000]
    max_attempts = settings.outbox_max_attempts
    if event.attempts >= max_attempts:
        event.status = OutboxStatus.failed
    else:
        event.status = OutboxStatus.pending


def process_batch(db: Session, *, send_fn=send_smtp, limit: int | None = None) -> int:
    events = claim_batch(db, limit=limit)
    for event in events:
        payload = event.payload
        event_id = str(event.uuid)
        try:
            send_fn(payload["to"], payload["subject"], payload["body"])
        except Exception as exc:
            err = str(exc)
            mark_failed(db, event, err)
            if event.status == OutboxStatus.failed:
                _log.warning(
                    "outbox_send_failed event_id=%s attempts=%s error=%s",
                    event_id,
                    event.attempts,
                    err,
                )
            else:
                _log.warning(
                    "outbox_send_retry event_id=%s attempts=%s error=%s",
                    event_id,
                    event.attempts,
                    err,
                )
        else:
            mark_sent(db, event)
            _log.info("outbox_send_ok event_id=%s kind=%s", event_id, event.kind)
    if events:
        db.commit()
    return len(events)
