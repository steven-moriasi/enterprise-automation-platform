"""Add worker execution leases.

Revision ID: 20260910_0003
Revises: 20260910_0002
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260910_0003"
down_revision: str | None = "20260910_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("executions", sa.Column("lease_owner", sa.String(length=160), nullable=True))
    op.add_column("executions", sa.Column("lease_token", sa.String(length=36), nullable=True))
    op.add_column(
        "executions",
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "executions",
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_execution_status_lease",
        "executions",
        ["status", "lease_expires_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_execution_status_lease", table_name="executions")
    op.drop_column("executions", "heartbeat_at")
    op.drop_column("executions", "lease_expires_at")
    op.drop_column("executions", "lease_token")
    op.drop_column("executions", "lease_owner")
