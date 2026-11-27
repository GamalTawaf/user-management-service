from __future__ import annotations

import uuid

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.clock import utc_now
from app.identity.models import User, UserRole
from app.identity.schemas import UserContext
from app.prior_auth.models import PriorAuthRequest, RequestStatus
from app.prior_auth.services.common import (
    audit_commit_refresh,
    get_request,
    get_request_for_update,
    has_coi,
)
from app.shared.errors import ConflictError, raise_field


def reassign_request(
    db: Session, admin: UserContext, request_id: uuid.UUID, reviewer_id: uuid.UUID
):
    # Status is enforced by the conditional UPDATE below (avoids duplicate early-check strings
    # that mutmut can flip without a covering assertion path).
    # Lock before capturing previous so concurrent reassigns cannot both audit from=A.
    request = get_request_for_update(db, request_id)
    previous = request.claimed_by_user_id

    reviewer = db.get(User, reviewer_id)
    if reviewer is None or reviewer.role != UserRole.reviewer:
        raise_field(
            "invalid_reviewer",
            "reviewer_id",
            "reviewer_id must reference a reviewer user",
        )
    if has_coi(db, reviewer_id, request.member_id):
        raise_field(
            "reviewer_coi",
            "reviewer_id",
            "Reviewer has a conflict of interest with this member",
        )

    now = utc_now()
    stmt = (
        update(PriorAuthRequest)
        .where(
            PriorAuthRequest.uuid == request_id,
            PriorAuthRequest.status == RequestStatus.in_review,
        )
        .values(
            claimed_by_user_id=reviewer_id,
            claimed_at=now,
        )
        .returning(PriorAuthRequest.uuid)
    )
    moved_id = db.execute(stmt).scalar_one_or_none()
    if moved_id is None:
        fresh = get_request(db, request_id)
        if fresh.status == RequestStatus.decided:
            raise ConflictError("Cannot reassign a decided request")
        raise ConflictError("Request must be in_review to reassign")

    request = get_request(db, request_id, load_procedures=True)
    # in_review rows always have a claimant (DB CHECK); previous is never None here.
    previous_str = str(previous)
    return audit_commit_refresh(
        db,
        request,
        actor_user_id=admin.user_id,
        action="reassign",
        payload={
            "request_id": str(request_id),
            "from": previous_str,
            "to": str(reviewer_id),
        },
    )
