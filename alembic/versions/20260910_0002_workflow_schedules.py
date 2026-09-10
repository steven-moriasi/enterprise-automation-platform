"""Add interval workflow schedules."""

import sqlalchemy as sa

from alembic import op

revision: str = "20260910_0002"
down_revision: str | None = "20260910_0001"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "workflow_schedules",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workflow_id", sa.String(length=36), nullable=False),
        sa.Column("interval_seconds", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.String(length=160), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["workflow_id"], ["workflows.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_workflow_schedules_workflow_id",
        "workflow_schedules",
        ["workflow_id"],
    )
    op.create_index(
        "ix_workflow_schedule_due",
        "workflow_schedules",
        ["enabled", "next_run_at"],
    )


def downgrade() -> None:
    op.drop_table("workflow_schedules")
