#!/usr/bin/env -S uv run python
"""Seed synthetic orgs/users and print JWT tokens for local demos."""

from __future__ import annotations

import uuid

from app.db import SessionLocal
from app.identity.auth import mint_token
from app.identity.models import User, UserRole, UserStatus
from app.identity.passwords import hash_password
from app.orgs.models import Organization
from sqlalchemy import select

ORG_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
ADMIN_ID = uuid.UUID("55555555-5555-5555-5555-555555555555")
MEMBER_ID = uuid.UUID("66666666-6666-6666-6666-666666666666")
AUDITOR_ID = uuid.UUID("77777777-7777-7777-7777-777777777777")
INVITED_ID = uuid.UUID("88888888-8888-8888-8888-888888888888")
SEED_PASSWORD = "password12345"


def seed() -> dict[str, str]:
    with SessionLocal() as db:
        if db.scalar(select(User).where(User.uuid == ADMIN_ID)):
            users = {
                "admin": db.get(User, ADMIN_ID),
                "member": db.get(User, MEMBER_ID),
                "auditor": db.get(User, AUDITOR_ID),
            }
        else:
            org = Organization(
                uuid=ORG_ID,
                name="Acme Workspace",
                notification_email="ops@acme.example.com",
            )
            db.add(org)
            db.flush()
            password_hash = hash_password(SEED_PASSWORD)
            admin = User(
                uuid=ADMIN_ID,
                email="admin@example.com",
                display_name="Ops Admin",
                role=UserRole.admin,
                status=UserStatus.active,
                org_id=ORG_ID,
                password_hash=password_hash,
            )
            member = User(
                uuid=MEMBER_ID,
                email="member@example.com",
                display_name="Alex Member",
                role=UserRole.member,
                status=UserStatus.active,
                org_id=ORG_ID,
                password_hash=password_hash,
            )
            auditor = User(
                uuid=AUDITOR_ID,
                email="auditor@example.com",
                display_name="Audit Viewer",
                role=UserRole.auditor,
                status=UserStatus.active,
                password_hash=password_hash,
            )
            invited = User(
                uuid=INVITED_ID,
                email="invited@example.com",
                display_name="Invited User",
                role=UserRole.member,
                status=UserStatus.invited,
                org_id=ORG_ID,
            )
            db.add_all([admin, member, auditor, invited])
            db.commit()
            users = {"admin": admin, "member": member, "auditor": auditor}

        tokens = {name: mint_token(user) for name, user in users.items() if user is not None}
    return tokens


def main() -> None:
    tokens = seed()
    print("Seeded. Bearer tokens:")
    for name, token in tokens.items():
        print(f"  {name}: {token}")
    print(f"org_id={ORG_ID}")
    print(f"admin_id={ADMIN_ID}")
    print(f"member_id={MEMBER_ID}")
    print(f"auditor_id={AUDITOR_ID}")
    print(f"invited_id={INVITED_ID}")
    print(f"seed_password={SEED_PASSWORD}")


if __name__ == "__main__":
    main()
