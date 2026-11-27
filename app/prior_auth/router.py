from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Header, Query
from sqlalchemy import and_, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from app.identity.models import User, UserRole
from app.prior_auth.idempotency import (
    body_hash,
    get_record,
    normalize_key,
    resolve_existing,
)
from app.prior_auth.limits import DEFAULT_PAGE_LIMIT, MAX_PAGE_LIMIT
from app.prior_auth.models import PriorAuthRequest, RequestStatus
from app.prior_auth.schemas import (
    DecideIn,
    MemberPriorAuthOut,
    PriorAuthOut,
    ReassignIn,
    ReviewerWorkloadOut,
    SubmitPriorAuthIn,
)
from app.prior_auth.serializers import to_member_out, to_prior_auth_out
from app.prior_auth.services.claim import claim_request
from app.prior_auth.services.common import apply_after_id, coi_free_clause, get_request, has_coi
from app.prior_auth.services.decide import decide_request
from app.prior_auth.services.reassign import reassign_request
from app.prior_auth.services.submit import submit_prior_auth
from app.shared.deps import (
    AdminUser,
    CurrentUser,
    DbSession,
    MemberUser,
    OfficeAdminOrAuditor,
    OfficeUser,
    ReviewerUser,
)
from app.shared.errors import OPENAPI_ERROR_RESPONSES, ForbiddenError, NotFoundError

router = APIRouter(tags=["prior-auth"], responses=OPENAPI_ERROR_RESPONSES)

_PROCEDURES = selectinload(PriorAuthRequest.procedures)

PageLimit = Annotated[int, Query(ge=1, le=MAX_PAGE_LIMIT)]
AfterId = Annotated[uuid.UUID | None, Query()]


@router.post(
    "/v1/prior-auths",
    response_model=PriorAuthOut,
    status_code=201,
    summary="Submit prior auth",
    description=(
        "Optional `Idempotency-Key` (unique per practice): same key + same body "
        "replays the stored 201; same key + different body → 409 "
        "`idempotency_key_reuse`. Keys are retained ~24h (prune optional)."
    ),
)
def create_prior_auth(
    body: SubmitPriorAuthIn,
    db: DbSession,
    ctx: OfficeUser,
    idempotency_key: Annotated[
        str | None,
        Header(
            alias="Idempotency-Key",
            description="Partner retry key; scoped to the caller's practice.",
        ),
    ] = None,
) -> PriorAuthOut:
    key = normalize_key(idempotency_key)
    request_hash: str | None = None
    if key is not None and ctx.practice_id is not None:
        request_hash = body_hash(body)
        existing = get_record(db, ctx.practice_id, key)
        if existing is not None:
            return resolve_existing(existing, request_hash)
    try:
        request = submit_prior_auth(
            db,
            ctx,
            body,
            idempotency_key=key,
            request_hash=request_hash,
        )
    except IntegrityError:
        db.rollback()
        if key is None or request_hash is None:
            raise
        raced = get_record(db, ctx.practice_id, key)
        if raced is None:
            raise
        return resolve_existing(raced, request_hash)
    return to_prior_auth_out(request)


@router.get("/v1/prior-auths", response_model=list[PriorAuthOut])
def list_prior_auths(
    db: DbSession,
    ctx: OfficeAdminOrAuditor,
    limit: PageLimit = DEFAULT_PAGE_LIMIT,
    after: AfterId = None,
) -> list[PriorAuthOut]:
    stmt = select(PriorAuthRequest).options(_PROCEDURES)
    if ctx.role == UserRole.provider_office:
        stmt = stmt.where(PriorAuthRequest.practice_id == ctx.practice_id)
    stmt = apply_after_id(stmt, after=after, newest_first=True)
    stmt = stmt.limit(limit)
    rows = db.scalars(stmt).all()
    return [to_prior_auth_out(r) for r in rows]


@router.get("/v1/prior-auths/{request_id}", response_model=PriorAuthOut)
def get_prior_auth(request_id: uuid.UUID, db: DbSession, ctx: CurrentUser) -> PriorAuthOut:
    request = get_request(db, request_id, load_procedures=True)
    if ctx.role == UserRole.provider_office:
        if request.practice_id != ctx.practice_id:
            raise NotFoundError("Prior auth request not found")
    elif ctx.role == UserRole.reviewer:
        own = request.claimed_by_user_id == ctx.user_id
        queueable = request.status == RequestStatus.submitted and request.claimed_by_user_id is None
        if not (own or queueable):
            raise ForbiddenError("Not allowed to view this request")
        if has_coi(db, ctx.user_id, request.member_id):
            raise ForbiddenError("Conflict of interest with this member")
    elif ctx.role == UserRole.ops_admin or ctx.role == UserRole.auditor:
        pass
    else:
        raise ForbiddenError("Not allowed")
    return to_prior_auth_out(request)


@router.get("/v1/review-queue", response_model=list[PriorAuthOut])
def review_queue(
    db: DbSession,
    ctx: ReviewerUser,
    limit: PageLimit = DEFAULT_PAGE_LIMIT,
    after: AfterId = None,
) -> list[PriorAuthOut]:
    unclaimed = PriorAuthRequest.claimed_by_user_id.is_(None)
    conflict_free = coi_free_clause(ctx.user_id)
    stmt = (
        select(PriorAuthRequest)
        .where(PriorAuthRequest.status == RequestStatus.submitted, unclaimed, conflict_free)
        .options(_PROCEDURES)
    )
    stmt = apply_after_id(stmt, after=after, newest_first=False)
    stmt = stmt.limit(limit)
    rows = db.scalars(stmt).all()
    return [to_prior_auth_out(r) for r in rows]


@router.post("/v1/prior-auths/{request_id}/claim", response_model=PriorAuthOut)
def claim(request_id: uuid.UUID, db: DbSession, ctx: ReviewerUser) -> PriorAuthOut:
    request = claim_request(db, ctx, request_id)
    return to_prior_auth_out(request)


@router.post("/v1/prior-auths/{request_id}/decision", response_model=PriorAuthOut)
def decide(request_id: uuid.UUID, body: DecideIn, db: DbSession, ctx: ReviewerUser) -> PriorAuthOut:
    request = decide_request(db, ctx, request_id, body)
    return to_prior_auth_out(request)


@router.post("/v1/prior-auths/{request_id}/reassign", response_model=PriorAuthOut)
def reassign(
    request_id: uuid.UUID, body: ReassignIn, db: DbSession, ctx: AdminUser
) -> PriorAuthOut:
    request = reassign_request(db, ctx, request_id, body.reviewer_id)
    return to_prior_auth_out(request)


@router.get("/v1/reviewers/workload", response_model=list[ReviewerWorkloadOut])
def reviewers_workload(db: DbSession, _ctx: AdminUser) -> list[ReviewerWorkloadOut]:
    claim_match = PriorAuthRequest.claimed_by_user_id == User.uuid
    in_review = PriorAuthRequest.status == RequestStatus.in_review
    join_on = and_(claim_match, in_review)
    open_count = func.count(PriorAuthRequest.uuid)
    open_count_col = open_count.label("open_count")
    stmt = (
        select(User.uuid, User.display_name, open_count_col)
        .outerjoin(PriorAuthRequest, join_on)
        .where(User.role == UserRole.reviewer)
        .group_by(User.uuid)
        .order_by(User.display_name, User.uuid)
    )
    rows = db.execute(stmt).all()
    return [
        ReviewerWorkloadOut(
            reviewer_id=row.uuid,
            display_name=row.display_name,
            open_count=row.open_count,
        )
        for row in rows
    ]


@router.get("/v1/me/prior-auths", response_model=list[MemberPriorAuthOut])
def my_prior_auths(
    db: DbSession,
    ctx: MemberUser,
    limit: PageLimit = DEFAULT_PAGE_LIMIT,
    after: AfterId = None,
) -> list[MemberPriorAuthOut]:
    stmt = (
        select(PriorAuthRequest)
        .where(PriorAuthRequest.member_id == ctx.member_id)
        .options(_PROCEDURES)
    )
    stmt = apply_after_id(stmt, after=after, newest_first=True)
    stmt = stmt.limit(limit)
    rows = db.scalars(stmt).all()
    return [to_member_out(r) for r in rows]


@router.get("/v1/me/prior-auths/{request_id}", response_model=MemberPriorAuthOut)
def my_prior_auth(request_id: uuid.UUID, db: DbSession, ctx: MemberUser) -> MemberPriorAuthOut:
    request = get_request(db, request_id, load_procedures=True)
    if request.member_id != ctx.member_id:
        raise NotFoundError("Prior auth request not found")
    return to_member_out(request)
