from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.identity.models import UserRole
from app.identity.schemas import UserContext
from app.intake.models import IntakeRejection
from app.shared.errors import NotFoundError


def get_intake_rejection(db: Session, ctx: UserContext, correlation_id: str) -> IntakeRejection:
    stmt = select(IntakeRejection).where(IntakeRejection.correlation_id == correlation_id)
    row = db.scalar(stmt)
    if row is None:
        raise NotFoundError("Intake rejection not found")
    if ctx.role == UserRole.ops_admin:
        return row
    if ctx.role == UserRole.provider_office and row.practice_id == ctx.practice_id:
        return row
    raise NotFoundError("Intake rejection not found")
