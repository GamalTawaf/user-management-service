from __future__ import annotations

from app.prior_auth.models import PriorAuthRequest, ProcedureDecision
from app.prior_auth.schemas import (
    MemberPriorAuthOut,
    MemberProcedureOut,
    MemberProcedureStatus,
    PriorAuthOut,
    ProcedureOut,
)


def to_prior_auth_out(request: PriorAuthRequest) -> PriorAuthOut:
    return PriorAuthOut(
        uuid=request.uuid,
        member_id=request.member_id,
        practice_id=request.practice_id,
        submitted_by_user_id=request.submitted_by_user_id,
        diagnosis_icd10=request.diagnosis_icd10,
        date_of_service=request.date_of_service,
        clinical_note=request.clinical_note,
        status=request.status.value,
        claimed_by_user_id=request.claimed_by_user_id,
        claimed_at=request.claimed_at,
        decided_by_user_id=request.decided_by_user_id,
        decided_at=request.decided_at,
        created_at=request.created_at,
        procedures=[
            ProcedureOut(
                uuid=p.uuid,
                code=p.code,
                units=p.units,
                sequence=p.sequence,
                decision=p.decision.value,
                denial_reason=p.denial_reason,
            )
            for p in request.procedures
        ],
    )


def to_member_out(request: PriorAuthRequest) -> MemberPriorAuthOut:
    procedures: list[MemberProcedureOut] = []
    for p in request.procedures:
        if p.decision == ProcedureDecision.approved:
            status = MemberProcedureStatus.approved
        elif p.decision == ProcedureDecision.denied:
            status = MemberProcedureStatus.not_approved
        else:
            status = MemberProcedureStatus.pending
        procedures.append(
            MemberProcedureOut(
                uuid=p.uuid,
                code=p.code,
                units=p.units,
                sequence=p.sequence,
                status=status,
            )
        )
    return MemberPriorAuthOut(
        uuid=request.uuid,
        member_id=request.member_id,
        practice_id=request.practice_id,
        diagnosis_icd10=request.diagnosis_icd10,
        date_of_service=request.date_of_service,
        status=request.status.value,
        decided_at=request.decided_at,
        created_at=request.created_at,
        procedures=procedures,
    )
