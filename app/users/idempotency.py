"""Create-user Idempotency-Key storage and helpers."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, func, select
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.db import Base
from app.shared.errors import ConflictError, FieldError, raise_bad_request
from app.users.schemas import CreateUserIn, UserOut

MAX_KEY_LENGTH = 255
_SERVER_NOW = func.now()


class IdempotencyRecord(Base):
    __tablename__ = "user_idempotency_keys"

    org_scope: Mapped[str] = mapped_column(String(64), primary_key=True)
    key: Mapped[str] = mapped_column(String(MAX_KEY_LENGTH), primary_key=True)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    response_status: Mapped[int] = mapped_column(Integer, nullable=False)
    response_body: Mapped[dict] = mapped_column(JSONB, nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=_SERVER_NOW
    )


def normalize_key(raw: str | None) -> str | None:
    if raw is None:
        return None
    key = raw.strip()
    if not key or len(key) > MAX_KEY_LENGTH:
        raise_bad_request(
            [
                FieldError(
                    error_code="idempotency_key_invalid",
                    field="Idempotency-Key",
                    message="Idempotency-Key must be 1-255 non-whitespace characters",
                )
            ]
        )
    return key


def body_hash(body: CreateUserIn) -> str:
    payload = body.model_dump(mode="json")
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    encoded = canonical.encode()
    digest = hashlib.sha256(encoded)
    return digest.hexdigest()


def scope_for_admin(admin_id: uuid.UUID) -> str:
    return f"admin:{admin_id}"


def get_record(db: Session, org_scope: str, key: str) -> IdempotencyRecord | None:
    stmt = select(IdempotencyRecord).where(
        IdempotencyRecord.org_scope == org_scope,
        IdempotencyRecord.key == key,
    )
    return db.scalar(stmt)


def resolve_existing(record: IdempotencyRecord, request_hash: str) -> UserOut:
    if record.request_hash != request_hash:
        raise ConflictError(
            "Idempotency-Key was already used with a different request body",
            errors=[
                FieldError(
                    error_code="idempotency_key_reuse",
                    field="Idempotency-Key",
                    message="Same Idempotency-Key must replay the same request body",
                )
            ],
        )
    return UserOut.model_validate(record.response_body)


def store_record(
    db: Session,
    *,
    org_scope: str,
    key: str,
    request_hash: str,
    user_id: uuid.UUID,
    response: UserOut,
) -> None:
    response_body = response.model_dump(mode="json")
    db.add(
        IdempotencyRecord(
            org_scope=org_scope,
            key=key,
            request_hash=request_hash,
            response_status=201,
            response_body=response_body,
            user_id=user_id,
        )
    )
