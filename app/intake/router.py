from __future__ import annotations

from fastapi import APIRouter

from app.intake.schemas import IntakeRejectionOut
from app.intake.services import get_intake_rejection
from app.shared.deps import DbSession, OfficeOrAdmin
from app.shared.errors import OPENAPI_ERROR_RESPONSES

router = APIRouter(tags=["support"], responses=OPENAPI_ERROR_RESPONSES)


@router.get(
    "/v1/support/intake-rejections/{correlation_id}",
    response_model=IntakeRejectionOut,
)
def lookup_intake_rejection(
    correlation_id: str, db: DbSession, ctx: OfficeOrAdmin
) -> IntakeRejectionOut:
    rejection = get_intake_rejection(db, ctx, correlation_id)
    return IntakeRejectionOut.model_validate(rejection)
