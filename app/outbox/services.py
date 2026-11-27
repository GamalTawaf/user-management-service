from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.clock import utc_now
from app.config import settings
from app.identity.models import UserRole
from app.master_data.models import Member, Practice
from app.outbox.mailer import send_smtp
from app.outbox.models import OutboxEvent, OutboxKind, OutboxStatus
from app.prior_auth.models import PriorAuthProcedure, PriorAuthRequest

_DECISION_LABEL = {
    "approved": "Approved",
    "denied": "Denied",
}


def _procedure_sequence(proc: PriorAuthProcedure) -> int:
    return proc.sequence


def _patient_label(request: PriorAuthRequest, member: Member | None) -> str:
    """Office-facing patient line: full name when known, plus external id / uuid."""
    if member is None:
        return str(request.member_id)
    return f"{member.full_name} ({member.external_id})"


def render_decision_notice_subject(request: PriorAuthRequest, member: Member | None) -> str:
    # Office-facing email: say "patient", not the API role name "member".
    label = _patient_label(request, member)
    patient = UserRole.member.people_name
    return f"Prior authorization decided for {patient} {label}"


def render_decision_notice_body(request: PriorAuthRequest, member: Member | None) -> str:
    label = _patient_label(request, member)
    patient = UserRole.member.people_name
    reviewer = UserRole.reviewer.people_name
    office = UserRole.provider_office.people_name
    dos = request.date_of_service.isoformat()
    lines = [
        "Hello,",
        "",
        f"A {reviewer} has decided a prior authorization for your {office}.",
        "",
        f"{patient.capitalize()}: {label}",
        f"Date of service: {dos}",
        f"Request ID: {request.uuid}",
        "",
        "Outcomes:",
    ]
    ordered = list(request.procedures)
    ordered.sort(key=_procedure_sequence)
    for proc in ordered:
        decision_value = proc.decision.value
        label = _DECISION_LABEL.get(decision_value, decision_value)
        lines.append(f"  • {proc.code} — {label}")
    lines.extend(
        [
            "",
            "Clinical notes and denial reasons are not included in this message.",
        ]
    )
    return "\n".join(lines)


def enqueue_decision_notice(db: Session, request: PriorAuthRequest) -> OutboxEvent:
    practice = db.get(Practice, request.practice_id)
    member = db.get(Member, request.member_id)
    assert practice is not None
    to_addr = practice.notification_email
    subject = render_decision_notice_subject(request, member)
    body = render_decision_notice_body(request, member)
    event = OutboxEvent(
        kind=OutboxKind.decision_notice,
        request_id=request.uuid,
        practice_id=request.practice_id,
        payload={"to": to_addr, "subject": subject, "body": body},
        status=OutboxStatus.pending,
        attempts=0,
    )
    db.add(event)
    return event


def claim_batch(db: Session, *, limit: int | None = None) -> list[OutboxEvent]:
    batch_size = limit if limit is not None else settings.outbox_batch_size
    stmt = (
        select(OutboxEvent)
        .where(OutboxEvent.status == OutboxStatus.pending)
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
    event.status = OutboxStatus.failed
    event.attempts = event.attempts + 1
    event.last_error = error[:2000]


def process_batch(
    db: Session,
    *,
    send_fn=send_smtp,
    limit: int | None = None,
) -> int:
    events = claim_batch(db, limit=limit)
    for event in events:
        payload = event.payload
        to = payload["to"]
        subject = payload["subject"]
        body = payload["body"]
        try:
            send_fn(to, subject, body)
        except Exception as exc:
            err = str(exc)
            mark_failed(db, event, err)
        else:
            mark_sent(db, event)
    if events:
        db.commit()
    return len(events)
