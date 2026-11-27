from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.service import write_audit
from app.identity.models import User, UserRole, UserStatus
from app.identity.schemas import UserContext
from app.orgs.models import Organization
from app.outbox.services import enqueue_user_welcome
from app.shared.errors import FieldError, raise_validation
from app.users.idempotency import store_record
from app.users.schemas import CreateUserIn
from app.users.serializers import to_user_out
from app.users.services.common import validate_email

_log = logging.getLogger(__name__)


def create_user(
    db: Session,
    admin: UserContext,
    body: CreateUserIn,
    *,
    idempotency_key: str | None = None,
    request_hash: str | None = None,
    idem_scope: str | None = None,
) -> User:
    errors: list[FieldError] = []
    email_errors = validate_email(body.email)
    errors.extend(email_errors)
    email = body.email.strip().lower()
    display_name = body.display_name.strip()
    if not display_name:
        errors.append(
            FieldError(
                error_code="display_name_required",
                field="display_name",
                message="Display name is required",
            )
        )

    if body.org_id is not None:
        org = db.get(Organization, body.org_id)
        if org is None:
            errors.append(
                FieldError(
                    error_code="org_not_found",
                    field="org_id",
                    message="Organization not found",
                )
            )

    email_match = User.email == email
    existing_stmt = select(User).where(email_match)
    existing = db.scalar(existing_stmt)
    if existing is not None:
        errors.append(
            FieldError(
                error_code="email_taken",
                field="email",
                message="Email is already registered",
            )
        )

    if errors:
        raise_validation(errors)

    role = UserRole(body.role)
    status = UserStatus(body.status)
    user = User(
        email=email,
        display_name=display_name,
        role=role,
        status=status,
        org_id=body.org_id,
    )
    db.add(user)
    db.flush()
    write_audit(
        db,
        actor_user_id=admin.user_id,
        action="user_create",
        payload={
            "user_id": str(user.uuid),
            "email": email,
            "role": role.value,
            "status": status.value,
        },
        subject_user_id=user.uuid,
    )
    enqueue_user_welcome(db, user)

    # Router sets request_hash + scope whenever Idempotency-Key is present.
    if idempotency_key is None:
        db.commit()
        db.refresh(user)
        _log_user_created(user)
        return user

    assert request_hash is not None
    assert idem_scope is not None
    db.refresh(user)
    response = to_user_out(user)
    store_record(
        db,
        org_scope=idem_scope,
        key=idempotency_key,
        request_hash=request_hash,
        user_id=user.uuid,
        response=response,
    )
    db.commit()
    db.refresh(user)
    _log_user_created(user)
    return user


def _log_user_created(user: User) -> None:
    user_id = str(user.uuid)
    role = user.role.value
    status = user.status.value
    _log.info("user_create user_id=%s role=%s status=%s", user_id, role, status)
