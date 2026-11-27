import enum
import uuid as uuid_lib
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class OutboxKind(enum.StrEnum):
    user_welcome = "user_welcome"
    user_status = "user_status"


class OutboxStatus(enum.StrEnum):
    pending = "pending"
    sent = "sent"
    failed = "failed"


class OutboxEvent(Base):
    """Transactional outbox row — e.g. welcome email after user create."""

    __tablename__ = "outbox_events"
    __table_args__ = (Index("ix_outbox_events_status_created", "status", "created_at"),)

    uuid: Mapped[uuid_lib.UUID] = mapped_column(
        "id", UUID(as_uuid=True), primary_key=True, default=uuid_lib.uuid4
    )
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    subject_user_id: Mapped[uuid_lib.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    org_id: Mapped[uuid_lib.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=True
    )
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=OutboxStatus.pending)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
