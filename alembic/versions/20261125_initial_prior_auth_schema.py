"""Create prior_auth schema and all application tables (single baseline).

Revision ID: 20261125_initial
Revises:
Create Date: 2026-11-25 13:27:09.989019
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261125_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "prior_auth"


def upgrade() -> None:
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")
    op.create_table(
        "members",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("external_id", sa.String(length=64), nullable=False),
        sa.Column("full_name", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("external_id"),
        schema="prior_auth",
    )
    op.create_table(
        "practices",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        schema="prior_auth",
    )
    op.create_table(
        "coverages",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("member_id", sa.UUID(), nullable=False),
        sa.Column("payer_name", sa.String(length=255), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.ForeignKeyConstraint(
            ["member_id"],
            ["prior_auth.members.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        schema="prior_auth",
    )
    op.create_index(
        op.f("ix_prior_auth_coverages_member_id"),
        "coverages",
        ["member_id"],
        unique=False,
        schema="prior_auth",
    )
    op.create_table(
        "patient_practice_links",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("member_id", sa.UUID(), nullable=False),
        sa.Column("practice_id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(
            ["member_id"],
            ["prior_auth.members.id"],
        ),
        sa.ForeignKeyConstraint(
            ["practice_id"],
            ["prior_auth.practices.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("member_id", "practice_id", name="uq_member_practice"),
        schema="prior_auth",
    )
    op.create_table(
        "users",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column(
            "role",
            sa.Enum(
                "provider_office",
                "reviewer",
                "ops_admin",
                "member",
                name="user_role",
                schema="prior_auth",
            ),
            nullable=False,
        ),
        sa.Column("practice_id", sa.UUID(), nullable=True),
        sa.Column("member_id", sa.UUID(), nullable=True),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(role <> 'member') OR (member_id IS NOT NULL)",
            name="ck_member_role_requires_member_id",
        ),
        sa.ForeignKeyConstraint(
            ["member_id"],
            ["prior_auth.members.id"],
        ),
        sa.ForeignKeyConstraint(
            ["practice_id"],
            ["prior_auth.practices.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
        schema="prior_auth",
    )
    op.create_table(
        "intake_rejections",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("correlation_id", sa.String(length=64), nullable=False),
        sa.Column("actor_user_id", sa.UUID(), nullable=False),
        sa.Column("practice_id", sa.UUID(), nullable=False),
        sa.Column(
            "at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("payload_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("field_errors", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["prior_auth.users.id"],
        ),
        sa.ForeignKeyConstraint(
            ["practice_id"],
            ["prior_auth.practices.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        schema="prior_auth",
    )
    op.create_index(
        op.f("ix_prior_auth_intake_rejections_correlation_id"),
        "intake_rejections",
        ["correlation_id"],
        unique=True,
        schema="prior_auth",
    )
    op.create_table(
        "prior_auth_requests",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("member_id", sa.UUID(), nullable=False),
        sa.Column("practice_id", sa.UUID(), nullable=False),
        sa.Column("submitted_by_user_id", sa.UUID(), nullable=False),
        sa.Column("diagnosis_icd10", sa.String(length=16), nullable=False),
        sa.Column("date_of_service", sa.Date(), nullable=False),
        sa.Column("clinical_note", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "submitted", "in_review", "decided", name="request_status", schema="prior_auth"
            ),
            nullable=False,
        ),
        sa.Column("claimed_by_user_id", sa.UUID(), nullable=True),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_by_user_id", sa.UUID(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(status <> 'decided') OR (decided_at IS NOT NULL)",
            name="ck_decided_requires_timestamp",
        ),
        sa.CheckConstraint(
            "(status <> 'decided') OR (decided_by_user_id IS NOT NULL)",
            name="ck_decided_requires_actor",
        ),
        sa.CheckConstraint(
            "(status <> 'in_review') OR (claimed_by_user_id IS NOT NULL)",
            name="ck_in_review_requires_claimant",
        ),
        sa.ForeignKeyConstraint(
            ["claimed_by_user_id"],
            ["prior_auth.users.id"],
        ),
        sa.ForeignKeyConstraint(
            ["decided_by_user_id"],
            ["prior_auth.users.id"],
        ),
        sa.ForeignKeyConstraint(
            ["member_id"],
            ["prior_auth.members.id"],
        ),
        sa.ForeignKeyConstraint(
            ["practice_id"],
            ["prior_auth.practices.id"],
        ),
        sa.ForeignKeyConstraint(
            ["submitted_by_user_id"],
            ["prior_auth.users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        schema="prior_auth",
    )
    op.create_index(
        "ix_pa_member_created",
        "prior_auth_requests",
        ["member_id", "created_at"],
        unique=False,
        schema="prior_auth",
    )
    op.create_index(
        "ix_pa_practice_created",
        "prior_auth_requests",
        ["practice_id", "created_at"],
        unique=False,
        schema="prior_auth",
    )
    op.create_index(
        "ix_pa_queue",
        "prior_auth_requests",
        ["status", "claimed_by_user_id"],
        unique=False,
        schema="prior_auth",
    )
    op.create_table(
        "reviewer_member_conflicts",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("reviewer_user_id", sa.UUID(), nullable=False),
        sa.Column("member_id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(
            ["member_id"],
            ["prior_auth.members.id"],
        ),
        sa.ForeignKeyConstraint(
            ["reviewer_user_id"],
            ["prior_auth.users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("reviewer_user_id", "member_id", name="uq_reviewer_member_coi"),
        schema="prior_auth",
    )
    op.create_table(
        "audit_events",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("request_id", sa.UUID(), nullable=True),
        sa.Column("intake_rejection_id", sa.UUID(), nullable=True),
        sa.Column("actor_user_id", sa.UUID(), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column(
            "at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["prior_auth.users.id"],
        ),
        sa.ForeignKeyConstraint(
            ["intake_rejection_id"],
            ["prior_auth.intake_rejections.id"],
        ),
        sa.ForeignKeyConstraint(
            ["request_id"],
            ["prior_auth.prior_auth_requests.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        schema="prior_auth",
    )
    op.create_index(
        op.f("ix_prior_auth_audit_events_request_id"),
        "audit_events",
        ["request_id"],
        unique=False,
        schema="prior_auth",
    )
    op.create_table(
        "prior_auth_procedures",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("request_id", sa.UUID(), nullable=False),
        sa.Column("code", sa.String(length=16), nullable=False),
        sa.Column("units", sa.Integer(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column(
            "decision",
            sa.Enum(
                "pending", "approved", "denied", name="procedure_decision", schema="prior_auth"
            ),
            nullable=False,
        ),
        sa.Column("denial_reason", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "(decision <> 'denied') OR (denial_reason IS NOT NULL AND btrim(denial_reason) <> '')",
            name="ck_denied_requires_reason",
        ),
        sa.CheckConstraint("units >= 1", name="ck_procedure_units_at_least_one"),
        sa.ForeignKeyConstraint(
            ["request_id"],
            ["prior_auth.prior_auth_requests.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        schema="prior_auth",
    )
    op.create_index(
        op.f("ix_prior_auth_prior_auth_procedures_request_id"),
        "prior_auth_procedures",
        ["request_id"],
        unique=False,
        schema="prior_auth",
    )


def downgrade() -> None:
    op.execute(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE")
