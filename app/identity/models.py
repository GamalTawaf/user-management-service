import enum
import uuid as uuid_lib
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Enum, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class UserRole(enum.StrEnum):
    """API actor roles. Wire values stay stable for JWT/RBAC.

    Use ``people_name`` only in human-facing prose (emails, OpenAPI narrative).
    Do not put it in JSON field names, audit payloads, or role wire values.
    """

    provider_office = "provider_office"
    reviewer = "reviewer"
    ops_admin = "ops_admin"
    member = "member"
    auditor = "auditor"

    @property
    def people_name(self) -> str:
        """Short plain-language label for people-facing copy."""
        return {
            UserRole.provider_office: "doctors' office",
            UserRole.reviewer: "nurse or physician",
            UserRole.ops_admin: "operations admin",
            UserRole.member: "patient",
            UserRole.auditor: "auditor",
        }[self]


class User(Base):
    """Signed-in actor (office staff, reviewer, ops, auditor, or member portal user)."""

    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(
            "(role <> 'member') OR (member_id IS NOT NULL)",
            name="ck_member_role_requires_member_id",
        ),
    )

    uuid: Mapped[uuid_lib.UUID] = mapped_column(
        "id", UUID(as_uuid=True), primary_key=True, default=uuid_lib.uuid4
    )
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    role: Mapped[UserRole] = mapped_column(Enum(UserRole, name="user_role"), nullable=False)
    practice_id: Mapped[uuid_lib.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("practices.id"), nullable=True
    )
    member_id: Mapped[uuid_lib.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("members.id"), nullable=True
    )
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
