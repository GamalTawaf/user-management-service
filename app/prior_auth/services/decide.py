from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.clock import utc_now
from app.identity.schemas import UserContext
from app.outbox.services import enqueue_decision_notice
from app.prior_auth.models import ProcedureDecision, RequestStatus
from app.prior_auth.schemas import DecideIn
from app.prior_auth.services.common import audit_commit_refresh, get_request_for_update, has_coi
from app.shared.errors import ConflictError, FieldError, ForbiddenError, raise_validation


def decide_request(db: Session, reviewer: UserContext, request_id: uuid.UUID, body: DecideIn):
    request = get_request_for_update(db, request_id, load_procedures=True)
    if request.status == RequestStatus.decided:
        raise ConflictError("Request already decided")
    if request.status != RequestStatus.in_review or request.claimed_by_user_id != reviewer.user_id:
        raise ForbiddenError("Only the claim holder may decide")
    if has_coi(db, reviewer.user_id, request.member_id):
        raise ForbiddenError("Conflict of interest with this member")

    by_id = {p.uuid: p for p in request.procedures}
    outcome_ids = [o.procedure_id for o in body.outcomes]
    errors: list[FieldError] = []
    if len(outcome_ids) != len(by_id) or set(outcome_ids) != set(by_id):
        errors.append(
            FieldError(
                error_code="procedures_incomplete",
                field="outcomes",
                message="Decision must cover every procedure exactly once",
            )
        )

    for outcome in body.outcomes:
        if outcome.decision not in ("approved", "denied"):
            errors.append(
                FieldError(
                    error_code="invalid_decision",
                    field=f"outcomes[{outcome.procedure_id}].decision",
                    message="Decision must be approved or denied",
                )
            )
        denial_blank = not (outcome.denial_reason or "").strip()
        if outcome.decision == "denied" and denial_blank:
            errors.append(
                FieldError(
                    error_code="denial_reason_required",
                    field=f"outcomes[{outcome.procedure_id}].denial_reason",
                    message="Denial reason is required when denying",
                )
            )

    if errors:
        raise_validation(errors)

    now = utc_now()
    for outcome in body.outcomes:
        proc = by_id[outcome.procedure_id]
        proc.decision = ProcedureDecision(outcome.decision)
        if outcome.decision == "denied":
            proc.denial_reason = str(outcome.denial_reason).strip()
        else:
            proc.denial_reason = None

    request.status = RequestStatus.decided
    request.decided_by_user_id = reviewer.user_id
    request.decided_at = now
    outcomes_payload = [
        {
            "procedure_id": str(o.procedure_id),
            "decision": o.decision,
            "denial_reason": o.denial_reason,
        }
        for o in body.outcomes
    ]
    enqueue_decision_notice(db, request)
    return audit_commit_refresh(
        db,
        request,
        actor_user_id=reviewer.user_id,
        action="decide",
        payload={"request_id": str(request_id), "outcomes": outcomes_payload},
    )
