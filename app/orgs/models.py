import uuid as uuid_lib
from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Organization(Base):
    """Tenant / workspace users can belong to."""

    __tablename__ = "organizations"

    uuid: Mapped[uuid_lib.UUID] = mapped_column(
        "id", UUID(as_uuid=True), primary_key=True, default=uuid_lib.uuid4
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    notification_email: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
