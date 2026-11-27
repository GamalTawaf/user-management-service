"""Initial user management schema.

Revision ID: 20261127_initial
Revises:
Create Date: 2026-11-27
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261127_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "user_mgmt"


def upgrade() -> None:
    op.execute(sa.text(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}"))
    op.execute(
        sa.text(
            f"""
            DO $$ BEGIN
                CREATE TYPE {SCHEMA}.user_role AS ENUM ('admin', 'member', 'auditor');
            EXCEPTION WHEN duplicate_object THEN NULL;
            END $$;
            """
        )
    )
    op.execute(
        sa.text(
            f"""
            DO $$ BEGIN
                CREATE TYPE {SCHEMA}.user_status AS ENUM ('invited', 'active', 'disabled');
            EXCEPTION WHEN duplicate_object THEN NULL;
            END $$;
            """
        )
    )

    user_role = postgresql.ENUM(
        "admin", "member", "auditor", name="user_role", schema=SCHEMA, create_type=False
    )
    user_status = postgresql.ENUM(
        "invited", "active", "disabled", name="user_status", schema=SCHEMA, create_type=False
    )

    op.create_table(
        "organizations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("notification_email", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        schema=SCHEMA,
    )

    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column("role", user_role, nullable=False),
        sa.Column("status", user_status, nullable=False),
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(f"{SCHEMA}.organizations.id"),
        ),
        sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.UniqueConstraint("email"),
        sa.CheckConstraint(
            "(status <> 'disabled') OR (disabled_at IS NOT NULL)",
            name="ck_disabled_requires_timestamp",
        ),
        schema=SCHEMA,
    )
    op.create_index("ix_users_org_created", "users", ["org_id", "created_at"], schema=SCHEMA)
    op.create_index("ix_users_status_role", "users", ["status", "role"], schema=SCHEMA)

    op.create_table(
        "audit_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "subject_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(f"{SCHEMA}.users.id"),
            nullable=True,
        ),
        sa.Column(
            "actor_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(f"{SCHEMA}.users.id"),
            nullable=False,
        ),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_audit_events_subject_user_id", "audit_events", ["subject_user_id"], schema=SCHEMA
    )

    op.create_table(
        "outbox_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("kind", sa.String(64), nullable=False),
        sa.Column(
            "subject_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(f"{SCHEMA}.users.id"),
            nullable=True,
        ),
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(f"{SCHEMA}.organizations.id"),
            nullable=True,
        ),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_outbox_events_status_created",
        "outbox_events",
        ["status", "created_at"],
        schema=SCHEMA,
    )

    op.create_table(
        "user_idempotency_keys",
        sa.Column("org_scope", sa.String(64), primary_key=True),
        sa.Column("key", sa.String(255), primary_key=True),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("response_status", sa.Integer(), nullable=False),
        sa.Column("response_body", postgresql.JSONB(), nullable=False),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(f"{SCHEMA}.users.id"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_table("user_idempotency_keys", schema=SCHEMA)
    op.drop_table("outbox_events", schema=SCHEMA)
    op.drop_table("audit_events", schema=SCHEMA)
    op.drop_table("users", schema=SCHEMA)
    op.drop_table("organizations", schema=SCHEMA)
    op.execute(sa.text(f"DROP TYPE IF EXISTS {SCHEMA}.user_status"))
    op.execute(sa.text(f"DROP TYPE IF EXISTS {SCHEMA}.user_role"))
