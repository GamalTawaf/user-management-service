"""Add auditor value to user_role enum.

Revision ID: 20261125_auditor
Revises: 20261125_outbox
Create Date: 2026-11-25 16:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20261125_auditor"
down_revision: str | None = "20261125_outbox"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "prior_auth"


def upgrade() -> None:
    # ADD VALUE cannot run inside a transaction block on PostgreSQL.
    with op.get_context().autocommit_block():
        op.execute(f"ALTER TYPE {SCHEMA}.user_role ADD VALUE IF NOT EXISTS 'auditor'")


def downgrade() -> None:
    # PostgreSQL cannot drop a single enum value cheaply; leave type as-is.
    pass
