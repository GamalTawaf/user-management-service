"""Add prior_auth_idempotency_keys for submit Idempotency-Key.

Revision ID: 20261125_idempotency
Revises: 20261125_auditor
Create Date: 2026-11-25 17:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261125_idempotency"
down_revision: str | None = "20261125_auditor"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "prior_auth"


def upgrade() -> None:
    op.create_table(
        "prior_auth_idempotency_keys",
        sa.Column("practice_id", sa.UUID(), nullable=False),
        sa.Column("key", sa.String(length=255), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("response_status", sa.Integer(), nullable=False),
        sa.Column("response_body", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("request_id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["practice_id"],
            [f"{SCHEMA}.practices.id"],
        ),
        sa.ForeignKeyConstraint(
            ["request_id"],
            [f"{SCHEMA}.prior_auth_requests.id"],
        ),
        sa.PrimaryKeyConstraint("practice_id", "key"),
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_table("prior_auth_idempotency_keys", schema=SCHEMA)
