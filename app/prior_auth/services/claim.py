from __future__ import annotations

import uuid

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.clock import utc_now
from app.identity.schemas import UserContext
from app.prior_auth.models import PriorAuthRequest, RequestStatus
from app.prior_auth.services.common import audit_commit_refresh, get_request, has_coi
from app.shared.errors import ConflictError, ForbiddenError
from app.telemetry import record_claim_conflict


def claim_request(db: Session, reviewer: UserContext, request_id: uuid.UUID) -> PriorAuthRequest:
    existing = get_request(db, request_id)
    if has_coi(db, reviewer.user_id, existing.member_id):
        raise ForbiddenError("Conflict of interest with this member")

    now = utc_now()
    unclaimed = PriorAuthRequest.claimed_by_user_id.is_(None)
    stmt = (
        update(PriorAuthRequest)
        .where(
            PriorAuthRequest.uuid == request_id,
            PriorAuthRequest.status == RequestStatus.submitted,
            unclaimed,
        )
        .values(
            status=RequestStatus.in_review,
            claimed_by_user_id=reviewer.user_id,
            claimed_at=now,
        )
        .returning(PriorAuthRequest.uuid)
    )
    claimed_id = db.execute(stmt).scalar_one_or_none()
    if claimed_id is None:
        record_claim_conflict()
        raise ConflictError("Request already claimed or not in submitted state")

    request = get_request(db, request_id, load_procedures=True)
    return audit_commit_refresh(
        db,
        request,
        actor_user_id=reviewer.user_id,
        action="claim",
        payload={"request_id": str(request_id), "reviewer_id": str(reviewer.user_id)},
    )
