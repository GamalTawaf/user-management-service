from __future__ import annotations

import uuid
from datetime import date, datetime
from enum import StrEnum
from typing import Annotated, Literal, get_args

from pydantic import BaseModel, ConfigDict, Field

from app.prior_auth.limits import MAX_CLINICAL_NOTE, MAX_DENIAL_REASON, MAX_PROCEDURES

PriorAuthStatus = Literal["submitted", "in_review", "decided"]
ProcedureDecisionValue = Literal["pending", "approved", "denied"]
# Decide accepts only approved/denied; OpenAPI documents that contract while the
# service still validates and emits invalid_decision for other strings.
ProcedureDecisionChoice = Literal["approved", "denied"]
_PROCEDURE_DECISION_CHOICES = list(get_args(ProcedureDecisionChoice))


class ProcedureIn(BaseModel):
    # Units bounds enforced in submit service so failures become IntakeRejection rows
    code: str
    units: int


class SubmitPriorAuthIn(BaseModel):
    member_id: uuid.UUID
    diagnosis_icd10: str
    date_of_service: date
    clinical_note: str | None = Field(default=None, max_length=MAX_CLINICAL_NOTE)
    procedures: list[ProcedureIn] = Field(default_factory=list, max_length=MAX_PROCEDURES)


class ProcedureOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    uuid: uuid.UUID
    code: str
    units: int
    sequence: int
    decision: ProcedureDecisionValue
    denial_reason: str | None = None


class PriorAuthOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    uuid: uuid.UUID
    member_id: uuid.UUID
    practice_id: uuid.UUID
    submitted_by_user_id: uuid.UUID
    diagnosis_icd10: str
    date_of_service: date
    clinical_note: str | None
    status: PriorAuthStatus
    claimed_by_user_id: uuid.UUID | None
    claimed_at: datetime | None
    decided_by_user_id: uuid.UUID | None
    decided_at: datetime | None
    created_at: datetime
    procedures: list[ProcedureOut]


class MemberProcedureStatus(StrEnum):
    approved = "approved"
    not_approved = "not_approved"
    pending = "pending"


class MemberProcedureOut(BaseModel):
    uuid: uuid.UUID
    code: str
    units: int
    sequence: int
    status: MemberProcedureStatus


class MemberPriorAuthOut(BaseModel):
    uuid: uuid.UUID
    member_id: uuid.UUID
    practice_id: uuid.UUID
    diagnosis_icd10: str
    date_of_service: date
    status: PriorAuthStatus
    decided_at: datetime | None
    created_at: datetime
    procedures: list[MemberProcedureOut]


class ProcedureDecisionIn(BaseModel):
    procedure_id: uuid.UUID
    decision: Annotated[
        str,
        Field(json_schema_extra={"enum": _PROCEDURE_DECISION_CHOICES}),
    ]
    denial_reason: str | None = Field(default=None, max_length=MAX_DENIAL_REASON)


class DecideIn(BaseModel):
    outcomes: list[ProcedureDecisionIn] = Field(min_length=1, max_length=MAX_PROCEDURES)


class ReassignIn(BaseModel):
    reviewer_id: uuid.UUID


class ReviewerWorkloadOut(BaseModel):
    reviewer_id: uuid.UUID
    display_name: str
    open_count: int
