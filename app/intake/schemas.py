from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class IntakeRejectionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    uuid: uuid.UUID
    correlation_id: str
    actor_user_id: uuid.UUID
    practice_id: uuid.UUID
    at: datetime
    payload_snapshot: dict[str, Any]
    field_errors: list[dict[str, Any]]
