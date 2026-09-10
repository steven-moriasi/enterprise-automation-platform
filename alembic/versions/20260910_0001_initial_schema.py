"""Create the workflow execution schema."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260910_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

workflow_status = sa.Enum("DRAFT", "ACTIVE", "ARCHIVED", name="workflowstatus")
execution_status = sa.Enum(
    "QUEUED",
    "RUNNING",
    "RETRY_SCHEDULED",
    "SUCCEEDED",
    "DEAD_LETTER",
    "CANCELLED",
    name="executionstatus",
)
trigger_type = sa.Enum("MANUAL", "WEBHOOK", "SCHEDULE", name="triggertype")
step_status = sa.Enum("PENDING", "RUNNING", "SUCCEEDED", "FAILED", name="stepstatus")
failure_kind = sa.Enum("TRANSIENT", "PERMANENT", name="failurekind")


def upgrade() -> None:
    op.create_table(
        "workflows",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", workflow_status, nullable=False),
        sa.Column("steps", sa.JSON(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("retry_base_seconds", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.String(length=160), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", "version", name="uq_workflow_name_version"),
    )
    op.create_table(
        "executions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workflow_id", sa.String(length=36), nullable=False),
        sa.Column("status", execution_status, nullable=False),
        sa.Column("trigger_type", trigger_type, nullable=False),
        sa.Column("idempotency_key", sa.String(length=160), nullable=False),
        sa.Column("input_payload", sa.JSON(), nullable=False),
        sa.Column("output_payload", sa.JSON(), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("current_step", sa.Integer(), nullable=False),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.String(length=120), nullable=True),
        sa.Column("last_error_message", sa.Text(), nullable=True),
        sa.Column("correlation_id", sa.String(length=160), nullable=False),
        sa.Column("requested_by", sa.String(length=160), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["workflow_id"], ["workflows.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workflow_id", "idempotency_key", name="uq_execution_idempotency"),
    )
    op.create_index("ix_executions_workflow_id", "executions", ["workflow_id"])
    op.create_index("ix_executions_status", "executions", ["status"])
    op.create_index("ix_executions_correlation_id", "executions", ["correlation_id"])
    op.create_index(
        "ix_execution_status_retry",
        "executions",
        ["status", "next_retry_at"],
    )
    op.create_table(
        "audit_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("execution_id", sa.String(length=36), nullable=True),
        sa.Column("workflow_id", sa.String(length=36), nullable=True),
        sa.Column("event_type", sa.String(length=120), nullable=False),
        sa.Column("actor_id", sa.String(length=160), nullable=False),
        sa.Column("correlation_id", sa.String(length=160), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["execution_id"], ["executions.id"]),
        sa.ForeignKeyConstraint(["workflow_id"], ["workflows.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_audit_events_execution_id", "audit_events", ["execution_id"])
    op.create_index("ix_audit_events_workflow_id", "audit_events", ["workflow_id"])
    op.create_index("ix_audit_events_event_type", "audit_events", ["event_type"])
    op.create_index("ix_audit_events_correlation_id", "audit_events", ["correlation_id"])
    op.create_index(
        "ix_audit_execution_created",
        "audit_events",
        ["execution_id", "created_at"],
    )
    op.create_table(
        "dispatch_outbox",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("execution_id", sa.String(length=36), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["execution_id"], ["executions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_dispatch_outbox_execution_id", "dispatch_outbox", ["execution_id"])
    op.create_index(
        "ix_dispatch_outbox_unpublished",
        "dispatch_outbox",
        ["published_at", "created_at"],
    )
    op.create_table(
        "failure_records",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("execution_id", sa.String(length=36), nullable=False),
        sa.Column("step_index", sa.Integer(), nullable=False),
        sa.Column("kind", failure_kind, nullable=False),
        sa.Column("code", sa.String(length=120), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["execution_id"], ["executions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_failure_records_execution_id", "failure_records", ["execution_id"])
    op.create_table(
        "step_executions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("execution_id", sa.String(length=36), nullable=False),
        sa.Column("step_index", sa.Integer(), nullable=False),
        sa.Column("step_name", sa.String(length=120), nullable=False),
        sa.Column("step_kind", sa.String(length=80), nullable=False),
        sa.Column("status", step_status, nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("output_payload", sa.JSON(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["execution_id"], ["executions.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("execution_id", "step_index", name="uq_step_execution_index"),
    )
    op.create_index("ix_step_executions_execution_id", "step_executions", ["execution_id"])


def downgrade() -> None:
    op.drop_table("step_executions")
    op.drop_table("failure_records")
    op.drop_table("dispatch_outbox")
    op.drop_table("audit_events")
    op.drop_table("executions")
    op.drop_table("workflows")
