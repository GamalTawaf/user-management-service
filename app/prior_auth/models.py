import enum
import uuid as uuid_lib
from datetime import date, datetime

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class RequestStatus(enum.StrEnum):
    submitted = "submitted"
    in_review = "in_review"
    decided = "decided"


class ProcedureDecision(enum.StrEnum):
    pending = "pending"
    approved = "approved"
    denied = "denied"


class PriorAuthRequest(Base):
    """Accepted prior-auth case in the review workflow (not an intake rejection)."""

    __tablename__ = "prior_auth_requests"
    __table_args__ = (
        CheckConstraint(
            "(status <> 'decided') OR (decided_by_user_id IS NOT NULL)",
            name="ck_decided_requires_actor",
        ),
        CheckConstraint(
            "(status <> 'decided') OR (decided_at IS NOT NULL)",
            name="ck_decided_requires_timestamp",
        ),
        CheckConstraint(
            "(status <> 'in_review') OR (claimed_by_user_id IS NOT NULL)",
            name="ck_in_review_requires_claimant",
        ),
        Index("ix_pa_queue", "status", "claimed_by_user_id"),
        Index("ix_pa_member_created", "member_id", "created_at"),
        Index("ix_pa_practice_created", "practice_id", "created_at"),
    )

    uuid: Mapped[uuid_lib.UUID] = mapped_column(
        "id", UUID(as_uuid=True), primary_key=True, default=uuid_lib.uuid4
    )
    member_id: Mapped[uuid_lib.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("members.id"), nullable=False
    )
    practice_id: Mapped[uuid_lib.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("practices.id"), nullable=False
    )
    submitted_by_user_id: Mapped[uuid_lib.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    diagnosis_icd10: Mapped[str] = mapped_column(String(16), nullable=False)
    date_of_service: Mapped[date] = mapped_column(Date, nullable=False)
    clinical_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[RequestStatus] = mapped_column(
        Enum(RequestStatus, name="request_status"), nullable=False
    )
    claimed_by_user_id: Mapped[uuid_lib.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decided_by_user_id: Mapped[uuid_lib.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    procedures: Mapped[list[PriorAuthProcedure]] = relationship(
        back_populates="request",
        cascade="all, delete-orphan",
        order_by="PriorAuthProcedure.sequence",
    )


class PriorAuthProcedure(Base):
    """One CPT/HCPCS line on a prior-auth request."""

    __tablename__ = "prior_auth_procedures"
    __table_args__ = (
        CheckConstraint("units >= 1", name="ck_procedure_units_at_least_one"),
        CheckConstraint(
            "(decision <> 'denied') OR (denial_reason IS NOT NULL AND btrim(denial_reason) <> '')",
            name="ck_denied_requires_reason",
        ),
    )

    uuid: Mapped[uuid_lib.UUID] = mapped_column(
        "id", UUID(as_uuid=True), primary_key=True, default=uuid_lib.uuid4
    )
    request_id: Mapped[uuid_lib.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("prior_auth_requests.id"), nullable=False, index=True
    )
    code: Mapped[str] = mapped_column(String(16), nullable=False)
    units: Mapped[int] = mapped_column(Integer, nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    decision: Mapped[ProcedureDecision] = mapped_column(
        Enum(ProcedureDecision, name="procedure_decision"),
        nullable=False,
        default=ProcedureDecision.pending,
    )
    denial_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    request: Mapped[PriorAuthRequest] = relationship(back_populates="procedures")
