"""Add practices.notification_email and outbox_events.

Revision ID: 20261125_outbox
Revises: 20261125_initial
Create Date: 2026-11-25 15:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261125_outbox"
down_revision: str | None = "20261125_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "prior_auth"


def upgrade() -> None:
    op.add_column(
        "practices",
        sa.Column("notification_email", sa.String(length=255), nullable=True),
        schema=SCHEMA,
    )
    op.execute(
        sa.text(
            f"UPDATE {SCHEMA}.practices "
            "SET notification_email = 'notify@example.com' "
            "WHERE notification_email IS NULL"
        )
    )
    op.alter_column(
        "practices",
        "notification_email",
        existing_type=sa.String(length=255),
        nullable=False,
        schema=SCHEMA,
    )

    op.create_table(
        "outbox_events",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column("request_id", sa.UUID(), nullable=True),
        sa.Column("practice_id", sa.UUID(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["practice_id"],
            [f"{SCHEMA}.practices.id"],
        ),
        sa.ForeignKeyConstraint(
            ["request_id"],
            [f"{SCHEMA}.prior_auth_requests.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_outbox_events_status_created",
        "outbox_events",
        ["status", "created_at"],
        unique=False,
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_outbox_events_status_created",
        table_name="outbox_events",
        schema=SCHEMA,
    )
    op.drop_table("outbox_events", schema=SCHEMA)
    op.drop_column("practices", "notification_email", schema=SCHEMA)
