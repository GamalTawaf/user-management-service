from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.identity.models import User, UserRole
from app.identity.schemas import UserContext
from app.orgs.models import Organization
from app.shared.errors import FieldError, raise_validation
from app.users.schemas import PatchMeIn, UpdateUserIn
from app.users.services.common import audit_commit_refresh, get_user


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
