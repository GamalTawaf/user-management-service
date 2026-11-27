import uuid as uuid_lib
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class IntakeRejection(Base):
    """Durable failed submit from a provider office — never enters the review queue."""

    __tablename__ = "intake_rejections"

    uuid: Mapped[uuid_lib.UUID] = mapped_column(
        "id", UUID(as_uuid=True), primary_key=True, default=uuid_lib.uuid4
    )
    correlation_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    actor_user_id: Mapped[uuid_lib.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    practice_id: Mapped[uuid_lib.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("practices.id"), nullable=False
    )
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    payload_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)
    field_errors: Mapped[list] = mapped_column(JSONB, nullable=False)
