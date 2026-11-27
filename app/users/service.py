from __future__ import annotations

import logging
import re
import uuid

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.audit.service import write_audit
from app.clock import utc_now
from app.identity.models import User, UserRole, UserStatus
from app.identity.schemas import UserContext
from app.orgs.models import Organization
from app.outbox.service import enqueue_status_notice, enqueue_user_welcome
from app.shared.errors import (
    ConflictError,
    FieldError,
    ForbiddenError,
    NotFoundError,
    raise_field,
    raise_validation,
)
from app.users.idempotency import store_record
from app.users.schemas import CreateOrgIn, CreateUserIn, PatchMeIn, UpdateUserIn
from app.users.serializers import to_user_out

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_log = logging.getLogger(__name__)


def validate_email(value: str) -> list[FieldError]:
    email = value.strip().lower()
    if not EMAIL_RE.match(email):
        return [
            FieldError(
                error_code="invalid_email",
                field="email",
                message="Email format looks invalid",
            )
        ]
    return []


def get_user(db: Session, user_id: uuid.UUID, *, for_update: bool = False) -> User:
    stmt = select(User).where(User.uuid == user_id)
    if for_update:
        stmt = stmt.with_for_update()
    user = db.scalar(stmt)
    if user is None:
        raise NotFoundError("User not found")
    return user


def apply_after_id(
    stmt: Select[tuple[User]],
    *,
    after: uuid.UUID | None,
    newest_first: bool,
) -> Select[tuple[User]]:
    created = User.created_at
    rid = User.uuid
    created_desc = created.desc()
    rid_desc = rid.desc()
    created_asc = created.asc()
    rid_asc = rid.asc()
    if newest_first:
        ordered = stmt.order_by(created_desc, rid_desc)
    else:
        ordered = stmt.order_by(created_asc, rid_asc)
    if after is None:
        return ordered
    cursor_created = select(created).where(rid == after).scalar_subquery()
    if newest_first:
        older = created < cursor_created
        tie = (created == cursor_created) & (rid < after)
        return ordered.where(older | tie)
    newer = created > cursor_created
    tie = (created == cursor_created) & (rid > after)
    return ordered.where(newer | tie)


def audit_commit_refresh(
    db: Session,
    user: User,
    *,
    actor_user_id: uuid.UUID,
    action: str,
    payload: dict,
) -> User:
    write_audit(
        db,
        actor_user_id=actor_user_id,
        action=action,
        payload=payload,
        subject_user_id=user.uuid,
    )
    db.commit()
    db.refresh(user)
    user_id = str(user.uuid)
    _log.info("user_mutation action=%s user_id=%s", action, user_id)
    return user


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


def update_user(db: Session, admin: UserContext, user_id: uuid.UUID, body: UpdateUserIn) -> User:
    user = get_user(db, user_id, for_update=True)
    errors: list[FieldError] = []
    changes: dict[str, str] = {}

    if body.display_name is not None:
        name = body.display_name.strip()
        if not name:
            errors.append(
                FieldError(
                    error_code="display_name_required",
                    field="display_name",
                    message="Display name is required",
                )
            )
        else:
            user.display_name = name
            changes["display_name"] = name

    if body.role is not None:
        user.role = UserRole(body.role)
        changes["role"] = body.role

    if "org_id" in body.model_fields_set:
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
            else:
                user.org_id = body.org_id
                changes["org_id"] = str(body.org_id)
        else:
            user.org_id = None
            changes["org_id"] = ""

    if errors:
        raise_validation(errors)

    return audit_commit_refresh(
        db,
        user,
        actor_user_id=admin.user_id,
        action="user_update",
        payload={"user_id": str(user_id), "changes": changes},
    )


def patch_me(db: Session, ctx: UserContext, body: PatchMeIn) -> User:
    user = get_user(db, ctx.user_id, for_update=True)
    name = body.display_name.strip()
    if not name:
        raise_validation(
            [
                FieldError(
                    error_code="display_name_required",
                    field="display_name",
                    message="Display name is required",
                )
            ]
        )
    user.display_name = name
    return audit_commit_refresh(
        db,
        user,
        actor_user_id=ctx.user_id,
        action="me_update",
        payload={"user_id": str(ctx.user_id), "display_name": name},
    )


def disable_user(db: Session, admin: UserContext, user_id: uuid.UUID):
    if admin.user_id == user_id:
        raise ForbiddenError("Cannot disable your own account")
    user = get_user(db, user_id, for_update=True)
    if user.status == UserStatus.disabled:
        raise ConflictError("User already disabled")
    previous = user.status.value
    user.status = UserStatus.disabled
    user.disabled_at = utc_now()
    enqueue_status_notice(db, user, previous=previous)
    return audit_commit_refresh(
        db,
        user,
        actor_user_id=admin.user_id,
        action="user_disable",
        payload={"user_id": str(user_id), "from": previous, "to": "disabled"},
    )


def enable_user(db: Session, admin: UserContext, user_id: uuid.UUID):
    user = get_user(db, user_id, for_update=True)
    if user.status != UserStatus.disabled:
        raise ConflictError("User is not disabled")
    previous = user.status.value
    user.status = UserStatus.active
    user.disabled_at = None
    enqueue_status_notice(db, user, previous=previous)
    return audit_commit_refresh(
        db,
        user,
        actor_user_id=admin.user_id,
        action="user_enable",
        payload={"user_id": str(user_id), "from": previous, "to": "active"},
    )


def activate_user(db: Session, admin: UserContext, user_id: uuid.UUID):
    user = get_user(db, user_id, for_update=True)
    if user.status != UserStatus.invited:
        raise_field(
            "invalid_status",
            "status",
            "Only invited users can be activated",
        )
    previous = user.status.value
    user.status = UserStatus.active
    enqueue_status_notice(db, user, previous=previous)
    return audit_commit_refresh(
        db,
        user,
        actor_user_id=admin.user_id,
        action="user_activate",
        payload={"user_id": str(user_id), "from": previous, "to": "active"},
    )


def create_organization(db: Session, admin: UserContext, body: CreateOrgIn) -> Organization:
    errors = validate_email(body.notification_email)
    mapped = [
        FieldError(
            error_code=err.error_code,
            field="notification_email",
            message=err.message,
        )
        for err in errors
    ]
    name = body.name.strip()
    if not name:
        mapped.append(
            FieldError(
                error_code="name_required",
                field="name",
                message="Organization name is required",
            )
        )
    if mapped:
        raise_validation(mapped)

    email = body.notification_email.strip().lower()
    org = Organization(name=name, notification_email=email)
    db.add(org)
    db.flush()
    write_audit(
        db,
        actor_user_id=admin.user_id,
        action="org_create",
        payload={"org_id": str(org.uuid), "name": org.name},
    )
    db.commit()
    db.refresh(org)
    org_id = str(org.uuid)
    _log.info("org_create org_id=%s name=%s", org_id, org.name)
    return org
