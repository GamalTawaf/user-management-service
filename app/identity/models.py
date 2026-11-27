import enum
import uuid as uuid_lib
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Enum, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class UserRole(enum.StrEnum):
    """API actor roles. Wire values stay stable for JWT/RBAC."""

    admin = "admin"
    member = "member"
    auditor = "auditor"


class UserStatus(enum.StrEnum):
    invited = "invited"
    active = "active"
    disabled = "disabled"


class User(Base):
    """Account that can authenticate and be managed by admins."""

    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(
            "(status <> 'disabled') OR (disabled_at IS NOT NULL)",
            name="ck_disabled_requires_timestamp",
        ),
        Index("ix_users_org_created", "org_id", "created_at"),
        Index("ix_users_status_role", "status", "role"),
    )

    uuid: Mapped[uuid_lib.UUID] = mapped_column(
        "id", UUID(as_uuid=True), primary_key=True, default=uuid_lib.uuid4
    )
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    role: Mapped[UserRole] = mapped_column(Enum(UserRole, name="user_role"), nullable=False)
    status: Mapped[UserStatus] = mapped_column(
        Enum(UserStatus, name="user_status"), nullable=False, default=UserStatus.invited
    )
    org_id: Mapped[uuid_lib.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=True
    )
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
