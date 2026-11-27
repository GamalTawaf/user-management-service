from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class AuditEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    uuid: uuid.UUID
    subject_user_id: uuid.UUID | None
    actor_user_id: uuid.UUID
    action: str
    at: datetime
    payload: dict[str, Any]
