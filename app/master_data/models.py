import uuid as uuid_lib
from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Practice(Base):
    """Provider office / clinic that submits prior authorization for patients."""

    __tablename__ = "practices"

    uuid: Mapped[uuid_lib.UUID] = mapped_column(
        "id", UUID(as_uuid=True), primary_key=True, default=uuid_lib.uuid4
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    notification_email: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Member(Base):
    """Member — a patient on the health plan."""

    __tablename__ = "members"

    uuid: Mapped[uuid_lib.UUID] = mapped_column(
        "id", UUID(as_uuid=True), primary_key=True, default=uuid_lib.uuid4
    )
    external_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PatientPracticeLink(Base):
    """Which patients a provider office may submit for."""

    __tablename__ = "patient_practice_links"
    __table_args__ = (UniqueConstraint("member_id", "practice_id", name="uq_member_practice"),)

    uuid: Mapped[uuid_lib.UUID] = mapped_column(
        "id", UUID(as_uuid=True), primary_key=True, default=uuid_lib.uuid4
    )
    member_id: Mapped[uuid_lib.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("members.id"), nullable=False
    )
    practice_id: Mapped[uuid_lib.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("practices.id"), nullable=False
    )


class Coverage(Base):
    """Insurance coverage window for a patient (member)."""

    __tablename__ = "coverages"

    uuid: Mapped[uuid_lib.UUID] = mapped_column(
        "id", UUID(as_uuid=True), primary_key=True, default=uuid_lib.uuid4
    )
    member_id: Mapped[uuid_lib.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("members.id"), nullable=False, index=True
    )
    payer_name: Mapped[str] = mapped_column(String(255), nullable=False)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)


class ReviewerMemberConflict(Base):
    """Conflict of interest: this reviewer treats this patient and must not decide their PA."""

    __tablename__ = "reviewer_member_conflicts"
    __table_args__ = (
        UniqueConstraint("reviewer_user_id", "member_id", name="uq_reviewer_member_coi"),
    )

    uuid: Mapped[uuid_lib.UUID] = mapped_column(
        "id", UUID(as_uuid=True), primary_key=True, default=uuid_lib.uuid4
    )
    reviewer_user_id: Mapped[uuid_lib.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    member_id: Mapped[uuid_lib.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("members.id"), nullable=False
    )
