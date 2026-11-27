from __future__ import annotations

import uuid

from fastapi import APIRouter
from sqlalchemy import select

from app.audit.models import AuditEvent
from app.audit.schemas import AuditEventOut
from app.prior_auth.services.common import get_request
from app.shared.deps import AdminOrAuditor, DbSession
from app.shared.errors import OPENAPI_ERROR_RESPONSES

router = APIRouter(tags=["audit"], responses=OPENAPI_ERROR_RESPONSES)


@router.get("/v1/prior-auths/{request_id}/audit", response_model=list[AuditEventOut])
def get_audit(request_id: uuid.UUID, db: DbSession, ctx: AdminOrAuditor) -> list[AuditEventOut]:
    get_request(db, request_id)
    oldest_first = AuditEvent.at.asc()
    stmt = select(AuditEvent).where(AuditEvent.request_id == request_id).order_by(oldest_first)
    rows = db.scalars(stmt).all()
    return [AuditEventOut.model_validate(r) for r in rows]
