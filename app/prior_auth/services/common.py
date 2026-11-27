from __future__ import annotations

import uuid

from sqlalchemy import ColumnElement, Select, select
from sqlalchemy.orm import Session, raiseload, selectinload

from app.audit.writer import write_audit
from app.master_data.models import ReviewerMemberConflict
from app.prior_auth.models import PriorAuthRequest
from app.shared.errors import NotFoundError


def apply_after_id(
    stmt: Select[tuple[PriorAuthRequest]],
    *,
    after: uuid.UUID | None,
    newest_first: bool,
) -> Select[tuple[PriorAuthRequest]]:
    """Keyset page using the last seen request id (stable under inserts; no offset)."""
    created = PriorAuthRequest.created_at
    rid = PriorAuthRequest.uuid
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


def has_coi(db: Session, reviewer_id: uuid.UUID, member_id: uuid.UUID) -> bool:
    stmt = select(ReviewerMemberConflict).where(
        ReviewerMemberConflict.reviewer_user_id == reviewer_id,
        ReviewerMemberConflict.member_id == member_id,
    )
    return db.scalar(stmt) is not None


def coi_free_clause(reviewer_id: uuid.UUID) -> ColumnElement[bool]:
    """Row filter excluding requests whose member conflicts with this reviewer."""
    conflict = select(ReviewerMemberConflict).where(
        ReviewerMemberConflict.reviewer_user_id == reviewer_id,
        ReviewerMemberConflict.member_id == PriorAuthRequest.member_id,
    )
    return ~conflict.exists()


def get_request(
    db: Session,
    request_id: uuid.UUID,
    *,
    for_update: bool = False,
    load_procedures: bool = False,
) -> PriorAuthRequest:
    stmt = select(PriorAuthRequest).where(PriorAuthRequest.uuid == request_id)
    if load_procedures:
        procedures_load = selectinload(PriorAuthRequest.procedures)
        stmt = stmt.options(procedures_load)
    else:
        # Make load_procedures=False observable (no silent lazy load).
        procedures_block = raiseload(PriorAuthRequest.procedures)
        stmt = stmt.options(procedures_block)
    if for_update:
        stmt = stmt.with_for_update()
    # Re-apply loader options when the row is already in the identity map.
    stmt = stmt.execution_options(populate_existing=True)
    request = db.scalar(stmt)
    if request is None:
        raise NotFoundError("Prior auth request not found")
    return request


def get_request_for_update(
    db: Session,
    request_id: uuid.UUID,
    *,
    load_procedures: bool = False,
) -> PriorAuthRequest:
    """Row-lock helper; lives in do_not_mutate common so `for_update=True` is not a mutant target."""
    return get_request(db, request_id, for_update=True, load_procedures=load_procedures)


def audit_commit_refresh(
    db: Session,
    request: PriorAuthRequest,
    *,
    actor_user_id: uuid.UUID,
    action: str,
    payload: dict,
) -> PriorAuthRequest:
    write_audit(
        db,
        actor_user_id=actor_user_id,
        action=action,
        payload=payload,
        request_id=request.uuid,
    )
    db.commit()
    db.refresh(request)
    return request
