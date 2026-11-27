from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Header, Query
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.audit.models import AuditEvent
from app.audit.schemas import AuditEventOut
from app.identity.models import User, UserRole
from app.orgs.models import Organization
from app.shared.deps import AdminOrAuditor, AdminUser, CurrentUser, DbSession
from app.shared.errors import OPENAPI_ERROR_RESPONSES, ForbiddenError, NotFoundError
from app.users.idempotency import (
    body_hash,
    get_record,
    normalize_key,
    resolve_existing,
    scope_for_admin,
)
from app.users.limits import DEFAULT_PAGE_LIMIT, MAX_PAGE_LIMIT
from app.users.schemas import (
    CreateOrgIn,
    CreateUserIn,
    OrgOut,
    PatchMeIn,
    UpdateUserIn,
    UserOut,
    UserStatsOut,
)
from app.users.serializers import to_org_out, to_user_out
from app.users.service import activate_user as activate_user_svc
from app.users.service import apply_after_id, create_organization, patch_me, update_user
from app.users.service import create_user as create_user_svc
from app.users.service import disable_user as disable_user_svc
from app.users.service import enable_user as enable_user_svc
from app.users.service import get_user as load_user

router = APIRouter(tags=["users"], responses=OPENAPI_ERROR_RESPONSES)

PageLimit = Annotated[int, Query(ge=1, le=MAX_PAGE_LIMIT)]
AfterId = Annotated[uuid.UUID | None, Query()]


@router.get("/v1/me", response_model=UserOut)
def me(db: DbSession, ctx: CurrentUser) -> UserOut:
    user = load_user(db, ctx.user_id)
    return to_user_out(user)


@router.patch("/v1/me", response_model=UserOut)
def me_patch(body: PatchMeIn, db: DbSession, ctx: CurrentUser) -> UserOut:
    user = patch_me(db, ctx, body)
    return to_user_out(user)


@router.get("/v1/users/stats", response_model=list[UserStatsOut])
def user_stats(db: DbSession, _ctx: AdminUser) -> list[UserStatsOut]:
    count_col = func.count(User.uuid).label("count")
    stmt = select(User.role, User.status, count_col).group_by(User.role, User.status)
    rows = db.execute(stmt).all()
    return [
        UserStatsOut(role=row.role.value, status=row.status.value, count=row.count) for row in rows
    ]


@router.get("/v1/users", response_model=list[UserOut])
def list_users(
    db: DbSession,
    _ctx: AdminOrAuditor,
    limit: PageLimit = DEFAULT_PAGE_LIMIT,
    after: AfterId = None,
) -> list[UserOut]:
    stmt = select(User)
    stmt = apply_after_id(stmt, after=after, newest_first=True)
    stmt = stmt.limit(limit)
    rows = db.scalars(stmt).all()
    return [to_user_out(r) for r in rows]


@router.post("/v1/users", response_model=UserOut, status_code=201)
def create_user(
    body: CreateUserIn,
    db: DbSession,
    ctx: AdminUser,
    idempotency_key: Annotated[
        str | None,
        Header(alias="Idempotency-Key", description="Admin retry key for create user."),
    ] = None,
) -> UserOut:
    key = normalize_key(idempotency_key)
    request_hash: str | None = None
    scope = scope_for_admin(ctx.user_id)
    if key is not None:
        request_hash = body_hash(body)
        existing = get_record(db, scope, key)
        if existing is not None:
            return resolve_existing(existing, request_hash)
    try:
        user = create_user_svc(
            db,
            ctx,
            body,
            idempotency_key=key,
            request_hash=request_hash,
            idem_scope=scope,
        )
    except IntegrityError:  # pragma: no cover - concurrent create race
        db.rollback()
        if key is None or request_hash is None:
            raise
        raced = get_record(db, scope, key)
        if raced is None:
            raise
        return resolve_existing(raced, request_hash)
    return to_user_out(user)


@router.get("/v1/users/{user_id}", response_model=UserOut)
def get_user(user_id: uuid.UUID, db: DbSession, ctx: CurrentUser) -> UserOut:
    user = load_user(db, user_id)
    is_self = ctx.user_id == user_id
    is_staff = ctx.role in (UserRole.admin, UserRole.auditor)
    if not (is_self or is_staff):
        raise ForbiddenError("Not allowed")
    return to_user_out(user)


@router.patch("/v1/users/{user_id}", response_model=UserOut)
def patch_user(user_id: uuid.UUID, body: UpdateUserIn, db: DbSession, ctx: AdminUser) -> UserOut:
    user = update_user(db, ctx, user_id, body)
    return to_user_out(user)


@router.post("/v1/users/{user_id}/disable", response_model=UserOut)
def disable_user(user_id: uuid.UUID, db: DbSession, ctx: AdminUser) -> UserOut:
    user = disable_user_svc(db, ctx, user_id)
    return to_user_out(user)


@router.post("/v1/users/{user_id}/enable", response_model=UserOut)
def enable_user(user_id: uuid.UUID, db: DbSession, ctx: AdminUser) -> UserOut:
    user = enable_user_svc(db, ctx, user_id)
    return to_user_out(user)


@router.post("/v1/users/{user_id}/activate", response_model=UserOut)
def activate_user(user_id: uuid.UUID, db: DbSession, ctx: AdminUser) -> UserOut:
    user = activate_user_svc(db, ctx, user_id)
    return to_user_out(user)


@router.get("/v1/users/{user_id}/audit", response_model=list[AuditEventOut])
def user_audit(user_id: uuid.UUID, db: DbSession, _ctx: AdminOrAuditor) -> list[AuditEventOut]:
    load_user(db, user_id)
    oldest_first = AuditEvent.at.asc()
    stmt = select(AuditEvent).where(AuditEvent.subject_user_id == user_id).order_by(oldest_first)
    rows = db.scalars(stmt).all()
    return [AuditEventOut.model_validate(r) for r in rows]


@router.get("/v1/orgs", response_model=list[OrgOut], tags=["orgs"])
def list_orgs(db: DbSession, _ctx: AdminOrAuditor) -> list[OrgOut]:
    ordered = select(Organization).order_by(Organization.name, Organization.uuid)
    rows = db.scalars(ordered).all()
    return [to_org_out(r) for r in rows]


@router.post("/v1/orgs", response_model=OrgOut, status_code=201, tags=["orgs"])
def create_org(body: CreateOrgIn, db: DbSession, ctx: AdminUser) -> OrgOut:
    org = create_organization(db, ctx, body)
    return to_org_out(org)


@router.get("/v1/orgs/{org_id}", response_model=OrgOut, tags=["orgs"])
def get_org(org_id: uuid.UUID, db: DbSession, _ctx: AdminOrAuditor) -> OrgOut:
    org = db.get(Organization, org_id)
    if org is None:
        raise NotFoundError("Organization not found")
    return to_org_out(org)
