from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.users.limits import MAX_DISPLAY_NAME, MAX_EMAIL


class CreateUserIn(BaseModel):
    email: str = Field(min_length=3, max_length=MAX_EMAIL)
    display_name: str = Field(min_length=1, max_length=MAX_DISPLAY_NAME)
    role: Literal["admin", "member", "auditor"] = "member"
    org_id: uuid.UUID | None = None
    status: Literal["invited", "active"] = "invited"


class UpdateUserIn(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=MAX_DISPLAY_NAME)
    role: Literal["admin", "member", "auditor"] | None = None
    org_id: uuid.UUID | None = None


class PatchMeIn(BaseModel):
    display_name: str = Field(min_length=1, max_length=MAX_DISPLAY_NAME)


class UserOut(BaseModel):
    uuid: uuid.UUID
    email: str
    display_name: str
    role: str
    status: str
    org_id: uuid.UUID | None
    disabled_at: datetime | None
    created_at: datetime


class UserStatsOut(BaseModel):
    role: str
    status: str
    count: int


class CreateOrgIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    notification_email: str = Field(min_length=3, max_length=MAX_EMAIL)


class OrgOut(BaseModel):
    uuid: uuid.UUID
    name: str
    notification_email: str
    created_at: datetime
