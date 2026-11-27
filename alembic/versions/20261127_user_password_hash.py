"""Add users.password_hash for login.

Revision ID: 20261127_password
Revises: 20261127_initial
Create Date: 2026-11-27
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261127_password"
down_revision: Union[str, None] = "20261127_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "user_mgmt"


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("password_hash", sa.String(255), nullable=True),
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_column("users", "password_hash", schema=SCHEMA)
